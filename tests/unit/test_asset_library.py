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
    merged_by_material,
    merged_mesh,
    AssetLibrary,
    bounds,
    brighten,
    recolour,
    shapes,
)
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform, MatrixTransform
from OpenGLContext.scenegraph.instancedshape import InstancedShape
from OpenGLContext.scenegraph.lod import LOD
from OpenGLContext.scenegraph.material import Material
from OpenGLContext.scenegraph.switch import Switch


def _quad(material=None):
    return PBRMesh(
        positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], "f"),
        normals=np.array([(0, 0, 1)] * 4, "f"),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=material,
    )


@pytest.fixture
def library(tmp_path):
    """A library holding one two-material model, ``car.glb``."""
    paint = PBRMaterial(baseColor=(0.62, 0.09, 0.07), metallic=0.55, roughness=0.32)
    paint.DEF = "paint"
    glass = PBRMaterial(baseColor=(0.1, 0.13, 0.16), transmission=1.0, ior=1.52)
    glass.DEF = "glass"
    (tmp_path / "cars").mkdir()
    write_glb(
        [SceneNode(mesh=_quad(paint), name="body"), SceneNode(mesh=_quad(glass), name="glass")],
        path=str(tmp_path / "cars" / "car.glb"),
    )
    return AssetLibrary(str(tmp_path))


# --- finding and loading ------------------------------------------------------


def test_path_for_resolves_under_the_root(library, tmp_path):
    assert library.path_for("cars/car.glb") == str(tmp_path / "cars" / "car.glb")


def test_load_returns_the_scene_with_its_names(library):
    """A load hands back the whole scene: geometry, named nodes, named materials."""
    scene = library.load("cars/car.glb")
    assert len(list(shapes(scene.group))) == 2
    assert scene.getDEF("body") is not None
    assert sorted(scene.materials) == ["glass", "paint"]


def test_load_of_a_missing_file_is_none_and_warns(library, caplog):
    """A model that is not there leaves the caller without one, and says so."""
    with caplog.at_level(logging.WARNING):
        assert library.load("cars/nothing.glb") is None
    assert "cars/nothing.glb" in caplog.text


def test_load_of_a_corrupt_file_is_none_and_warns(library, tmp_path, caplog):
    (tmp_path / "cars" / "broken.glb").write_bytes(b"not a glb at all")
    with caplog.at_level(logging.WARNING):
        assert library.load("cars/broken.glb") is None
    assert "broken.glb" in caplog.text


def test_each_load_is_the_caller_s_own(library):
    """Two loads are two models: repainting one leaves the other alone."""
    mine, yours = library.load("cars/car.glb"), library.load("cars/car.glb")
    assert mine is not yours
    mine.materials["paint"].baseColor = (0.0, 1.0, 0.0)
    assert tuple(yours.materials["paint"].baseColor) == pytest.approx((0.62, 0.09, 0.07))


# --- sharing one copy ---------------------------------------------------------


def test_shared_hands_back_one_copy(library):
    """Callers that only draw a model share it, and share the parse."""
    assert library.shared("cars/car.glb") is library.shared("cars/car.glb")


def test_shared_and_load_are_different_copies(library):
    """A caller that means to repaint asks to load, and gets its own."""
    assert library.load("cars/car.glb") is not library.shared("cars/car.glb")


def test_shared_remembers_a_failure(library, caplog):
    """A model that will not load is not retried, and is warned about once."""
    with caplog.at_level(logging.WARNING):
        assert library.shared("cars/nothing.glb") is None
        assert library.shared("cars/nothing.glb") is None
    assert len([one for one in caplog.records if one.levelno >= logging.WARNING]) == 1
    assert "cars/nothing.glb" in caplog.text


def test_clear_drops_what_was_shared(library):
    """Clearing lets the next call read the file again."""
    first = library.shared("cars/car.glb")
    library.clear()
    assert library.shared("cars/car.glb") is not first


# --- painting -----------------------------------------------------------------


