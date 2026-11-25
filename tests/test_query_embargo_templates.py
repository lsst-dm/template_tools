
from lsst.geom import SpherePoint, degrees

import query_embargo_templates as qet

class _FakePolygon:
    def __init__(self, vertices):
        self._vertices = vertices

    def getVertices(self):
        return self._vertices

class _FakeTract:
    def __init__(self, n_patches=(10, 10)):
        verts = [
            SpherePoint(ra*degrees, dec*degrees).getVector()
            for ra, dec in [(10.0, -5.0), (11.0, -5.0), (11.0, -4.0), (10.0, -4.0)]
        ]
        self._polygon = _FakePolygon(verts)
        self._n_patches = n_patches

    def getInnerSkyPolygon(self):
        return self._polygon

    def getNumPatches(self):
        return self._n_patches

class _FakeSkymap(dict):
    pass

def test_get_tract_corners_records_patch_counts():
    skymap = _FakeSkymap({1: _FakeTract(), 2: _FakeTract((5, 4))})
    patches_by_band = {
        "g": [{"tract": 1, "patch": p} for p in range(100)] + [{"tract": 2, "patch": 0}],
        "r": [{"tract": 2, "patch": 3}, {"tract": 2, "patch": 7}],
    }

    records = qet.get_tract_corners(skymap, patches_by_band)

    by_key = {(r["band"], r["tract"]): r for r in records}
    assert set(by_key) == {("g", 1), ("g", 2), ("r", 2)}
    assert by_key[("g", 1)]["n_patches"] == 100
    assert by_key[("g", 1)]["n_patches_total"] == 100
    assert by_key[("g", 2)]["n_patches"] == 1
    assert by_key[("g", 2)]["n_patches_total"] == 20
    assert by_key[("r", 2)]["n_patches"] == 2
    assert len(by_key[("g", 1)]["corners"]) == 4
    assert set(by_key[("g", 1)]["corners"][0]) == {"ra", "dec"}

def test_get_tract_corners_sorted_by_tract_within_band():
    skymap = _FakeSkymap({5: _FakeTract(), 3: _FakeTract()})
    patches_by_band = {"i": [{"tract": 5, "patch": 0}, {"tract": 3, "patch": 0}]}

    records = qet.get_tract_corners(skymap, patches_by_band)

    assert [r["tract"] for r in records] == [3, 5]
