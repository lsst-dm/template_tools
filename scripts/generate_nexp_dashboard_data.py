#!/usr/bin/env python
"""Generate JSON data for the nexp coverage dashboard.

Reads healsparse nexp maps, degrades them for visualization, computes tract
polygon vertices and per-tract coverage fractions, and writes a JSON file
consumed by nexp_coverage.html.
"""

import argparse
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import healpy as hp
import healsparse
import numpy as np

import lsst.daf.butler as dafButler
from lsst.geom import SpherePoint

BANDS = ["u", "g", "r", "i", "z", "y"]
THRESHOLDS = [1, 2, 3, 4, 5, 7, 10]


def load_skymap(butler_repo="/repo/main", skymap_name="lsst_cells_v2"):
    butler = dafButler.Butler(butler_repo)
    return butler.get("skyMap", skymap=skymap_name, collections="skymaps")


def get_healpix_cell_corners(nside, pixels):
    """Get RA/Dec corners for an array of HEALPix pixels (NESTED).

    Returns list of [[ra0,dec0],[ra1,dec1],[ra2,dec2],[ra3,dec3]] per pixel,
    with coordinates rounded to 2 decimal places (~0.6 arcmin).
    """
    all_corners = []
    for pix in pixels:
        boundaries = hp.boundaries(nside, int(pix), step=1, nest=True)
        theta, phi = hp.vec2ang(boundaries.T)
        ra = np.round(np.degrees(phi), 2)
        dec = np.round(90.0 - np.degrees(theta), 2)
        all_corners.append([[r, d] for r, d in zip(ra.tolist(), dec.tolist())])
    return all_corners


def build_nexp_layer(input_dir, band, display_nside=64):
    """Degrade a healsparse nexp map and return pixel data for display."""
    filename = input_dir / f"incremental_template_inputs_{band}_nexp_sum.hsp"
    hsp_map = healsparse.HealSparseMap.read(str(filename))
    degraded = hsp_map.degrade(display_nside, reduction="mean")

    valid_pixels = degraded.valid_pixels
    values = degraded[valid_pixels]

    corners = get_healpix_cell_corners(display_nside, valid_pixels)

    pixels_data = []
    for i, (pix, val) in enumerate(zip(valid_pixels, values)):
        pixels_data.append({
            "c": corners[i],
            "v": round(float(val), 2),
        })

    return pixels_data, float(values.max())


def build_tract_data(input_dir, band, skymap):
    """Compute tract polygons and coverage fractions for a band."""
    filename = input_dir / f"incremental_template_inputs_{band}_nexp_sum.hsp"
    hsp_map = healsparse.HealSparseMap.read(str(filename))
    valid_pixels = hsp_map.valid_pixels
    values = hsp_map[valid_pixels]
    nside = hsp_map.nside_sparse

    theta, phi = hp.pix2ang(nside, valid_pixels, nest=True)
    ra = np.degrees(phi)
    dec = 90.0 - np.degrees(theta)
    tract_ids = skymap.findTractIdArray(ra, dec, degrees=True)

    unique_tracts = np.unique(tract_ids)
    tracts_data = []
    for tract_id in unique_tracts:
        mask = tract_ids == tract_id
        tract_values = values[mask]
        n_pixels = int(len(tract_values))

        tract_info = skymap[int(tract_id)]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            vertices = tract_info.getInnerSkyPolygon().getVertices()
        corners = []
        for v in vertices:
            point = SpherePoint(v)
            corners.append([
                round(point.getRa().asDegrees(), 3),
                round(point.getDec().asDegrees(), 3),
            ])

        fractions = {}
        for thresh in THRESHOLDS:
            fractions[str(thresh)] = round(float(np.sum(tract_values >= thresh) / n_pixels), 4)

        tracts_data.append({
            "id": int(tract_id),
            "corners": corners,
            "n": n_pixels,
            "f": fractions,
        })

    return tracts_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir", type=Path, default=Path("output_incremental_test"),
        help="Directory containing the .hsp files",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("nexp_dashboard_data.json"),
        help="Output JSON file",
    )
    parser.add_argument(
        "--display-nside", type=int, default=64,
        help="NSIDE for degraded display map (default: 64)",
    )
    parser.add_argument(
        "--butler-repo", default="/repo/main",
        help="Butler repository path",
    )
    parser.add_argument(
        "--bands", nargs="+", default=BANDS, choices=BANDS,
        help="Bands to process",
    )
    args = parser.parse_args()

    print("Loading skymap...")
    skymap = load_skymap(args.butler_repo)

    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "display_nside": args.display_nside,
        "thresholds": THRESHOLDS,
        "bands": {},
    }

    for band in args.bands:
        print(f"Processing band {band}...")
        print(f"  Building display pixels (nside={args.display_nside})...")
        pixels_data, max_val = build_nexp_layer(args.input_dir, band, args.display_nside)
        print(f"    {len(pixels_data)} display pixels, max nexp={max_val:.1f}")

        print(f"  Computing tract coverage fractions...")
        tracts_data = build_tract_data(args.input_dir, band, skymap)
        print(f"    {len(tracts_data)} tracts with data")

        output["bands"][band] = {
            "pixels": pixels_data,
            "tracts": tracts_data,
            "max_nexp": round(max_val, 1),
        }

    with open(args.output, "w") as f:
        json.dump(output, f)

    size_mb = args.output.stat().st_size / 1e6
    print(f"Wrote {args.output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