def test_shapes_finds_every_shape(library):
    scene = library.load("cars/car.glb")
    assert [one.geometry.positions.shape[0] for one in shapes(scene.group)] == [4, 4]


def test_recolour_paints_the_whole_subtree(library):
    """One colour over a model, for art whose colour is all it says."""
    scene = library.load("cars/car.glb")
    assert recolour(scene.group, (0.0, 0.4, 0.8)) == 2
    for material in scene.materials.values():
        assert tuple(material.baseColor) == pytest.approx((0.0, 0.4, 0.8))


def test_recolour_leaves_the_rest_of_the_material_alone(library):
    """What makes glass read as glass is not its colour."""
    scene = library.load("cars/car.glb")
    recolour(scene.group, (1.0, 1.0, 1.0))
    assert scene.materials["glass"].transmission == pytest.approx(1.0)
    assert scene.materials["glass"].ior == pytest.approx(1.52)
    assert scene.materials["paint"].metallic == pytest.approx(0.55)


def test_recolour_with_glow_lights_the_model_from_inside(library):
    scene = library.load("cars/car.glb")
    recolour(scene.group, (0.2, 0.4, 0.6), glow=0.5)
    assert tuple(scene.materials["paint"].emissiveColor) == pytest.approx((0.1, 0.2, 0.3))


def test_brighten_keeps_each_material_its_own_colour(library):
    """A floor of light, not a repaint: the reds stay red and the greys grey."""
    scene = library.load("cars/car.glb")
    assert brighten(scene.group, 0.5) == 2
    assert tuple(scene.materials["paint"].emissiveColor) == pytest.approx((0.31, 0.045, 0.035))
    assert tuple(scene.materials["paint"].baseColor) == pytest.approx((0.62, 0.09, 0.07))


# --- how big a model is -------------------------------------------------------


class TestBounds:
    """The box a model occupies, which is what a collider is cut from."""

    def test_it_measures_the_geometry(self, library):
        low, high = bounds(library.load("cars/car.glb").group)
        assert low == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
        assert high == pytest.approx((1.0, 1.0, 0.0), abs=1e-6)

    def test_a_transform_moves_the_box(self):
        shape = Shape(geometry=_quad(), appearance=Appearance())
        placed = Transform(children=[shape], translation=(2.0, -1.0, 0.5))
        low, high = bounds(placed)
        assert low == pytest.approx((2.0, -1.0, 0.5), abs=1e-6)
        assert high == pytest.approx((3.0, 0.0, 0.5), abs=1e-6)

    def test_transforms_compose_through_the_tree(self):
        inner = Transform(
            children=[Shape(geometry=_quad(), appearance=Appearance())], scale=(2.0, 2.0, 2.0)
        )
        outer = Transform(children=[inner], translation=(0.0, 1.0, 0.0))
        low, high = bounds(outer)
        assert low == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)
        assert high == pytest.approx((2.0, 3.0, 0.0), abs=1e-6)

    def test_a_rotation_turns_the_box(self):
        turned = Transform(
            children=[Shape(geometry=_quad(), appearance=Appearance())],
            rotation=(0.0, 0.0, 1.0, math.pi / 2.0),
        )
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
        first = library.variant("cars/car.glb", "red")
        assert library.variant("cars/car.glb", "red") is first

    def test_a_different_key_is_a_different_copy(self, library):
        assert library.variant("cars/car.glb", "red") is not library.variant("cars/car.glb", "blue")

    def test_a_variant_is_not_the_shared_copy(self, library):
        """Changing one must not change the model everything else draws."""
        assert library.variant("cars/car.glb", "red") is not library.shared("cars/car.glb")

    def test_it_is_prepared_once_however_often_it_is_asked_for(self, library):
        made = []

        def prepare(scene):
            made.append(scene)

        for _ in range(4):
            library.variant("cars/car.glb", "red", prepare=prepare)
        assert len(made) == 1

    def test_what_prepare_did_is_what_every_caller_gets(self, library):
        library.variant(
            "cars/car.glb", "red", prepare=lambda scene: recolour(scene.group, (1, 0, 0))
        )
        again = library.variant("cars/car.glb", "red")
        painted = [shape.appearance.material.baseColor for shape in shapes(again.group)]
        assert all(tuple(colour)[:3] == pytest.approx((1, 0, 0)) for colour in painted)

    def test_two_keys_are_painted_independently(self, library):
        for key, colour in (("red", (1, 0, 0)), ("blue", (0, 0, 1))):
            library.variant(
                "cars/car.glb", key, prepare=lambda scene, c=colour: recolour(scene.group, c)
            )
        red = shapes(library.variant("cars/car.glb", "red").group)
        assert tuple(next(red).appearance.material.baseColor)[:3] == pytest.approx((1, 0, 0))

    def test_a_colour_makes_a_usable_key(self, library):
        """Which is how a caller keys one: by the colour it is painting it."""
        assert library.variant("cars/car.glb", (0.7, 0.2, 0.1)) is library.variant(
            "cars/car.glb", (0.7, 0.2, 0.1)
        )

    def test_a_model_that_will_not_load_is_none(self, library, caplog):
        with caplog.at_level(logging.WARNING):
            assert library.variant("cars/missing.glb", "red") is None

    def test_and_is_remembered_as_absent(self, library, caplog):
        with caplog.at_level(logging.WARNING):
            library.variant("cars/missing.glb", "red")
            library.variant("cars/missing.glb", "red")
        assert len(caplog.records) == 1

    def test_prepare_is_not_called_for_a_model_that_did_not_load(self, library):
        made = []
        library.variant("cars/missing.glb", "red", prepare=made.append)
        assert made == []

    def test_clear_drops_the_variants_too(self, library):
        first = library.variant("cars/car.glb", "red")
        library.clear()
        assert library.variant("cars/car.glb", "red") is not first


