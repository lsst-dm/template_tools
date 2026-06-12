#!/usr/bin/env python
"""Generate JSON data for the nexp coverage dashboard.

Reads healsparse nexp maps, degrades them for visualization, computes tract
polygon vertices and per-tract coverage fractions, and writes a JSON file
consumed by nexp_coverage.html.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import healpy as hp
import healsparse
import numpy as np

import common

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"

BANDS = common.BANDS
THRESHOLDS = [1, 2, 3, 4, 5, 7, 10]


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

    tract_ids = common.assign_pixels_to_tracts(valid_pixels, nside, skymap)

    tracts_data = []
    for record in common.compute_tract_fractions(tract_ids, values, THRESHOLDS):
        tract_id = record["tract"]
        corners = common.tract_corners(skymap[tract_id], ndigits=3)
        fractions = {
            str(thresh): round(record["fractions"][thresh], 4)
            for thresh in THRESHOLDS
        }
        tracts_data.append({
            "id": tract_id,
            "corners": corners,
            "n": record["n_pixels"],
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
        "--output", type=Path, default=WEB_DIR / "nexp_dashboard_data.json",
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
    skymap = common.load_skymap(args.butler_repo)

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

        print("  Computing tract coverage fractions...")
        tracts_data = build_tract_data(args.input_dir, band, skymap)
        print(f"    {len(tracts_data)} tracts with data")

        output["bands"][band] = {
            "pixels": pixels_data,
            "tracts": tracts_data,
            "max_nexp": round(max_val, 1),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f)

    size_mb = args.output.stat().st_size / 1e6
    print(f"Wrote {args.output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
