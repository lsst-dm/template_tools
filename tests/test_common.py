import numpy as np
import pytest

import common
from lsst.geom import SpherePoint, degrees


def test_compute_tract_fractions_basic():
    tract_ids = np.array([10, 10, 10, 20, 20])
    values = np.array([1, 3, 5, 2, 8])
    thresholds = [1, 2, 5]

    records = common.compute_tract_fractions(tract_ids, values, thresholds)

    assert [r["tract"] for r in records] == [10, 20]
    assert all(isinstance(r["tract"], int) for r in records)

    t10, t20 = records
    assert t10["n_pixels"] == 3 and isinstance(t10["n_pixels"], int)
    assert t10["fractions"][1] == pytest.approx(1.0)
    assert t10["fractions"][2] == pytest.approx(2 / 3)
    assert t10["fractions"][5] == pytest.approx(1 / 3)
    assert all(isinstance(v, float) for v in t10["fractions"].values())

    assert t20["n_pixels"] == 2
    assert t20["fractions"][1] == pytest.approx(1.0)
    assert t20["fractions"][2] == pytest.approx(1.0)
    assert t20["fractions"][5] == pytest.approx(0.5)


class _FakePolygon:
    def __init__(self, vertices):
        self._vertices = vertices

    def getVertices(self):
        return self._vertices


class _FakeTract:
    def __init__(self, vertices):
        self._polygon = _FakePolygon(vertices)

    def getInnerSkyPolygon(self):
        return self._polygon


def _unit_vector(ra_deg, dec_deg):
    return SpherePoint(ra_deg * degrees, dec_deg * degrees).getVector()


def test_tract_corners_rounds_by_default():
    verts = [_unit_vector(10.123456, -5.654321), _unit_vector(11.0, -6.0)]
    tract = _FakeTract(verts)

    corners = common.tract_corners(tract)

    assert corners == [[10.123, -5.654], [11.0, -6.0]]


def test_tract_corners_no_rounding_when_ndigits_none():
    verts = [_unit_vector(10.123456, -5.654321)]
    tract = _FakeTract(verts)

    corners = common.tract_corners(tract, ndigits=None)

    ra, dec = corners[0]
    assert ra == pytest.approx(10.123456, abs=1e-6)
    assert dec == pytest.approx(-5.654321, abs=1e-6)
