"""
Query the embargo Butler for deployed template_coadd datasets in
LSSTCam/templates and produce a JSON data file with tract corner
coordinates for the embargo templates dashboard.
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timezone

import lsst.daf.butler as dafButler
from lsst.geom import SpherePoint

import numpy as np

STERADIANS_TO_SQDEG = (180.0 / math.pi) ** 2


def spherical_polygon_area(vertices):
    """Compute area of a convex spherical polygon in steradians.

    Parameters
    ----------
    vertices : list of UnitVector3d
    """
    v = [np.array(vert) for vert in vertices]
    n = len(v)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(1, n - 1):
        a = v[0]
        b = v[i]
        c = v[i + 1]
        cross = np.cross(b, c)
        dot = np.dot(a, cross)
        denom = 1.0 + np.dot(a, b) + np.dot(a, c) + np.dot(b, c)
        area += 2.0 * math.atan2(dot, denom)
    return abs(area)


def query_template_patches(repo="embargo", collection="LSSTCam/templates"):
    """Query Butler for all template_coadd data IDs."""
    butler = dafButler.Butler(repo)

    patches_by_band = defaultdict(list)
    for band in ['u', 'g', 'r', 'i', 'z', 'y']:
        refs = butler.query_datasets(
            "template_coadd",
            collections=collection,
            where=f"band='{band}'",
            limit=None
        )
        for ref in refs:
            data_id = ref.dataId
            patches_by_band[data_id["band"]].append({
                "tract": data_id["tract"],
                "patch": data_id["patch"],
            })

    return patches_by_band


def get_skymap():
    """Load the lsst_cells_v2 skymap from the embargo Butler."""
    butler = dafButler.Butler("embargo")
    return butler.get("skyMap", skymap="lsst_cells_v2", collections="skymaps")


def get_tract_corners(skymap, tracts_by_band):
    """Compute RA, Dec corners for each tract that has any patch coverage."""
    records = []
    for band, tract_ids in tracts_by_band.items():
        for tract_id in sorted(tract_ids):
            tract_info = skymap[tract_id]
            vertices = tract_info.getInnerSkyPolygon().getVertices()
            corners = []
            for v in vertices:
                point = SpherePoint(v)
                corners.append({
                    "ra": point.getRa().asDegrees(),
                    "dec": point.getDec().asDegrees(),
                })
            records.append({
                "band": band,
                "tract": tract_id,
                "corners": corners,
            })
    return records


def build_summary(skymap, patches_by_band, tracts_by_band):
    """Compute per-band summary statistics including area."""
    summary = {}
    for band in sorted(patches_by_band.keys()):
        area_sr = sum(
            spherical_polygon_area(
                skymap[t].getInnerSkyPolygon().getVertices()
            )
            for t in tracts_by_band[band]
        )
        summary[band] = {
            "n_patches": len(patches_by_band[band]),
            "n_tracts": len(tracts_by_band[band]),
            "area_sqdeg": round(area_sr * STERADIANS_TO_SQDEG, 1),
        }
    return summary


def main():
    print("Querying embargo Butler for template_coadd datasets...")
    patches_by_band = query_template_patches()

    total = sum(len(v) for v in patches_by_band.values())
    print(f"Found {total} patches across {len(patches_by_band)} bands")

    tracts_by_band = {}
    for band in sorted(patches_by_band.keys()):
        tracts = set(p["tract"] for p in patches_by_band[band])
        tracts_by_band[band] = tracts
        print(f"  {band}: {len(patches_by_band[band])} patches in {len(tracts)} tracts")

    print("Loading skymap...")
    skymap = get_skymap()

    print("Computing tract corners...")
    records = get_tract_corners(skymap, tracts_by_band)

    summary = build_summary(skymap, patches_by_band, tracts_by_band)

    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "summary": summary,
        "records": records,
    }

    outfile = "deployed_template_data.json"
    with open(outfile, "w") as f:
        json.dump(output, f)

    n_tracts = sum(len(t) for t in tracts_by_band.values())
    print(f"Wrote {n_tracts} tract records to {outfile}")


if __name__ == "__main__":
    main()
