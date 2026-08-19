"""The models a package ships: finding them, loading them, and repainting them.

:class:`~OpenGLContext.loaders.assets.AssetLibrary` is a directory of models
addressed by relative name, so a table of art is a table of filenames and never
a path built at each call site. Loading is forgiving: a file that will not load
leaves the caller without a model rather than stopping the program, because a
game whose level fails to start over one corrupt ``.glb`` has failed worse than
one with an invisible car in it.

No GL: a loaded model is a scenegraph of arrays.
"""
import logging
import math

import numpy as np
import pytest

from OpenGLContext.loaders.assets import (
    AssetLibrary, bounds, brighten, recolour, shapes,
)
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform


def _quad(material=None):
    return PBRMesh(
        positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], 'f'),
        normals=np.array([(0, 0, 1)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=material,
    )


@pytest.fixture
def library(tmp_path):
    """A library holding one two-material model, ``car.glb``."""
    paint = PBRMaterial(baseColor=(0.62, 0.09, 0.07), metallic=0.55, roughness=0.32)
    paint.DEF = 'paint'
    glass = PBRMaterial(baseColor=(0.1, 0.13, 0.16), transmission=1.0, ior=1.52)
    glass.DEF = 'glass'
    (tmp_path / 'cars').mkdir()
    write_glb([SceneNode(mesh=_quad(paint), name='body'),
               SceneNode(mesh=_quad(glass), name='glass')],
              path=str(tmp_path / 'cars' / 'car.glb'))
    return AssetLibrary(str(tmp_path))


# --- finding and loading ------------------------------------------------------

def test_path_for_resolves_under_the_root(library, tmp_path):
    assert library.path_for('cars/car.glb') == str(tmp_path / 'cars' / 'car.glb')


def test_load_returns_the_scene_with_its_names(library):
    """A load hands back the whole scene: geometry, named nodes, named materials."""
    scene = library.load('cars/car.glb')
    assert len(list(shapes(scene.group))) == 2
    assert scene.getDEF('body') is not None
    assert sorted(scene.materials) == ['glass', 'paint']


def test_load_of_a_missing_file_is_none_and_warns(library, caplog):
    """A model that is not there leaves the caller without one, and says so."""
    with caplog.at_level(logging.WARNING):
        assert library.load('cars/nothing.glb') is None
    assert 'cars/nothing.glb' in caplog.text


def test_load_of_a_corrupt_file_is_none_and_warns(library, tmp_path, caplog):
    (tmp_path / 'cars' / 'broken.glb').write_bytes(b'not a glb at all')
    with caplog.at_level(logging.WARNING):
        assert library.load('cars/broken.glb') is None
    assert 'broken.glb' in caplog.text


def test_each_load_is_the_caller_s_own(library):
    """Two loads are two models: repainting one leaves the other alone."""
    mine, yours = library.load('cars/car.glb'), library.load('cars/car.glb')
    assert mine is not yours
    mine.materials['paint'].baseColor = (0.0, 1.0, 0.0)
    assert tuple(yours.materials['paint'].baseColor) == pytest.approx((0.62, 0.09, 0.07))


# --- sharing one copy ---------------------------------------------------------

def test_shared_hands_back_one_copy(library):
    """Callers that only draw a model share it, and share the parse."""
    assert library.shared('cars/car.glb') is library.shared('cars/car.glb')


def test_shared_and_load_are_different_copies(library):
    """A caller that means to repaint asks to load, and gets its own."""
    assert library.load('cars/car.glb') is not library.shared('cars/car.glb')


def test_shared_remembers_a_failure(library, caplog):
    """A model that will not load is not retried, and is warned about once."""
    with caplog.at_level(logging.WARNING):
        assert library.shared('cars/nothing.glb') is None
        assert library.shared('cars/nothing.glb') is None
    assert len([one for one in caplog.records if one.levelno >= logging.WARNING]) == 1
    assert 'cars/nothing.glb' in caplog.text


def test_clear_drops_what_was_shared(library):
    """Clearing lets the next call read the file again."""
    first = library.shared('cars/car.glb')
    library.clear()
    assert library.shared('cars/car.glb') is not first


# --- painting -----------------------------------------------------------------

def test_shapes_finds_every_shape(library):
    scene = library.load('cars/car.glb')
    assert [one.geometry.positions.shape[0] for one in shapes(scene.group)] == [4, 4]


def test_recolour_paints_the_whole_subtree(library):
    """One colour over a model, for art whose colour is all it says."""
    scene = library.load('cars/car.glb')
    assert recolour(scene.group, (0.0, 0.4, 0.8)) == 2
    for material in scene.materials.values():
        assert tuple(material.baseColor) == pytest.approx((0.0, 0.4, 0.8))


def test_recolour_leaves_the_rest_of_the_material_alone(library):
    """What makes glass read as glass is not its colour."""
    scene = library.load('cars/car.glb')
    recolour(scene.group, (1.0, 1.0, 1.0))
    assert scene.materials['glass'].transmission == pytest.approx(1.0)
    assert scene.materials['glass'].ior == pytest.approx(1.52)
    assert scene.materials['paint'].metallic == pytest.approx(0.55)


def test_recolour_with_glow_lights_the_model_from_inside(library):
    scene = library.load('cars/car.glb')
    recolour(scene.group, (0.2, 0.4, 0.6), glow=0.5)
    assert tuple(scene.materials['paint'].emissiveColor) == pytest.approx((0.1, 0.2, 0.3))


def test_brighten_keeps_each_material_its_own_colour(library):
    """A floor of light, not a repaint: the reds stay red and the greys grey."""
    scene = library.load('cars/car.glb')
    assert brighten(scene.group, 0.5) == 2
    assert tuple(scene.materials['paint'].emissiveColor) == pytest.approx((0.31, 0.045, 0.035))
    assert tuple(scene.materials['paint'].baseColor) == pytest.approx((0.62, 0.09, 0.07))


# --- how big a model is -------------------------------------------------------

class TestBounds:
    """The box a model occupies, which is what a collider is cut from."""

    def test_it_measures_the_geometry(self, library):
        low, high = bounds(library.load('cars/car.glb').group)
        assert low == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
        assert high == pytest.approx((1.0, 1.0, 0.0), abs=1e-6)

    def test_a_transform_moves_the_box(self):
        shape = Shape(geometry=_quad(), appearance=Appearance())
        placed = Transform(children=[shape], translation=(2.0, -1.0, 0.5))
        low, high = bounds(placed)
        assert low == pytest.approx((2.0, -1.0, 0.5), abs=1e-6)
        assert high == pytest.approx((3.0, 0.0, 0.5), abs=1e-6)

    def test_transforms_compose_through_the_tree(self):
        inner = Transform(children=[Shape(geometry=_quad(), appearance=Appearance())],
                          scale=(2.0, 2.0, 2.0))
        outer = Transform(children=[inner], translation=(0.0, 1.0, 0.0))
        low, high = bounds(outer)
        assert low == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)
        assert high == pytest.approx((2.0, 3.0, 0.0), abs=1e-6)

    def test_a_rotation_turns_the_box(self):
        turned = Transform(children=[Shape(geometry=_quad(), appearance=Appearance())],
                           rotation=(0.0, 0.0, 1.0, math.pi / 2.0))
        low, high = bounds(turned)
        assert low == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)
        assert high == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)

    def test_nothing_to_measure_is_none(self):
        assert bounds(Transform(children=[Transform()])) is None


