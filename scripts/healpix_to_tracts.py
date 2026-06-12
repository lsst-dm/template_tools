#!/usr/bin/env python
"""Assign HEALPix nexp map pixels to LSST skymap tracts and compute coverage fractions."""

import argparse
from pathlib import Path

import healsparse
import pandas as pd

import common

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"

BANDS = common.BANDS
THRESHOLDS = [1, 2, 3, 5, 10]


def process_band(band, input_dir, skymap):
    filename = input_dir / f"incremental_template_inputs_{band}_nexp_sum.hsp"
    hsp_map = healsparse.HealSparseMap.read(str(filename))
    valid_pixels = hsp_map.valid_pixels
    values = hsp_map[valid_pixels]
    nside = hsp_map.nside_sparse

    tract_ids = common.assign_pixels_to_tracts(valid_pixels, nside, skymap)

    records = []
    for record in common.compute_tract_fractions(tract_ids, values, THRESHOLDS):
        row = {"tract": record["tract"], "n_pixels": record["n_pixels"]}
        for thresh in THRESHOLDS:
            row[f"frac_ge_{thresh}"] = record["fractions"][thresh]
        records.append(row)

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
        default=OUTPUT_DIR / "tract_nexp_fractions.csv",
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
    skymap = common.load_skymap(args.butler_repo)

    all_dfs = []
    for band in args.bands:
        print(f"Processing band {band}...")
        df = process_band(band, args.input_dir, skymap)
        all_dfs.append(df)
        print(f"  {len(df)} tracts with data")

    result = pd.concat(all_dfs, ignore_index=True)
    col_order = ["band", "tract", "n_pixels"] + [f"frac_ge_{t}" for t in THRESHOLDS]
    result = result[col_order].sort_values(["band", "tract"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, float_format="%.4f")
    print(f"Wrote {args.output} ({len(result)} rows)")


if __name__ == "__main__":
    main()
