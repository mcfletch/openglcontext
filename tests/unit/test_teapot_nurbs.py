"""Unit tests for the NURBS-tessellated Utah Teapot.

Covers the raw Bezier-patch data, the glut-matching orientation transform,
the Teapot node's render-path selection and lid toggle, and (when a GL
context is available) the GLU tessellation that turns the patches into vertex
arrays.
"""
import numpy as np
import pytest

from OpenGLContext.testing.glcontext import GLUnavailable, hidden_window

from OpenGLContext.scenegraph import teapot_nurbs_data as data
from OpenGLContext.scenegraph import teapot_nurbs
from OpenGLContext.scenegraph.teapot import Teapot


# -- data integrity (no GL context required) ---------------------------------

def test_control_point_count():
    """The Newell dataset defines 306 control points."""
    assert len(data.CONTROL_POINTS) == 306
    assert all(len(p) == 3 for p in data.CONTROL_POINTS)


def test_patch_counts_per_part():
    """Each teapot part has the expected number of 16-point Bezier patches."""
    expected = {'body': 12, 'handle': 4, 'spout': 4, 'lid': 8, 'bottom': 4}
    assert {k: len(v) for k, v in data.PATCH_GROUPS.items()} == expected
    assert sum(len(v) for v in data.PATCH_GROUPS.values()) == 32


def test_patch_indices_valid():
    """Every patch is 16 in-range control-point indices."""
    n = len(data.CONTROL_POINTS)
    for patches in data.PATCH_GROUPS.values():
        for patch in patches:
            assert len(patch) == 16
            assert all(0 <= i < n for i in patch)


def test_lid_excluded_from_base_order():
    """The lid is rendered separately so it can be toggled."""
    assert data.LID_PART == 'lid'
    assert 'lid' not in data.PART_ORDER
    assert set(data.PART_ORDER) == {'body', 'handle', 'spout', 'bottom'}


# -- injective texture layout (no GL context required) -----------------------

def _rects_from_transforms(transforms):
    """Recover each patch's atlas rectangle (u0, v0, u1, v1) from its affine."""
    rects = []
    for su, sv, ou, ov in transforms:
        rects.append((ou, ov, ou + su, ov + sv))
    return rects


def _overlap(a, b):
    """Area of intersection of two (u0, v0, u1, v1) rectangles."""
    du = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    dv = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return du * dv


def test_injective_transform_counts():
    """One exterior and one interior affine per base patch and per lid patch."""
    base_ext, base_int, lid_ext, lid_int = teapot_nurbs.injective_uv_transforms()
    n_base = sum(len(data.PATCH_GROUPS[p]) for p in data.PART_ORDER)
    assert len(base_ext) == len(base_int) == n_base == 24
    assert len(lid_ext) == len(lid_int) == len(data.PATCH_GROUPS['lid']) == 8


def test_injective_transforms_within_unit_square():
    """Every atlas rectangle stays inside [0, 1] x [0, 1]."""
    parts = teapot_nurbs.injective_uv_transforms()
    for transforms in parts:
        for u0, v0, u1, v1 in _rects_from_transforms(transforms):
            assert -1e-6 <= u0 < u1 <= 1 + 1e-6
            assert -1e-6 <= v0 < v1 <= 1 + 1e-6


def test_injective_layout_is_non_overlapping():
    """No two patch slots overlap: the whole teapot maps injectively.

    Exterior and interior faces, and every part, occupy disjoint atlas cells,
    so a texture is sampled without any patch fighting another for texels.
    """
    base_ext, base_int, lid_ext, lid_int = teapot_nurbs.injective_uv_transforms()
    rects = _rects_from_transforms(
        base_ext + base_int + lid_ext + lid_int
    )
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert _overlap(rects[i], rects[j]) < 1e-9, (i, j)


def test_injective_interior_and_exterior_are_separate():
    """Exterior body faces sit in the upper bottom-half band, interior below it."""
    base_ext, base_int, _, _ = teapot_nurbs.injective_uv_transforms()
    # Body is the first 12 base patches; exterior v in [0.25, 0.5], interior [0, 0.25].
    for _su, _sv, _ou, ov in base_ext[:12]:
        assert ov >= 0.25 - 1e-6
    for _su, sv, _ou, ov in base_int[:12]:
        assert ov + sv <= 0.25 + 1e-6


def test_orient_makes_teapot_y_up():
    """The orientation transform matches glutSolidTeapot(1.0) framing.

    The raw data is z-up; after transform the body's tallest control point
    (raw z near 3.15) maps to positive y, and the transform is a pure scale
    plus axis swap (no skew).
    """
    # Raw apex of the lid knob sits high in z; it should map to high +y.
    high_z = max(data.CONTROL_POINTS, key=lambda p: p[2])
    x, y, z = teapot_nurbs._orient(high_z)
    assert y > 0.5
    # A point on the +x body wall stays on +x, halved in scale.
    assert teapot_nurbs._orient((2.0, 0.0, 0.0)) == (1.0, -0.75, -0.0)


