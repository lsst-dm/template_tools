#!/usr/bin/env python
"""Select tracts with enough nexp coverage that are visible from Rubin on a given night.

Reads ``output/tract_nexp_fractions.csv`` (written by ``healpix_to_tracts.py``),
keeps rows in the requested band whose ``frac_ge_<N>`` value is at least the
requested minimum, then computes how many hours each tract center is above a
minimum altitude between evening and morning 12-degree (nautical) twilight on
the requested night. Tracts visible for at least ``--min-hours`` are written to
a CSV.

The date is interpreted as the local date on which the night *starts*
(the ``day_obs`` convention): ``2026-12-16`` means the night of Dec 16/17.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_sun
from astropy.time import Time
from astropy.utils import iers

import common

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"

# Sun altitude defining the end/start of 12-degree (nautical) twilight.
TWILIGHT_SUN_ALTITUDE = -12.0
# Rubin is at ~ -70.7 deg longitude, so local solar noon is ~16:43 UTC.
# Starting the search window at 16:00 UTC keeps a full night inside it.
LOCAL_NOON_UTC_HOURS = 16.0

# Future dates lack final Earth-orientation data; the resulting sub-arcsecond
# errors are irrelevant for hours-of-visibility estimates.
iers.conf.iers_degraded_accuracy = "ignore"


def select_tracts(df, band, threshold, min_frac):
    """Return rows in ``band`` whose ``frac_ge_<threshold>`` >= ``min_frac``.

    Parameters
    ----------
    df : `pandas.DataFrame`
        Table with ``band``, ``tract``, and ``frac_ge_<N>`` columns.
    band : `str`
        Band to select.
    threshold : `int`
        The ``N`` in the ``frac_ge_N`` column to cut on.
    min_frac : `float`
        Minimum (inclusive) value of that column.

    Returns
    -------
    selected : `pandas.DataFrame`
        Filtered copy of the input, sorted by tract.
    """
    column = f"frac_ge_{threshold}"
    if column not in df.columns:
        available = ", ".join(c for c in df.columns if c.startswith("frac_ge_"))
        raise ValueError(f"Column {column} not in table; available: {available}")
    mask = (df["band"] == band) & (df[column] >= min_frac)
    return df.loc[mask].sort_values("tract").reset_index(drop=True)


def night_times(date, location, step_minutes=5.0, sun_altitude=TWILIGHT_SUN_ALTITUDE):
    """Return a grid of times during the night starting on ``date``.

    Parameters
    ----------
    date : `str`
        ISO date (``YYYY-MM-DD``) of the local evening on which the night begins.
    location : `astropy.coordinates.EarthLocation`
        Observer location.
    step_minutes : `float`, optional
        Grid spacing in minutes.
    sun_altitude : `float`, optional
        Sun altitude (degrees) below which it counts as night.

    Returns
    -------
    times : `astropy.time.Time`
        Times (UTC) between evening and morning twilight, spaced by
        ``step_minutes``.
    """
    start = Time(f"{date}T00:00:00", scale="utc") + LOCAL_NOON_UTC_HOURS*u.hour
    n_steps = int(round(24*60/step_minutes))
    grid = start + np.arange(n_steps)*step_minutes*u.min
    sun_alt = get_sun(grid).transform_to(AltAz(obstime=grid, location=location)).alt.deg
    dark = sun_alt < sun_altitude
    if not np.any(dark):
        raise RuntimeError(f"No dark time found on {date}")
    return grid[dark]


def visible_hours(ra, dec, times, location, min_altitude):
    """Return hours each (ra, dec) is above ``min_altitude`` during ``times``.

    Parameters
    ----------
    ra, dec : `numpy.ndarray`
        ICRS coordinates in degrees, shape ``(N,)``.
    times : `astropy.time.Time`
        Uniformly-spaced sample times, shape ``(T,)``, as from `night_times`.
    location : `astropy.coordinates.EarthLocation`
        Observer location.
    min_altitude : `float`
        Minimum altitude in degrees to count as visible.

    Returns
    -------
    hours : `numpy.ndarray`
        Hours above ``min_altitude``, shape ``(N,)``.
    """
    ra = np.atleast_1d(np.asarray(ra, dtype=float))
    dec = np.atleast_1d(np.asarray(dec, dtype=float))
    if len(times) < 2:
        step_hours = 0.0
    else:
        step_hours = (times[1] - times[0]).to_value("hour")
    coords = SkyCoord(ra=ra[:, np.newaxis]*u.deg, dec=dec[:, np.newaxis]*u.deg, frame="icrs")
    frame = AltAz(obstime=times[np.newaxis, :], location=location)
    alt = coords.transform_to(frame).alt.deg
    return np.sum(alt >= min_altitude, axis=1)*step_hours


def tract_centers(skymap, tract_ids):
    """Return (ra, dec) arrays in degrees for the centers of ``tract_ids``."""
    ra = np.empty(len(tract_ids))
    dec = np.empty(len(tract_ids))
    for i, tract_id in enumerate(tract_ids):
        center = skymap[int(tract_id)].getCtrCoord()
        ra[i] = center.getRa().asDegrees()
        dec[i] = center.getDec().asDegrees()
    return ra, dec


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("band", choices=common.BANDS, help="Band to select")
    parser.add_argument(
        "threshold", type=int, help="N in the frac_ge_N column to cut on (e.g. 3)"
    )
    parser.add_argument(
        "min_frac", type=float, help="Minimum value of frac_ge_N (inclusive)"
    )
    parser.add_argument("date", help="Night start date, ISO format (e.g. 2026-12-16)")
    parser.add_argument(
        "min_hours",
        type=float,
        help="Minimum hours above --min-altitude between 12-deg twilights",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=OUTPUT_DIR / "tract_nexp_fractions.csv",
        help="Input CSV from healpix_to_tracts.py",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV (default: output/selected_tracts_<band>_<date>.csv)",
    )
    parser.add_argument(
        "--min-altitude",
        type=float,
        default=30.0,
        help="Minimum altitude in degrees to count as visible (default 30, airmass 2)",
    )
    parser.add_argument(
        "--step-minutes",
        type=float,
        default=5.0,
        help="Time grid spacing for the visibility integration",
    )
    parser.add_argument(
        "--butler-repo",
        default="/repo/main",
        help="Butler repository holding the lsst_cells_v2 skymap",
    )
    args = parser.parse_args()

    if args.output is None:
        args.output = OUTPUT_DIR / f"selected_tracts_{args.band}_{args.date}.csv"

    df = pd.read_csv(args.input)
    selected = select_tracts(df, args.band, args.threshold, args.min_frac)
    print(
        f"{len(selected)} tracts in band {args.band} with "
        f"frac_ge_{args.threshold} >= {args.min_frac}"
    )
    if len(selected) == 0:
        print("Nothing to do.")
        return

    print("Loading skymap...")
    skymap = common.load_skymap(args.butler_repo)
    ra, dec = tract_centers(skymap, selected["tract"].to_numpy())
    selected = selected.assign(ra=ra, dec=dec)

    location = EarthLocation.of_site("Rubin Observatory")
    times = night_times(args.date, location, step_minutes=args.step_minutes)
    night_hours = len(times)*args.step_minutes/60.0
    print(
        f"Night of {args.date}: {times[0].iso} to {times[-1].iso} UTC "
        f"({night_hours:.1f} h below {TWILIGHT_SUN_ALTITUDE:g} deg)"
    )

    selected["visible_hours"] = visible_hours(ra, dec, times, location, args.min_altitude)
    visible = selected[selected["visible_hours"] >= args.min_hours]
    print(
        f"{len(visible)} tracts visible >= {args.min_hours} h "
        f"above {args.min_altitude:g} deg"
    )

    columns = ["tract", "band", "ra", "dec", f"frac_ge_{args.threshold}", "visible_hours"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    visible[columns].to_csv(args.output, index=False, float_format="%.4f")
    print(f"Wrote {args.output} ({len(visible)} rows)")


if __name__ == "__main__":
    main()
