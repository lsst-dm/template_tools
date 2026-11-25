import numpy as np
import pandas as pd
import pytest
from astropy import units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time

import select_visible_tracts as svt


def _make_df():
    return pd.DataFrame(
        {
            "band": ["g", "g", "g", "r"],
            "tract": [1, 2, 3, 1],
            "n_pixels": [10, 10, 10, 10],
            "frac_ge_1": [1.0, 1.0, 1.0, 1.0],
            "frac_ge_3": [0.9, 0.5, 0.49, 0.9],
        }
    )


def test_select_tracts_filters_on_band_and_threshold():
    df = _make_df()
    out = svt.select_tracts(df, band="g", threshold=3, min_frac=0.5)
    assert out["tract"].tolist() == [1, 2]
    assert set(out["band"]) == {"g"}


def test_select_tracts_unknown_threshold_raises():
    df = _make_df()
    with pytest.raises(ValueError, match="frac_ge_7"):
        svt.select_tracts(df, band="g", threshold=7, min_frac=0.5)


def test_night_times_are_dark_and_within_one_night():
    location = EarthLocation.of_site("Rubin Observatory")
    times = svt.night_times("2026-12-16", location, step_minutes=10.0)
    assert len(times) > 0
    # Southern summer night at ~ -30 deg latitude: roughly 7-8 hours of
    # darkness below -12 deg twilight.
    duration_hours = (times[-1] - times[0]).to_value("hour")
    assert 6.0 < duration_hours < 9.0
    # All samples should fall within the night starting on the given date.
    start = Time("2026-12-16T16:00:00")
    assert np.all(times >= start)
    assert np.all(times <= start + 1.0*u.day)


def test_visible_hours_near_sun_is_zero_and_anti_sun_is_full():
    location = EarthLocation.of_site("Rubin Observatory")
    step = 10.0
    times = svt.night_times("2026-12-16", location, step_minutes=step)
    night_length = len(times) * step / 60.0

    # Mid-December the Sun is at RA ~ 265 deg, Dec ~ -23 deg.
    # Anti-sun point at Dec -30 transits around midnight: visible most
    # of the night. A point near the Sun is never up in the dark.
    ra = np.array([85.0, 265.0])
    dec = np.array([-30.0, -23.0])
    hours = svt.visible_hours(ra, dec, times, location, min_altitude=30.0)

    assert hours[1] == 0.0
    assert hours[0] > 0.8 * night_length
    assert hours[0] <= night_length
