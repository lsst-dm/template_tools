#!/usr/bin/env python
"""Assign HEALPix nexp map pixels to LSST skymap tracts and compute coverage fractions."""

import argparse
from pathlib import Path

import healpy as hp
import healsparse
import numpy as np
import pandas as pd

import lsst.daf.butler as dafButler


BANDS = ["u", "g", "r", "i", "z", "y"]
THRESHOLDS = [1, 2, 3, 5, 10]


def load_skymap(butler_repo="/repo/main", skymap_name="lsst_cells_v2"):
    butler = dafButler.Butler(butler_repo)
    return butler.get("skyMap", skymap=skymap_name, collections="skymaps")


def assign_pixels_to_tracts(valid_pixels, nside, skymap):
    """Return tract IDs for each valid HEALPix pixel."""
    theta, phi = hp.pix2ang(nside, valid_pixels, nest=True)
    ra = np.degrees(phi)
    dec = 90.0 - np.degrees(theta)
    tract_ids = skymap.findTractIdArray(ra, dec, degrees=True)
    return tract_ids


def compute_tract_fractions(tract_ids, values):
    """For each tract, compute fraction of pixels >= each threshold."""
    unique_tracts = np.unique(tract_ids)
    records = []
    for tract_id in unique_tracts:
        mask = tract_ids == tract_id
        tract_values = values[mask]
        n_pixels = len(tract_values)
        record = {"tract": int(tract_id), "n_pixels": n_pixels}
        for thresh in THRESHOLDS:
            frac = np.sum(tract_values >= thresh) / n_pixels
            record[f"frac_ge_{thresh}"] = frac
        records.append(record)
    return records


def process_band(band, input_dir, skymap):
    filename = input_dir / f"incremental_template_inputs_{band}_nexp_sum.hsp"
    hsp_map = healsparse.HealSparseMap.read(str(filename))
    valid_pixels = hsp_map.valid_pixels
    values = hsp_map[valid_pixels]
    nside = hsp_map.nside_sparse

    tract_ids = assign_pixels_to_tracts(valid_pixels, nside, skymap)
    records = compute_tract_fractions(tract_ids, values)
    df = pd.DataFrame(records)
    df["band"] = band
    return df


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("output_incremental_test"),
        help="Directory containing the .hsp files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tract_nexp_fractions.csv"),
        help="Output CSV file",
    )
    parser.add_argument(
        "--bands",
        nargs="+",
        default=BANDS,
        choices=BANDS,
        help="Bands to process",
    )
    parser.add_argument(
        "--butler-repo",
        default="/repo/main",
        help="Butler repository path",
    )
    args = parser.parse_args()

    print("Loading skymap...")
    skymap = load_skymap(args.butler_repo)

    all_dfs = []
    for band in args.bands:
        print(f"Processing band {band}...")
        df = process_band(band, args.input_dir, skymap)
        all_dfs.append(df)
        print(f"  {len(df)} tracts with data")

    result = pd.concat(all_dfs, ignore_index=True)
    col_order = ["band", "tract", "n_pixels"] + [f"frac_ge_{t}" for t in THRESHOLDS]
    result = result[col_order].sort_values(["band", "tract"])
    result.to_csv(args.output, index=False, float_format="%.4f")
    print(f"Wrote {args.output} ({len(result)} rows)")


if __name__ == "__main__":
    main()