def test_painting_a_subtree_with_no_materials_touches_nothing():
    assert recolour(Transform(children=[Transform()]), (1.0, 0.0, 0.0)) == 0
    assert brighten(Transform(), 0.5) == 0


def test_repr_says_where_the_art_is(library, tmp_path):
    assert repr(library) == "AssetLibrary(%r)" % (str(tmp_path),)


def test_brighten_lights_a_vrml_material_from_its_diffuse_colour():
    """VRML97's own Material names its colour differently, and is lit the same."""
    from OpenGLContext.scenegraph.appearance import Appearance
    from OpenGLContext.scenegraph.material import Material
    from OpenGLContext.scenegraph.shape import Shape

    material = Material(diffuseColor=(0.8, 0.4, 0.2))
    shape = Shape(geometry=_quad(), appearance=Appearance(material=material))
    assert brighten(Transform(children=[shape]), 0.5) == 1
    assert tuple(material.emissiveColor) == pytest.approx((0.4, 0.2, 0.1))


class TestVariants:
    """A road full of cars is one model painted a dozen ways.

    :meth:`AssetLibrary.load` hands back a copy nobody else holds, which is what
    repainting one needs -- and reading the file again for every car that wants
    the same colour costs a frame each time. A *variant* is one copy per colour:
    prepared once, then shared by everything asking for that colour, which is
    also what lets the pass draw them as one batch.
    """

    def test_the_same_key_hands_back_the_same_copy(self, library):
        first = library.variant('cars/car.glb', 'red')
        assert library.variant('cars/car.glb', 'red') is first

    def test_a_different_key_is_a_different_copy(self, library):
        assert library.variant('cars/car.glb', 'red') is not \
            library.variant('cars/car.glb', 'blue')

    def test_a_variant_is_not_the_shared_copy(self, library):
        """Changing one must not change the model everything else draws."""
        assert library.variant('cars/car.glb', 'red') is not \
            library.shared('cars/car.glb')

    def test_it_is_prepared_once_however_often_it_is_asked_for(self, library):
        made = []

        def prepare(scene):
            made.append(scene)

        for _ in range(4):
            library.variant('cars/car.glb', 'red', prepare=prepare)
        assert len(made) == 1

    def test_what_prepare_did_is_what_every_caller_gets(self, library):
        library.variant('cars/car.glb', 'red',
                        prepare=lambda scene: recolour(scene.group, (1, 0, 0)))
        again = library.variant('cars/car.glb', 'red')
        painted = [shape.appearance.material.baseColor
                   for shape in shapes(again.group)]
        assert all(tuple(colour)[:3] == pytest.approx((1, 0, 0))
                   for colour in painted)

    def test_two_keys_are_painted_independently(self, library):
        for key, colour in (('red', (1, 0, 0)), ('blue', (0, 0, 1))):
            library.variant('cars/car.glb', key,
                            prepare=lambda scene, c=colour: recolour(scene.group, c))
        red = shapes(library.variant('cars/car.glb', 'red').group)
        assert tuple(next(red).appearance.material.baseColor)[:3] == \
            pytest.approx((1, 0, 0))

    def test_a_colour_makes_a_usable_key(self, library):
        """Which is how a caller keys one: by the colour it is painting it."""
        assert library.variant('cars/car.glb', (0.7, 0.2, 0.1)) is \
            library.variant('cars/car.glb', (0.7, 0.2, 0.1))

    def test_a_model_that_will_not_load_is_none(self, library, caplog):
        with caplog.at_level(logging.WARNING):
            assert library.variant('cars/missing.glb', 'red') is None

    def test_and_is_remembered_as_absent(self, library, caplog):
        with caplog.at_level(logging.WARNING):
            library.variant('cars/missing.glb', 'red')
            library.variant('cars/missing.glb', 'red')
        assert len(caplog.records) == 1

    def test_prepare_is_not_called_for_a_model_that_did_not_load(self, library):
        made = []
        library.variant('cars/missing.glb', 'red', prepare=made.append)
        assert made == []

    def test_clear_drops_the_variants_too(self, library):
        first = library.variant('cars/car.glb', 'red')
        library.clear()
        assert library.variant('cars/car.glb', 'red') is not first
