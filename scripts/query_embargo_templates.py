"""
Query the embargo Butler for deployed template_coadd datasets in
LSSTCam/templates and produce a JSON data file with tract corner
coordinates for the embargo templates dashboard, plus per-band
HEALPix fractional coverage maps.
"""

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

import healpy as hp
import hpgeom as hpg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits

import lsst.daf.butler as dafButler
from lsst.geom import SpherePoint

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


def get_patch_polygons(skymap, patches_by_band):
    """Get RA/Dec polygon vertices for each patch from the skymap."""
    polygons_by_band = defaultdict(list)
    for band, patches in patches_by_band.items():
        for p in patches:
            tract_info = skymap[p["tract"]]
            patch_info = tract_info[p["patch"]]
            vertices = patch_info.inner_sky_polygon.getVertices()
            ra = []
            dec = []
            for v in vertices:
                point = SpherePoint(v)
                ra.append(point.getRa().asDegrees())
                dec.append(point.getDec().asDegrees())
            polygons_by_band[band].append((np.array(ra), np.array(dec)))
    return polygons_by_band


def build_healpix_coverage(patch_polygons_by_band, nside=64):
    """Build per-band HEALPix coverage maps with fractional pixel coverage.

    Uses sub-pixel sampling at 4x the target NSIDE to estimate the fraction
    of each target pixel covered by one or more template patches.
    """
    npix = hpg.nside_to_npixel(nside)
    nside_hi = nside * 4
    n_subpix_per_pix = (nside_hi // nside) ** 2
    order_diff = hpg.nside_to_order(nside_hi) - hpg.nside_to_order(nside)
    bit_shift = 2 * order_diff

    coverage_maps = {}
    for band, polygons in patch_polygons_by_band.items():
        covered_subpix = set()
        for ra, dec in polygons:
            subpixels = hpg.query_polygon(
                nside_hi, ra, dec, inclusive=False, nest=True
            )
            covered_subpix.update(subpixels)

        coverage = np.zeros(npix, dtype=np.float64)
        if covered_subpix:
            subpix_arr = np.array(list(covered_subpix), dtype=np.int64)
            parent_pix = subpix_arr >> bit_shift
            unique, counts = np.unique(parent_pix, return_counts=True)
            coverage[unique] = counts / n_subpix_per_pix

        coverage_maps[band] = coverage

    return coverage_maps


def write_healpix_fits(coverage_map, nside, band, filename):
    """Write a HEALPix coverage map to a standard FITS binary table."""
    col = fits.Column(name="COVERAGE", format="E", array=coverage_map)
    hdu = fits.BinTableHDU.from_columns([col])
    hdu.header["PIXTYPE"] = "HEALPIX"
    hdu.header["ORDERING"] = "NESTED"
    hdu.header["NSIDE"] = nside
    hdu.header["COORDSYS"] = "C"
    hdu.header["BAND"] = band
    hdu.writeto(filename, overwrite=True)


# https://rtn-045.lsst.io/#colorblind-friendly-plots
BAND_COLORS = {'u': '#1600ea', 'g': '#31de1f', 'r': '#b52626', 'i': '#370201', 'z': '#ba52ff', 'y': '#61a2b3'}


def make_band_cmap(band):
    """Create a colormap that goes from black to the band's color."""
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list(
        f"cmap_{band}", ["#FFFFFF", BAND_COLORS[band]]
    )


def _overplot_plane(lon_array, lat_array, coord_from, color, label):
    """Overplot a great circle (e.g. galactic or ecliptic plane) on a mollview."""
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    if coord_from == "galactic":
        sc = SkyCoord(l=lon_array * u.deg, b=lat_array * u.deg, frame="galactic")
        ra = sc.icrs.ra.deg
        dec = sc.icrs.dec.deg
    elif coord_from == "ecliptic":
        sc = SkyCoord(
            lon=lon_array * u.deg, lat=lat_array * u.deg,
            frame="geocentricmeanecliptic",
        )
        ra = sc.icrs.ra.deg
        dec = sc.icrs.dec.deg
    else:
        ra, dec = lon_array, lat_array
    hp.projplot(ra, dec, lonlat=True, coord="C", color=color,
                linewidth=0.8, alpha=0.7, linestyle="--")
    mid = len(ra) // 4
    hp.projtext(ra[mid], dec[mid], f" {label}", lonlat=True, coord="C",
                fontsize=7, color=color, ha="left", va="bottom")


def write_healpix_png(coverage_map, nside, band, filename):
    """Render a HEALPix coverage map as a Mollweide projection PNG."""
    cmap = make_band_cmap(band)
    hp.mollview(
        coverage_map,
        nest=True,
        coord=["C"],
        cmap=cmap,
        min=0,
        max=1,
        title=f"Template Coverage — {band} band (NSIDE={nside})",
        unit="Fractional coverage",
        bgcolor="white",
    )
    hp.graticule(dpar=30, dmer=30, coord="C", color="gray", alpha=0.5)
    for dec in [-60, -30, 0, 30, 60]:
        hp.projtext(
            180, dec, f"{dec:+d}°",
            lonlat=True, coord="C", fontsize=8, color="gray",
            ha="right", va="bottom",
        )
    for ra in [0, 60, 120, 180, 240, 300]:
        hp.projtext(
            ra, -2, f"{ra}°",
            lonlat=True, coord="C", fontsize=8, color="gray",
            ha="center", va="top",
        )
    gal_lon = np.linspace(0, 360, 500)
    gal_lat = np.zeros_like(gal_lon)
    _overplot_plane(gal_lon, gal_lat, "galactic", "gray", "Galactic")

    ecl_lon = np.linspace(0, 360, 500)
    ecl_lat = np.zeros_like(ecl_lon)
    _overplot_plane(ecl_lon, ecl_lat, "ecliptic", "gray", "Ecliptic")

    plt.savefig(filename, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate template coverage data and HEALPix maps."
    )
    parser.add_argument(
        "--nside", type=int, default=64,
        help="HEALPix NSIDE for coverage maps (default: 64)",
    )
    args = parser.parse_args()

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

    print(f"Computing HEALPix coverage maps (NSIDE={args.nside})...")
    patch_polygons = get_patch_polygons(skymap, patches_by_band)
    coverage_maps = build_healpix_coverage(patch_polygons, nside=args.nside)

    for band, cov_map in coverage_maps.items():
        fits_fname = f"template_coverage_healpix_{band}_nside{args.nside}.fits"
        png_fname = f"template_coverage_healpix_{band}_nside{args.nside}.png"
        write_healpix_fits(cov_map, args.nside, band, fits_fname)
        write_healpix_png(cov_map, args.nside, band, png_fname)
        n_covered = np.count_nonzero(cov_map)
        area = n_covered * hpg.nside_to_pixel_area(args.nside, degrees=True)
        print(f"  {band}: {fits_fname}, {png_fname} ({n_covered} pixels, ~{area:.1f} deg²)")

    print("Done.")


if __name__ == "__main__":
    main()