class TestMergingAModelIntoOneMesh:
    """A model is often several primitives; a reduction wants one surface.

    A material each, or a 16-bit index limit that split one scan into chunks of
    65,535 vertices -- either way, decimating the pieces apart leaves a seam
    along every join, because neither side knows the other shares its edge.
    """

    def test_one_shape_comes_back_as_itself(self):
        shape = Shape(geometry=_quad())
        attributes, indices = merged_mesh(shape)
        assert attributes["POSITION"] == pytest.approx(shape.geometry.positions)
        assert np.array_equal(indices, shape.geometry.indices)

    def test_two_shapes_become_one_mesh_with_the_indices_moved_along(self):
        group = Transform(children=[Shape(geometry=_quad()), Shape(geometry=_quad())])
        attributes, indices = merged_mesh(group)
        assert len(attributes["POSITION"]) == 8
        assert len(indices) == 12
        # The second primitive's triangles name the second primitive's vertices.
        assert indices[:6].max() == 3
        assert indices[6:].min() == 4

    def test_a_placed_shape_arrives_where_it_is_placed(self):
        """World space, so the pieces of a model line up the way they are drawn."""
        group = Transform(translation=(10.0, 0.0, 0.0), children=[Shape(geometry=_quad())])
        attributes, _indices = merged_mesh(group)
        assert attributes["POSITION"][:, 0].min() == pytest.approx(10.0)

    def test_normals_are_turned_with_the_geometry(self):
        group = Transform(
            rotation=(1.0, 0.0, 0.0, math.pi / 2.0), children=[Shape(geometry=_quad())]
        )
        attributes, _indices = merged_mesh(group)
        # The quad's +Z normal turned a quarter turn about X points along -Y.
        assert attributes["NORMAL"][0] == pytest.approx((0.0, -1.0, 0.0), abs=1e-6)
        assert np.linalg.norm(attributes["NORMAL"], axis=1) == pytest.approx(1.0)

    def test_a_subtree_with_no_geometry_merges_to_nothing(self):
        assert merged_mesh(Transform(children=[])) is None

    def test_a_mesh_with_no_normals_is_given_the_surface_s_own(self):
        """A reduction needs them, and a shaded picture of the result needs them."""
        bare = PBRMesh(
            positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0)], "f"),
            indices=np.array([0, 1, 2], np.uint32),
        )
        attributes, _indices = merged_mesh(Shape(geometry=bare))
        assert attributes["NORMAL"].shape == (3, 3)
        assert attributes["NORMAL"][0] == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)


