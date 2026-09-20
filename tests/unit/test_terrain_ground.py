"""The ground's own shading, and the meshes drawn with it.

What makes ground *ground* is the blend of detail materials over it, the control
map that says where each belongs and the light baked into it -- not the mesh it
is drawn on. :class:`~OpenGLContext.scenegraph.terrain.ground.GroundShading`
holds that, once for a world, and any mesh can be drawn with it: the one
:class:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain` builds from a
height field, and the ones a bake puts in the tiles of a streamed world.

The GL draw is covered where the other terrain renders are; these are the parts
that need no context.
"""
import types

import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain.ground import (
    GROUND_MATERIAL,
    GroundPatch,
    GroundShading,
    mount_ground,
)
from OpenGLContext.scenegraph.terrain.heightfield import HeightField
from OpenGLContext.scenegraph.terrain.splat import SplatTerrain

EXTENT = 100.0


def _hf(res=8):
    grid = np.linspace(0, 1, res)[:, None] * np.ones((res, res))
    return HeightField(grid, EXTENT, 10.0)


def _shading(**named):
    named.setdefault('material_fn', lambda *a, **k: {})
    named.setdefault('shading', np.ones((8, 8), 'f'))
    return GroundShading(extent=EXTENT, layers=['floor'], control='control.png',
                         **named)


class TestWhatTheGroundIsMadeOf:
    def test_it_knows_the_square_the_control_map_covers(self) -> None:
        """Every layer is placed from world XZ, so the world's own square is
        what the blend is read in."""
        found = _shading()
        assert found.world_min == pytest.approx((-EXTENT / 2, -EXTENT / 2))
        assert found.world_size == pytest.approx((EXTENT, EXTENT))

    def test_the_sun_it_is_lit_by_is_a_direction(self) -> None:
        found = _shading(sun=(0.0, -2.0, 0.0))
        assert float(np.linalg.norm(found.sun)) == pytest.approx(1.0)

    def test_it_resolves_its_layers_the_way_a_terrain_does(self) -> None:
        found = GroundShading(extent=EXTENT, layers=['floor'],
                              control='control.png',
                              shading=np.ones((8, 8), 'f'))
        assert found.material_fn.__module__.endswith('cc0')

    def test_it_holds_the_light_baked_into_the_ground(self) -> None:
        lit = np.full((8, 8), 0.5, 'f')
        assert _shading(shading=lit).shading is lit


class TestAMeshDrawnAsGround:
    def _patch(self, shading=None):
        field = _hf()
        vertices, indices = field.mesh()
        return GroundPatch(shading or _shading(), vertices, indices)

    def test_it_carries_the_mesh_it_was_given(self) -> None:
        patch = self._patch()
        field = _hf()
        assert len(patch.indices) == len(field.mesh()[1])
        assert patch.vertices.shape[1] == 6           # position and normal

    def test_it_shares_the_shading_it_was_given(self) -> None:
        shading = _shading()
        assert self._patch(shading).shading is shading

    def test_it_is_placed_where_the_world_puts_it(self) -> None:
        """A tile is placed by the tileset's transform, where a field is not,
        and the blend is read from world XZ -- so the patch is told."""
        patch = self._patch()
        assert np.allclose(patch.model, np.eye(4))
        moved = np.eye(4)
        moved[3, :3] = (12.0, 0.0, -5.0)
        patch.model = moved
        assert np.allclose(patch.model, moved)

    def test_a_patch_with_no_triangles_draws_nothing(self) -> None:
        patch = GroundPatch(_shading(), np.zeros((0, 6), 'f'),
                            np.zeros(0, 'I'))
        assert patch.render(types.SimpleNamespace(visible=True)) == 1

    def test_the_shadow_pass_is_given_the_geometry_and_no_more(self) -> None:
        """The ground casts: a hill shades the valley behind it. With no GL to
        draw into, what is asked of the node is that it tries."""
        patch = self._patch()
        assert patch.render(types.SimpleNamespace(shadow_pass=True,
                                                  visible=True)) == 1

    def test_an_invisible_pass_draws_nothing(self) -> None:
        patch = self._patch()
        assert patch.render(types.SimpleNamespace(visible=False)) == 1