# -- Teapot node behaviour (no GL context required) --------------------------

def test_teapot_has_lid_field_default_true():
    t = Teapot()
    assert t.lid is True or t.lid == 1


def test_teapot_lid_toggle():
    t = Teapot(lid=False)
    assert not t.lid


def test_teapot_use_glut_field():
    assert Teapot().useGlut in (False, 0)
    assert Teapot(useGlut=True).useGlut


class _Mode:
    def __init__(self, shader_mode, matrix=None):
        self.shader_mode = shader_mode
        if matrix is not None:
            self.matrix = matrix


class TestTeapotLOD:
    """Distance-LOD: coarser GLU steps the further the camera. Level 0 keeps the pre-LOD default sampling."""

    def test_steps_decrease_with_level(self):
        steps = [teapot_nurbs.steps_for_level(l) for l in range(4)]
        assert steps == sorted(steps, reverse=True)
        assert steps[0] == 30.0            # level 0 == pre-LOD default

    def test_steps_clamp_past_last_level(self):
        assert teapot_nurbs.steps_for_level(99) == teapot_nurbs.steps_for_level(3)

    def test_near_teapot_is_level0(self):
        m = np.eye(4)
        m[3, 2] = -3.0      # ~1.5 radii away
        assert Teapot(size=1.0)._lod_level(_Mode(False, m)) == 0

    def test_far_teapot_is_coarser(self):
        near = np.eye(4)
        near[3, 2] = -3.0
        far = np.eye(4)
        far[3, 2] = -400.0
        t = Teapot(size=1.0)
        assert t._lod_level(_Mode(False, far)) > t._lod_level(_Mode(False, near))

    def test_size_normalizes_level(self, monkeypatch):
        # a big teapot and a small one at proportional distances get the same level
        m = np.eye(4)
        m[3, 2] = -40.0
        small = Teapot(size=1.0)._lod_level(_Mode(False, m))
        m2 = np.eye(4)
        m2[3, 2] = -400.0
        big = Teapot(size=10.0)._lod_level(_Mode(False, m2))
        assert small == big

    def test_lod_off_forces_level0(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_LOD', 'off')
        far = np.eye(4)
        far[3, 2] = -400.0
        assert Teapot(size=1.0)._lod_level(_Mode(False, far)) == 0


def _patch_render(monkeypatch, t, tessellate_ok=True):
    """Stub the render backends, recording which one draws.

    The static pre-generated fallback is gone: NURBS
    tessellation is the sole renderer, with GLUT only as an explicit/legacy
    last resort. ``_Mode`` carries no matrix, so the LOD level resolves to 0.
    """
    calls = []
    monkeypatch.setattr(type(t), '_ensure_tessellated',
                        classmethod(lambda cls, level=0: tessellate_ok))
    monkeypatch.setattr(t, '_render_legacy', lambda level: calls.append('legacy'))
    monkeypatch.setattr(t, '_render_shader', lambda mode, level: calls.append('shader'))
    monkeypatch.setattr(t, '_render_glut', lambda: calls.append('glut'))
    return calls


def test_render_uses_tessellated_mesh_legacy(monkeypatch):
    """The NURBS-tessellated mesh is the renderer (legacy path)."""
    t = Teapot()
    calls = _patch_render(monkeypatch, t)
    t.render(mode=_Mode(shader_mode=False))
    assert calls == ['legacy']


def test_render_uses_tessellated_mesh_shader(monkeypatch):
    """The NURBS-tessellated mesh is the renderer (shader path)."""
    t = Teapot()
    calls = _patch_render(monkeypatch, t)
    t.render(mode=_Mode(shader_mode=True))
    assert calls == ['shader']


def test_render_falls_back_to_glut_when_tessellation_unavailable(monkeypatch):
    """With no NURBS tessellation, GLUT is the last resort in legacy mode."""
    t = Teapot()
    calls = _patch_render(monkeypatch, t, tessellate_ok=False)
    monkeypatch.setattr('OpenGLContext.scenegraph.teapot.HAS_GLUT_TEAPOT', True)
    t.render(mode=_Mode(shader_mode=False))
    assert calls == ['glut']


def test_no_render_when_tessellation_unavailable_in_shader_mode(monkeypatch):
    """GLUT can't render in a core profile, so nothing draws if tessellation fails."""
    t = Teapot()
    calls = _patch_render(monkeypatch, t, tessellate_ok=False)
    monkeypatch.setattr('OpenGLContext.scenegraph.teapot.HAS_GLUT_TEAPOT', True)
    t.render(mode=_Mode(shader_mode=True))
    assert calls == []  # no usable backend


def test_use_glut_override(monkeypatch):
    """useGlut forces the GLUT path in legacy mode for comparison."""
    t = Teapot(useGlut=True)
    calls = _patch_render(monkeypatch, t)
    monkeypatch.setattr('OpenGLContext.scenegraph.teapot.HAS_GLUT_TEAPOT', True)
    t.render(mode=_Mode(shader_mode=False))
    assert calls == ['glut']


def test_bounding_volume_scales_with_size():
    from OpenGLContext.scenegraph import boundingvolume
    small = Teapot(size=1.0).boundingVolume(None)
    big = Teapot(size=2.0).boundingVolume(None)
    assert isinstance(small, boundingvolume.AABoundingBox)
    assert np.allclose(np.asarray(big.size), np.asarray(small.size) * 2.0)


# -- compute_tangents (pure CPU, T2F_N3F_V3F triangle soup) -------------------

def _tri(uvs, positions, normal=(0.0, 0.0, 1.0)):
    """One triangle interleaved as T2F_N3F_V3F (u,v, nx,ny,nz, x,y,z)."""
    rows = []
    for uv, pos in zip(uvs, positions, strict=True):
        rows.append([uv[0], uv[1], normal[0], normal[1], normal[2],
                     pos[0], pos[1], pos[2]])
    return np.array(rows, dtype=np.float32).reshape(-1)


def test_tangent_points_along_u_axis():
    # UV u grows with world +x, so the tangent must be +x, orthonormal, w=+1.
    interleaved = _tri(
        uvs=[(0, 0), (1, 0), (0, 1)],
        positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    tangents = teapot_nurbs.compute_tangents(interleaved)
    assert tangents.shape == (3, 4)
    assert np.allclose(tangents[:, 0:3], [1.0, 0.0, 0.0], atol=1e-6)
    assert np.allclose(tangents[:, 3], 1.0)


def test_tangent_is_orthogonal_to_normal():
    # A slanted UV mapping still yields a tangent perpendicular to the normal.
    interleaved = _tri(
        uvs=[(0, 0), (1, 0.5), (0.2, 1)],
        positions=[(0, 0, 0), (2, 0, 0), (0, 3, 0)])
    tangents = teapot_nurbs.compute_tangents(interleaved)
    normals = interleaved.reshape(-1, teapot_nurbs.FLOATS_PER_VERTEX)[:, 2:5]
    dots = np.sum(tangents[:, 0:3] * normals, axis=1)
    assert np.allclose(dots, 0.0, atol=1e-6)
    lengths = np.linalg.norm(tangents[:, 0:3], axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-6)   # unit tangent


def test_degenerate_uv_yields_zero_tangent():
    # All three vertices share one UV -> zero UV area -> no defined tangent.
    interleaved = _tri(
        uvs=[(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)],
        positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    tangents = teapot_nurbs.compute_tangents(interleaved)
    assert np.allclose(tangents[:, 0:3], 0.0)
    assert np.allclose(tangents[:, 3], 1.0)


def test_empty_input_returns_empty_tangents():
    tangents = teapot_nurbs.compute_tangents(np.zeros(0, dtype=np.float32))
    assert tangents.shape == (0, 4)


# -- GL tessellation (requires a GL context) ---------------------------------

@pytest.fixture(scope='module')
def gl_context():
    """One window for the whole module, with no alpha in what is read back."""
    try:
        with hidden_window('teapot-test', profile='any',
                           hints={'ALPHA_BITS': 0}) as window:
            yield window
    except GLUnavailable as err:
        pytest.skip(str(err))


@pytest.mark.core_profile
def test_tessellation_produces_arrays(gl_context):
    base, lid = teapot_nurbs.tessellate_teapot()
    assert base.dtype == np.float32
    assert len(base) % teapot_nurbs.FLOATS_PER_VERTEX == 0
    assert len(lid) % teapot_nurbs.FLOATS_PER_VERTEX == 0
    # Triangle vertices, so vertex count is a multiple of three.
    assert (len(base) // teapot_nurbs.FLOATS_PER_VERTEX) % 3 == 0
    assert len(base) > 0 and len(lid) > 0


@pytest.mark.core_profile
def test_tessellation_normals_are_unit(gl_context):
    base, _ = teapot_nurbs.tessellate_teapot()
    verts = base.reshape(-1, teapot_nurbs.FLOATS_PER_VERTEX)
    normals = verts[:, 2:5]  # T2F_N3F_V3F: normal is floats 2..5
    lengths = np.linalg.norm(normals, axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-3)


@pytest.mark.core_profile
def test_tessellation_normals_point_outward(gl_context):
    """Body normals face away from the central (y) axis.

    Regression guard for the Newell patch ordering, which is left-handed and
    yields inward normals unless the control grid is transposed.  Tested on
    the rotationally-symmetric parts (body, lid, bottom); the handle and spout
    are tubes whose normals are not radial.
    """
    data_mod = pytest.importorskip(
        'OpenGLContext.scenegraph.teapot_nurbs_data'
    )
    patches = []
    for part in ('body', 'lid', 'bottom'):
        patches.extend(data_mod.PATCH_GROUPS[part])
    v = teapot_nurbs.tessellate_patches(patches).reshape(
        -1, teapot_nurbs.FLOATS_PER_VERTEX
    )
    normals, pos = v[:, 2:5], v[:, 5:8]  # T2F_N3F_V3F
    # Radial direction in the xz-plane (outward from the vertical axis).
    radial = pos.copy()
    radial[:, 1] = 0.0
    r = np.linalg.norm(radial, axis=1)
    mask = r > 0.3  # ignore points near the axis (poles/knob)
    radial = radial[mask] / r[mask, None]
    outwardness = np.sum(normals[mask] * radial, axis=1)
    assert np.mean(outwardness > 0) > 0.85


@pytest.mark.core_profile
def test_tessellation_oriented_y_up(gl_context):
    """Tessellated geometry is y-up and roughly glut-teapot sized."""
    base, lid = teapot_nurbs.tessellate_teapot()
    pos = base.reshape(-1, teapot_nurbs.FLOATS_PER_VERTEX)[:, 5:8]  # T2F_N3F_V3F
    # Body sits around the origin, wider than tall, depth along z.
    assert pos[:, 0].min() < -1.0  # handle side
    assert pos[:, 0].max() > 1.0   # spout side
    # Lid adds height above the body.
    lid_pos = lid.reshape(-1, teapot_nurbs.FLOATS_PER_VERTEX)[:, 5:8]
    assert lid_pos[:, 1].max() > pos[:, 1].max() - 1e-3


@pytest.mark.core_profile
def test_tessellation_emits_texcoords_in_unit_square(gl_context):
    """Every vertex carries a (u, v) inside the injective atlas [0, 1]^2."""
    base, lid = teapot_nurbs.tessellate_teapot()
    for arr in (base, lid):
        uv = arr.reshape(-1, teapot_nurbs.FLOATS_PER_VERTEX)[:, 0:2]
        assert uv.min() >= -1e-4
        assert uv.max() <= 1 + 1e-4
    # The lid occupies only the knob+lid columns of the top half.
    lid_uv = lid.reshape(-1, teapot_nurbs.FLOATS_PER_VERTEX)[:, 0:2]
    assert lid_uv[:, 0].min() >= 0.25 - 1e-4  # knob column starts at u=0.25
    assert lid_uv[:, 0].max() <= 0.75 + 1e-4  # lid column ends at u=0.75
    assert lid_uv[:, 1].min() >= 0.5 - 1e-4   # top half only


@pytest.mark.core_profile
def test_interior_faces_double_geometry_and_flip_normals(gl_context):
    """With interior on, each patch also emits a reversed, negated-normal copy."""
    base_solid, _ = teapot_nurbs.tessellate_teapot(interior=False)
    base_both, _ = teapot_nurbs.tessellate_teapot(interior=True)
    fpv = teapot_nurbs.FLOATS_PER_VERTEX
    assert len(base_both) // fpv == 2 * (len(base_solid) // fpv)
    # A single patch emits exterior faces then its negated-normal interior copy,
    # so within one patch the two halves' mean normals are opposites.
    patch = data.PATCH_GROUPS['body'][0]
    arr = teapot_nurbs.tessellate_patches(
        [patch], ext_transforms=[(1, 1, 0, 0)], int_transforms=[(1, 1, 0, 0)],
    ).reshape(-1, fpv)
    m = len(arr) // 2
    ext_n, int_n = arr[:m, 2:5], arr[m:, 2:5]
    assert np.allclose(ext_n.mean(0), -int_n.mean(0), atol=1e-4)


@pytest.mark.core_profile
def test_interior_faces_use_interior_atlas_region(gl_context):
    """A body patch's exterior faces land in v>=0.25, its interior copy in v<=0.25."""
    base_ext, base_int, _, _ = teapot_nurbs.injective_uv_transforms()
    patch = data.PATCH_GROUPS['body'][0]
    fpv = teapot_nurbs.FLOATS_PER_VERTEX
    arr = teapot_nurbs.tessellate_patches(
        [patch], ext_transforms=[base_ext[0]], int_transforms=[base_int[0]],
    ).reshape(-1, fpv)
    m = len(arr) // 2
    assert arr[:m, 1].min() >= 0.25 - 1e-4   # exterior in v[0.25, 0.5]
    assert arr[m:, 1].max() <= 0.25 + 1e-4   # interior in v[0, 0.25]
