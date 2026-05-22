"""
Query the embargo Butler for deployed template_coadd datasets in
LSSTCam/templates and produce a JSON data file with patch coordinates
for the embargo templates dashboard.
"""

import json
import numpy as np
from collections import defaultdict

import lsst.daf.butler as dafButler
from lsst.geom import SpherePoint, degrees


def query_template_patches(repo="embargo", collection="LSSTCam/templates"):
    """Query Butler for all template_coadd data IDs."""
    butler = dafButler.Butler(repo)

    patches_by_band = defaultdict(list)
    for band in ['u','g','r','i','z','y']:
        refs = butler.query_datasets(
            "template_coadd",
            collections=collection,
            where=f"band='{band}'",
            limit=None
        )
        for ref in refs:
            data_id = ref.dataId
            band = data_id["band"]
            tract = data_id["tract"]
            patch = data_id["patch"]
            patches_by_band[band].append({"tract": tract, "patch": patch})

    return patches_by_band


def get_skymap():
    """Load the lsst_cells_v2 skymap from the embargo Butler."""
    butler = dafButler.Butler("embargo")
    return butler.get("skyMap", skymap="lsst_cells_v2", collections="skymaps")


def get_patch_centers(skymap, patches_by_band):
    """Compute RA, Dec center for each patch in the results."""
    records = []
    for band, patches in patches_by_band.items():
        for entry in patches:
            tract_info = skymap[entry["tract"]]
            patch_info = tract_info[entry["patch"]]
            center = patch_info.getInnerSkyPolygon().getCentroid()
            point = SpherePoint(center)
            records.append({
                "band": band,
                "tract": entry["tract"],
                "patch": entry["patch"],
                "ra": point.getRa().asDegrees(),
                "dec": point.getDec().asDegrees(),
            })
    return records


def build_summary(records):
    """Compute per-band summary statistics."""
    summary = {}
    bands = sorted(set(r["band"] for r in records))
    for band in bands:
        band_records = [r for r in records if r["band"] == band]
        tracts = set(r["tract"] for r in band_records)
        summary[band] = {
            "n_patches": len(band_records),
            "n_tracts": len(tracts),
        }
    return summary


def main():
    print("Querying embargo Butler for template_coadd datasets...")
    patches_by_band = query_template_patches()

    total = sum(len(v) for v in patches_by_band.values())
    print(f"Found {total} patches across {len(patches_by_band)} bands")
    for band in sorted(patches_by_band.keys()):
        tracts = set(p["tract"] for p in patches_by_band[band])
        print(f"  {band}: {len(patches_by_band[band])} patches in {len(tracts)} tracts")

    print("Loading skymap...")
    skymap = get_skymap()

    print("Computing patch centers...")
    records = get_patch_centers(skymap, patches_by_band)

    summary = build_summary(records)

    output = {
        "summary": summary,
        "records": records,
    }

    outfile = "embargo_template_data.json"
    with open(outfile, "w") as f:
        json.dump(output, f)

    print(f"Wrote {len(records)} records to {outfile}")


if __name__ == "__main__":
    main()
