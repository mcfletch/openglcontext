"""Unit tests for the persistent per-path picking object-id map (headless).

The MRT pick path assigns each renderable path a stable object id stashed on the
path, so the {id: path} map is maintained incrementally instead of rebuilt every
warm frame (the O(N) build dominated pick cost on large scenes). These tests
exercise that allocation and its invalidation without a GL context.
"""
from OpenGLContext.passes._flat import FlatPass, SGObserver


class FakePath:
    """NodePath-like: attribute-settable, identity-distinct, has .broken."""
    def __init__(self, name):
        self.name = name
        self.broken = False
    def __repr__(self):
        return 'FakePath(%s)' % self.name


def _bare_pass():
    fp = FlatPass.__new__(FlatPass)
    fp._sel_id_map = None
    fp._sel_next = 1
    return fp


class TestObjectIdAllocation:
    def test_ids_are_stable_per_path(self):
        fp = _bare_pass()
        a, b = FakePath('a'), FakePath('b')
        ia, ib = fp._objectIdFor(a), fp._objectIdFor(b)
        assert ia != ib
        # Same path -> same id across repeated (per-frame) lookups.
        assert fp._objectIdFor(a) == ia
        assert fp._objectIdFor(b) == ib

    def test_map_resolves_id_back_to_path(self):
        fp = _bare_pass()
        a, b = FakePath('a'), FakePath('b')
        ia, ib = fp._objectIdFor(a), fp._objectIdFor(b)
        assert fp._sel_id_map[ia] is a
        assert fp._sel_id_map[ib] is b

    def test_zero_never_allocated(self):
        # 0 means "no object" in the id buffer, so ids start at 1.
        fp = _bare_pass()
        assert fp._objectIdFor(FakePath('a')) != 0
        assert 0 not in fp._sel_id_map

    def test_lookup_does_not_rebuild_map(self):
        # Re-looking-up an existing path must not grow the map (no per-frame
        # rebuild); only genuinely new paths add entries.
        fp = _bare_pass()
        a = FakePath('a')
        fp._objectIdFor(a)
        size = len(fp._sel_id_map)
        for _ in range(10):
            fp._objectIdFor(a)
        assert len(fp._sel_id_map) == size


class TestPurgePrunesIds:
    def test_removed_path_id_is_dropped(self):
        fp = _bare_pass()
        keep, gone = FakePath('keep'), FakePath('gone')
        ik, ig = fp._objectIdFor(keep), fp._objectIdFor(gone)

        # Wire up just enough SGObserver state for purge() to run.
        fp.paths = {'T': [keep, gone]}
        fp.nodePaths = {id(keep): [keep], id(gone): [gone]}
        gone.broken = True

        SGObserver.purge(fp)

        assert ig not in fp._sel_id_map, "stale id must not resolve after removal"
        assert fp._sel_id_map[ik] is keep, "surviving path keeps its id"
        assert gone not in fp.paths['T']