class TestMergingWhatIsDrawn:
    """The merge is the model as it is drawn: every placement, mirrored and
    stretched copies included, and one level or choice of a node that draws
    one of several."""

    @staticmethod
    def _slanted():
        """A triangle leaning out of its plane, with its true normal."""
        points = np.array([(0, 0, 0), (1, 0, 1), (0, 1, 0)], "f")
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        mesh = PBRMesh(positions=points,
                       normals=np.tile(normal / np.linalg.norm(normal), (3, 1)),
                       indices=np.array([0, 1, 2], np.uint32))
        return Shape(geometry=mesh, appearance=Appearance(material=PBRMaterial()))

    @staticmethod
    def _facing(attributes, indices):
        """How well each triangle's winding agrees with its normals, -1 to 1."""
        corners = attributes["POSITION"][indices.reshape(-1, 3)]
        wound = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        wound /= np.linalg.norm(wound, axis=1, keepdims=True)
        given = attributes["NORMAL"][indices.reshape(-1, 3)[:, 0]]
        return np.einsum("ij,ij->i", wound, given)

    def test_a_stretched_copy_keeps_its_normals_square_to_its_surface(self) -> None:
        attributes, indices = merged_mesh(
            Transform(scale=(4.0, 1.0, 1.0), children=[self._slanted()]))
        assert self._facing(attributes, indices).min() == pytest.approx(1.0, abs=1e-5)

    def test_a_mirrored_copy_is_wound_to_face_the_way_its_normals_do(self) -> None:
        attributes, indices = merged_mesh(
            Transform(scale=(-1.0, 1.0, 1.0), children=[self._slanted()]))
        assert self._facing(attributes, indices).min() == pytest.approx(1.0, abs=1e-5)

    def test_a_level_of_detail_merges_its_finest_level(self) -> None:
        fine = Shape(geometry=_quad())
        coarse = Shape(geometry=PBRMesh(
            positions=np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], "f"),
            indices=np.array([0, 1, 2], np.uint32)))
        attributes, indices = merged_mesh(LOD(level=[fine, coarse], range=[10.0]))
        assert len(attributes["POSITION"]) == 4 and len(indices) == 6

    def test_a_switch_merges_the_child_it_shows(self) -> None:
        shown = Transform(translation=(5.0, 0.0, 0.0), children=[Shape(geometry=_quad())])
        attributes, _indices = merged_mesh(
            Switch(choice=[Shape(geometry=_quad()), shown], whichChoice=1))
        assert float(attributes["POSITION"][:, 0].min()) == pytest.approx(5.0)

    def test_a_switch_showing_nothing_merges_nothing(self) -> None:
        assert merged_mesh(Switch(choice=[Shape(geometry=_quad())],
                                  whichChoice=-1)) is None

    def test_an_instanced_shape_merges_each_placement(self) -> None:
        placements = np.tile(np.eye(4, dtype="f"), (2, 1, 1))
        placements[1, 3, :3] = (10.0, 0.0, 0.0)
        attributes, indices = merged_mesh(
            InstancedShape(geometry=_quad(), placements=placements))
        assert len(attributes["POSITION"]) == 8 and len(indices) == 12
        assert float(attributes["POSITION"][:, 0].max()) == pytest.approx(11.0)

    def test_a_matrix_transform_places_what_is_measured(self) -> None:
        moved = np.eye(4)
        moved[3, :3] = (0.0, 7.0, 0.0)
        low, _high = bounds(MatrixTransform(localMatrix=moved,
                                            children=[Shape(geometry=_quad())]))
        assert float(low[1]) == pytest.approx(7.0)


