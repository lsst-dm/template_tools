import pandas as pd
import pytest

import get_visits_for_tracts as gv


def _write(tmp_path, rows):
    path = tmp_path / "tracts.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_read_tract_list_takes_band_from_csv(tmp_path):
    path = _write(tmp_path, {"tract": [3, 1, 1], "band": ["i", "i", "i"]})
    tracts, band = gv.read_tract_list(path)
    assert tracts == [1, 3]
    assert band == "i"


def test_read_tract_list_explicit_band_overrides(tmp_path):
    path = _write(tmp_path, {"tract": [5], "band": ["i"]})
    assert gv.read_tract_list(path, band="z") == ([5], "z")


def test_read_tract_list_requires_band_when_ambiguous(tmp_path):
    path = _write(tmp_path, {"tract": [1, 2], "band": ["i", "z"]})
    with pytest.raises(ValueError, match="multiple bands"):
        gv.read_tract_list(path)
    assert gv.read_tract_list(path, band="i")[0] == [1, 2]


def test_read_tract_list_requires_tract_column(tmp_path):
    path = _write(tmp_path, {"id": [1]})
    with pytest.raises(ValueError, match="'tract'"):
        gv.read_tract_list(path)
