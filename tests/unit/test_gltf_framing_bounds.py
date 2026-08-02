"""Where a model ends, for the purpose of pointing a camera at it
(:func:`OpenGLContext.loaders.gltf.transforms.framing_bounds`).

An exported model often carries a part or two stranded far outside itself, at a
scale or a place nothing else in the file agrees with. Framing the union of
everything then stands the camera hundreds of model-widths back and the model
is a speck. These check that the stranded parts are left out of the fit, that a
model which merely thins out towards its edges is framed whole, and that a
scene which genuinely is two things far apart is not cut in half.

Pure numpy, no GL and no file.
"""
import numpy as np
import pytest

from OpenGLContext.loaders.gltf.transforms import (
    STRAY_GAP, STRAY_RATIO, framing_bounds,
)


def _part(centre, size=1.0, weight=100):
    """One drawn primitive's world box and vertex count."""
    c = np.asarray(centre, dtype='d')
    return (c - size / 2.0, c + size / 2.0, weight)


def _radius(bounds):
    return float(np.linalg.norm(bounds.maximum - bounds.minimum) / 2.0)


class TestOrdinaryModels:
    def test_nothing_to_frame(self):
        assert framing_bounds([]) is None

    def test_one_part_is_the_whole_model(self):
        bounds = framing_bounds([_part((5, 0, 0), size=2.0)])
        assert np.allclose(bounds.minimum, (4, -1, -1))
        assert np.allclose(bounds.maximum, (6, 1, 1))
        assert bounds.strays == 0

    def test_a_crowd_is_framed_whole(self):
        """Nothing is left out of a model whose parts sit together."""
        parts = [_part((x, 0, 0)) for x in range(-5, 6)]
        bounds = framing_bounds(parts)
        assert np.allclose(bounds.minimum, (-5.5, -0.5, -0.5))
        assert np.allclose(bounds.maximum, (5.5, 0.5, 0.5))
        assert bounds.strays == 0

    def test_a_model_that_thins_out_is_framed_whole(self):
        """Sparse outskirts are still the model, so long as there is no gap.

        Each part is further out than the last but never by ``STRAY_GAP``, so
        the shells are occupied all the way to the edge and the fit keeps them
        even though the far end is many times ``STRAY_RATIO`` out.
        """
        reach, parts = 1.0, [_part((0, 0, 0))]
        for _ in range(11):
            reach *= STRAY_GAP * 0.75
            parts.append(_part((reach, 0, 0), weight=1))
        assert reach > STRAY_RATIO * 4        # the ratio test has to have fired
        bounds = framing_bounds(parts)
        assert bounds.strays == 0
        assert _radius(bounds) > reach / 2.0

    def test_a_dense_detail_does_not_shrink_the_fit(self):
        """Most of a model's *vertices* can be in a small part of it.

        A hub carrying a thousand times the vertex count of the body around it
        must not become the thing framed. Counting vertices alone it is
        ``STRAY_CROWD`` of the model on its own; the median part is what says
        the model is really the size of the body.
        """
        parts = [_part((0, 0, 0), size=0.2, weight=50000)]
        parts += [_part((x, 0, 0), size=1.0, weight=8) for x in (-3, -1, 1, 3)]
        bounds = framing_bounds(parts)
        assert bounds.strays == 0
        assert np.allclose(bounds.minimum, (-3.5, -0.5, -0.5))