class TestGroundThatArrivedInATile:
    """A baked world can carry its ground in its tiles: meshed, detailed and cut
    when the world was built, and refined by the streamer as the camera comes
    in. What arrives is an ordinary glTF primitive whose material says *ground*,
    and what draws it is the world's own ground shading."""

    def _tile(self, normals=True, indices=True):
        """A loaded tile: its subtree, and the material the document named."""
        from OpenGLContext.scenegraph.appearance import Appearance
        from OpenGLContext.scenegraph.group import Group
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        from OpenGLContext.scenegraph.shape import Shape
        material = PBRMaterial(baseColor=(1.0, 1.0, 1.0))
        mesh = PBRMesh(
            positions=np.array([[0, 0, 0], [4, 0, 0], [0, 0, 4]], 'f'),
            normals=(np.tile([0, 1, 0], (3, 1)).astype('f') if normals else None),
            indices=(np.array([0, 1, 2], np.uint32) if indices else None),
            material=material)
        tile = Group(children=[Shape(geometry=mesh,
                                     appearance=Appearance(material=material))])
        return tile, {GROUND_MATERIAL: material}

    def test_a_ground_primitive_is_drawn_as_ground(self) -> None:
        tile, named = self._tile()
        shading = _shading()
        assert mount_ground(tile, shading, named[GROUND_MATERIAL]) == 1
        patch = tile.children[0].geometry
        assert isinstance(patch, GroundPatch)
        assert patch.shading is shading

    def test_it_keeps_the_mesh_that_was_baked(self) -> None:
        tile, named = self._tile()
        mount_ground(tile, _shading(), named[GROUND_MATERIAL])
        patch = tile.children[0].geometry
        assert len(patch.indices) == 3
        assert patch.vertices[1, :3] == pytest.approx([4.0, 0.0, 0.0])
        assert patch.vertices[0, 3:] == pytest.approx([0.0, 1.0, 0.0])

    def test_it_is_told_where_the_tile_was_put(self) -> None:
        """A tile is placed by the tileset's own transform, and which layer is
        on the ground is read from world XZ."""
        tile, named = self._tile()
        placed = np.eye(4)
        placed[:3, 3] = (100.0, 0.0, -40.0)
        mount_ground(tile, _shading(), named[GROUND_MATERIAL], model=placed)
        assert np.allclose(tile.children[0].geometry.model, placed)

    def test_anything_else_in_the_tile_is_left_alone(self) -> None:
        """A tile carries a road, a sign and a tree as well, and those are
        drawn as what they are."""
        tile, _named = self._tile()
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
        assert mount_ground(tile, _shading(), PBRMaterial()) == 0
        assert not isinstance(tile.children[0].geometry, GroundPatch)

    def test_a_tile_that_carries_no_ground_mounts_none(self) -> None:
        """Most of them do not: a tile of trees names no ground material."""
        tile, _named = self._tile()
        assert mount_ground(tile, _shading(), None) == 0
        assert not isinstance(tile.children[0].geometry, GroundPatch)

    def test_a_primitive_with_no_normals_is_left_alone(self) -> None:
        """Ground is shaded from its own normals, so one that arrives without
        them is not ground this can draw."""
        tile, named = self._tile(normals=False)
        assert mount_ground(tile, _shading(), named[GROUND_MATERIAL]) == 0

    def test_a_primitive_drawn_without_indices_still_becomes_ground(self) -> None:
        tile, named = self._tile(indices=False)
        assert mount_ground(tile, _shading(), named[GROUND_MATERIAL]) == 1
        assert len(tile.children[0].geometry.indices) == 3


class TestTheNameSurvivesTheFile:
    """The bake and the loader meet on a material name, so the name has to come
    back off the file it was written to."""

    def test_a_ground_material_is_indexed_by_its_name(self) -> None:
        from OpenGLContext.loaders import gltf
        from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        mesh = PBRMesh(
            positions=np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1]], 'f'),
            normals=np.tile([0, 1, 0], (3, 1)).astype('f'),
            indices=np.array([0, 1, 2], np.uint32),
            material=PBRMaterial(baseColor=(1.0, 1.0, 1.0),
                                 DEF=GROUND_MATERIAL))
        scene = gltf.load_gltf(write_glb([SceneNode(mesh=mesh, name='terrain')]))
        assert GROUND_MATERIAL in scene.materials

    def test_and_what_it_names_is_what_the_tile_draws(self) -> None:
        from OpenGLContext.loaders import gltf
        from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        mesh = PBRMesh(
            positions=np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1]], 'f'),
            normals=np.tile([0, 1, 0], (3, 1)).astype('f'),
            indices=np.array([0, 1, 2], np.uint32),
            material=PBRMaterial(baseColor=(1.0, 1.0, 1.0),
                                 DEF=GROUND_MATERIAL))
        scene = gltf.load_gltf(write_glb([SceneNode(mesh=mesh, name='terrain')]))
        assert mount_ground(scene.group, _shading(),
                            scene.materials[GROUND_MATERIAL]) == 1


class TestTheTerrainIsOneOfItsCallers:
    """`SplatTerrain` is a height field's mesh drawn with a world's ground
    shading, and says so: what it offers a caller is unchanged."""

    def _node(self):
        return SplatTerrain(_hf(), ['floor'], 'control.png',
                            material_fn=lambda *a, **k: {})

    def test_it_has_ground_shading_of_its_own(self) -> None:
        assert isinstance(self._node().ground, GroundShading)

    def test_the_shading_is_the_light_the_terrain_baked(self) -> None:
        node = self._node()
        assert node.ground.shading is node.shading

    def test_the_layers_and_the_control_map_are_the_terrains(self) -> None:
        node = self._node()
        assert node.ground.layers == node.layers
        assert node.ground.control == node.control

    def test_the_square_it_blends_over_is_the_fields(self) -> None:
        node = self._node()
        assert node.ground.world_size == pytest.approx((EXTENT, EXTENT))