class TestMergingOneMeshPerMaterial:
    """A textured model cannot become one mesh: a mesh draws with one material.

    Grouping by material is the most a reduction can merge without losing what
    the surface looks like, and it is enough -- what splits a model into
    primitives is usually the index width, not the material.
    """

    def _two_materials(self):
        red, blue = PBRMaterial(baseColor=(1, 0, 0)), PBRMaterial(baseColor=(0, 0, 1))
        return (
            red,
            blue,
            Transform(
                children=[
                    Shape(geometry=_quad(), appearance=Appearance(material=red)),
                    Shape(geometry=_quad(), appearance=Appearance(material=blue)),
                    Shape(geometry=_quad(), appearance=Appearance(material=red)),
                ]
            ),
        )

    def test_the_pieces_sharing_a_material_become_one_mesh(self):
        red, blue, group = self._two_materials()
        grouped = merged_by_material(group)
        assert len(grouped) == 2
        by_material = {
            id(material): (attributes, indices) for material, attributes, indices in grouped
        }
        assert len(by_material[id(red)][1]) == 12  # two quads
        assert len(by_material[id(blue)][1]) == 6  # one

    def test_each_group_is_a_mesh_in_its_own_right(self):
        _red, _blue, group = self._two_materials()
        for _material, attributes, indices in merged_by_material(group):
            assert len(attributes["POSITION"]) == len(attributes["NORMAL"])
            assert indices.max() < len(attributes["POSITION"])

    def test_the_order_is_the_order_the_materials_were_met_in(self):
        """So a caller's report reads the same way twice."""
        red, blue, group = self._two_materials()
        assert [id(m) for m, _a, _i in merged_by_material(group)] == [id(red), id(blue)]

    def test_texture_coordinates_come_along(self):
        """Without them a decimated mesh cannot be drawn with its own texture."""
        uv = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], "f")
        mesh = _quad()
        mesh.texcoords = uv
        grouped = merged_by_material(Shape(geometry=mesh, appearance=Appearance()))
        assert grouped[0][1]["TEXCOORD_0"] == pytest.approx(uv)

    def test_a_group_where_only_some_pieces_have_uvs_still_merges(self):
        """The ones without get zeroes rather than the group losing them all."""
        material = PBRMaterial()
        textured, bare = _quad(), _quad()
        textured.texcoords = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], "f")
        group = Transform(
            children=[
                Shape(geometry=textured, appearance=Appearance(material=material)),
                Shape(geometry=bare, appearance=Appearance(material=material)),
            ]
        )
        _material, attributes, _indices = merged_by_material(group)[0]
        assert attributes["TEXCOORD_0"].shape == (8, 2)
        assert attributes["TEXCOORD_0"][4:] == pytest.approx(0.0)

    def test_a_subtree_with_no_geometry_groups_to_nothing(self):
        assert merged_by_material(Transform(children=[])) == []


class TestARootAskedForAtEachUse:
    """An application whose art arrives after start-up names its art by a
    function rather than by a directory, and each load asks it."""

    def test_the_library_reads_from_wherever_the_art_is_now(self, library,
                                                             tmp_path):
        where = [str(tmp_path / "not-yet")]
        following = AssetLibrary(lambda: where[0])
        assert following.load("cars/car.glb") is None
        where[0] = str(tmp_path)
        assert following.path_for("cars/car.glb") == \
            str(tmp_path / "cars" / "car.glb")
        assert following.load("cars/car.glb") is not None

    def test_what_was_shared_from_the_old_place_is_let_go(self, library,
                                                          tmp_path):
        where = [str(tmp_path / "not-yet")]
        following = AssetLibrary(lambda: where[0])
        assert following.shared("cars/car.glb") is None
        where[0] = str(tmp_path)
        assert following.shared("cars/car.glb") is not None

    def test_nothing_is_asked_until_a_model_is(self):
        asked = []
        AssetLibrary(lambda: asked.append(1) or "/nowhere")
        assert asked == []