class TestStrandedParts:
    def test_a_stranded_part_is_left_out(self):
        parts = [_part((x, 0, 0)) for x in range(-5, 6)]
        parts.append(_part((900, 0, 0), weight=20))
        bounds = framing_bounds(parts)
        assert bounds.strays == 1
        assert np.allclose(bounds.minimum, (-5.5, -0.5, -0.5))
        assert np.allclose(bounds.maximum, (5.5, 0.5, 0.5))

    def test_the_reach_says_how_far_the_strays_go(self):
        """In radii of the box that is framed, which is what makes it tell a
        user why the model would otherwise have been invisible."""
        parts = [_part((x, 0, 0)) for x in range(-5, 6)]
        parts.append(_part((900, 0, 0), weight=20))
        bounds = framing_bounds(parts)
        assert bounds.reach == pytest.approx(900.5 / _radius(bounds), rel=0.01)

    def test_several_strands_go_together(self):
        """Everything past the first empty shell is a stray, near ones too."""
        parts = [_part((x, 0, 0)) for x in np.linspace(-5, 5, 31)]
        parts += [_part((d, 0, 0), weight=20) for d in (40, 300, 900)]
        assert framing_bounds(parts).strays == 3

    def test_the_model_keeps_the_strays_weight_out_of_the_crowd(self):
        """A stray with a lot of geometry in it is still a stray, so long as
        the crowd keeps ``STRAY_CROWD`` of the model to itself."""
        parts = [_part((x, 0, 0), weight=1000) for x in range(-5, 6)]
        parts.append(_part((900, 0, 0), weight=900))
        assert framing_bounds(parts).strays == 1

    def test_the_far_cluster_can_be_where_the_model_is(self):
        """Nearly all the geometry, out beyond a scattering of small parts.

        That is a scene whose model stands away from some props, not a model
        with strays: counting parts alone would frame the props and leave the
        model itself out of the shot, which is what ``STRAY_CROWD`` prevents.
        """
        parts = [_part((x, 0, 0), weight=1) for x in range(-3, 4)]
        parts += [_part((900 + x, 0, 0), weight=5000) for x in range(-2, 3)]
        bounds = framing_bounds(parts)
        assert bounds.strays == 0
        assert bounds.maximum[0] == pytest.approx(902.5)

    def test_two_halves_far_apart_are_both_framed(self):
        """A scene that genuinely is two things is not a model with a stray.

        Half the geometry is out at the far cluster, so no ``STRAY_CROWD`` of
        the model sits close enough together for the ratio test to fire.
        """
        parts = [_part((x, 0, 0)) for x in range(-5, 6)]
        parts += [_part((900 + x, 0, 0)) for x in range(-5, 6)]
        bounds = framing_bounds(parts)
        assert bounds.strays == 0
        assert np.allclose(bounds.maximum, (905.5, 0.5, 0.5))

    def test_a_part_just_inside_the_ratio_is_kept(self):
        """The rejection only starts once the model is mostly somewhere else."""
        parts = [_part((x, 0, 0), size=0.1) for x in np.linspace(-1, 1, 21)]
        parts.append(_part((STRAY_RATIO * 0.7, 0, 0), size=0.1, weight=1))
        assert framing_bounds(parts).strays == 0

    def test_the_gap_is_measured_against_everything_kept(self):
        """A stray twice as far as the crowd, but reached by a stepping stone
        between the two, is inside the model: the shell it would have to jump
        is not empty."""
        parts = [_part((x, 0, 0)) for x in range(-5, 6)]
        parts.append(_part((900, 0, 0), weight=20))
        with_stone = parts + [_part((d, 0, 0), weight=20)
                              for d in (9, 17, 32, 60, 113, 212, 397, 745)]
        assert framing_bounds(parts).strays == 1
        assert framing_bounds(with_stone).strays == 0


class TestLoadedScene:
    """The loader frames what it built, and says what it left out."""

    def test_a_stranded_node_does_not_blow_the_framing_up(self):
        pygltflib = pytest.importorskip("pygltflib")
        from OpenGLContext.loaders import gltf

        pos = np.array([[-1, -1, 0], [1, -1, 0], [0, 1, 0]], dtype=np.float32)
        blob = pos.tobytes()
        # A crowd of parts at the origin, and one the file left 800 out.
        nodes = [pygltflib.Node(mesh=0, translation=[float(x), 0.0, 0.0])
                 for x in range(-10, 11)]
        nodes.append(pygltflib.Node(mesh=0, translation=[0.0, 0.0, -800.0]))
        g = pygltflib.GLTF2()
        g.scene = 0
        g.scenes = [pygltflib.Scene(nodes=list(range(len(nodes))))]
        g.nodes = nodes
        g.meshes = [pygltflib.Mesh(primitives=[pygltflib.Primitive(
            attributes=pygltflib.Attributes(POSITION=0))])]
        g.accessors = [pygltflib.Accessor(
            bufferView=0, componentType=5126, count=3, type='VEC3',
            max=pos.max(0).tolist(), min=pos.min(0).tolist())]
        g.bufferViews = [pygltflib.BufferView(
            buffer=0, byteOffset=0, byteLength=pos.nbytes)]
        g.buffers = [pygltflib.Buffer(byteLength=len(blob))]
        g.set_binary_blob(blob)

        scene = gltf.load_gltf(b"".join(g.save_to_bytes()))
        assert scene.radius < 12.0                  # not the 400 of the union
        assert scene.center == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
        assert scene.strays == 1
        assert scene.stray_reach > 50

    def test_an_ordinary_scene_reports_no_strays(self):
        pytest.importorskip("pygltflib")
        from OpenGLContext.loaders import gltf
        from tests.unit.test_gltf_loader import _triangle_glb

        scene = gltf.load_gltf(_triangle_glb())
        assert scene.strays == 0
        assert scene.radius > 0
