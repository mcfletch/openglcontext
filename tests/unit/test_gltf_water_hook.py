"""Water authored in a model rather than in Python.

An artist puts a custom property on the lake's material in Blender and exports;
the surface loads as water, moves, and is something a walking context can be
inside of. The ``water`` kind ships registered, so a tagged file needs no
application code at all.

Each test writes a document with :mod:`OpenGLContext.loaders.gltf.writer` and
reads it back with :func:`OpenGLContext.loaders.gltf.load_gltf`. No GL: a wave
on the card is two attributes on the geometry, and those are numbers.
"""
import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph import water
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape


def _sheet(tag, level=0.0, side=10.0):
    """A horizontal quad tagged as water, as an exporter would write one."""
    material = PBRMaterial(baseColor=(0.05, 0.1, 0.12))
    material.extras = {'OGLC_hook': tag}
    return PBRMesh(
        positions=np.array([(0, level, 0), (side, level, 0),
                            (side, level, side), (0, level, side)], 'f'),
        normals=np.array([(0, 1, 0)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=material,
    )


def _shapes(node, out=None):
    out = [] if out is None else out
    if isinstance(node, Shape):
        out.append(node)
    for child in getattr(node, 'children', None) or []:
        _shapes(child, out)
    return out


def _loaded(tag, **named):
    scene = gltf.load_gltf(write_glb(SceneNode(mesh=_sheet(tag, **named))))
    return scene, _shapes(scene.group)[0]


# --- the kind ships registered ------------------------------------------------

def test_the_water_kind_is_bound_without_being_imported():
    """A tagged file works in a viewer that never heard of water."""
    entry = hooks.registered('water')
    assert entry is not None
    assert entry.shareable is False


# --- what the tag does to the surface -----------------------------------------

def test_a_tagged_material_gives_the_mesh_a_wave():
    """The whole contract with the card: two attributes on the geometry."""
    _scene, shape = _loaded('water')
    assert shape.geometry.wave_style is water.STILL
    assert shape.geometry.wave_time == pytest.approx(0.0)


@pytest.mark.parametrize('name, style', [
    ('still', water.STILL), ('flowing', water.FLOWING),
    ('choppy', water.CHOPPY), ('lake', water.LAKE),
])
def test_the_named_styles_map(name, style):
    _scene, shape = _loaded({'kind': 'water', 'style': name})
    assert shape.geometry.wave_style is style


def test_a_style_may_be_written_out_in_full():
    """Water is a continuum; an artist who wants a fourth motion writes one."""
    _scene, shape = _loaded({'kind': 'water', 'style': {
        'amplitude': 0.3, 'wavelength': 6.0, 'speed': 2.0,
        'steepness': 0.1, 'flow': [1.0, 0.5]}})
    style = shape.geometry.wave_style
    assert style.amplitude == pytest.approx(0.3)
    assert style.wavelength == pytest.approx(6.0)
    assert style.flow == pytest.approx((1.0, 0.5))
    assert style.moving()


def test_an_unknown_style_name_is_still_water(caplog):
    """A misspelling loads a pond rather than failing the file."""
    _scene, shape = _loaded({'kind': 'water', 'style': 'stil'})
    assert shape.geometry.wave_style is water.STILL


# --- which material shades it -------------------------------------------------

def test_the_file_shades_its_own_water_by_default():
    """What the artist authored is what is drawn."""
    _scene, shape = _loaded('water')
    assert tuple(shape.appearance.material.baseColor) == pytest.approx(
        (0.05, 0.1, 0.12), abs=1e-3)


def test_the_engine_material_may_be_asked_for():
    """``material: engine`` takes the engine's own open water instead."""
    _scene, shape = _loaded({'kind': 'water', 'material': 'engine'})
    material = shape.appearance.material
    assert tuple(material.baseColor) == pytest.approx(water.WATER_ALBEDO)
    assert material.roughness == pytest.approx(water.WATER_ROUGHNESS)
    assert material is shape.geometry.material


# --- where the water is -------------------------------------------------------

def test_the_body_lands_in_hook_data():
    """A walking context finds the volumes through the scene."""
    scene, shape = _loaded('water')
    body, = scene.hook_data['water']
    assert body.mesh is shape.geometry
    assert body.volume.medium == water.WATER
    assert body.volume.minimum == pytest.approx((0.0, 0.0, 0.0))
    assert body.volume.maximum == pytest.approx((10.0, 0.0, 10.0))


def test_the_volume_is_where_the_node_puts_it():
    """The box is round where this copy stands, not round the mesh's origin."""
    scene = gltf.load_gltf(write_glb(
        SceneNode(mesh=_sheet('water'), translation=(100.0, 2.0, 0.0))))
    body, = scene.hook_data['water']
    assert body.volume.minimum == pytest.approx((100.0, 2.0, 0.0))
    assert body.volume.maximum == pytest.approx((110.0, 2.0, 10.0))


def test_depth_gives_a_sheet_something_to_be_inside_of():
    """A surface has no thickness; ``depth`` says how far down the body goes."""
    scene, _shape = _loaded({'kind': 'water', 'depth': 4.0}, level=6.0)
    body, = scene.hook_data['water']
    assert body.volume.minimum[1] == pytest.approx(2.0)
    assert body.volume.maximum[1] == pytest.approx(6.0)
    assert body.volume.contains((5.0, 3.0, 5.0))
    assert not body.volume.contains((5.0, 1.0, 5.0))


def test_the_volumes_answer_what_is_at_a_point():
    """What the subsystem asks of a world, a tagged file can now answer."""
    scene, _shape = _loaded({'kind': 'water', 'depth': 3.0})
    volumes = water.Volumes([body.volume for body in scene.hook_data['water']])
    assert volumes.medium_at((5.0, -1.0, 5.0)) == water.WATER
    assert volumes.medium_at((5.0, 40.0, 5.0)) == ''


@pytest.mark.parametrize('medium', [water.WATER, water.SLIME, water.LAVA])
def test_lava_is_the_same_hook_with_another_medium(medium):
    """It needs no second kind: what it is like inside is a parameter."""
    scene, shape = _loaded({'kind': 'water', 'medium': medium,
                            'style': 'flowing'})
    body, = scene.hook_data['water']
    assert body.volume.medium == medium
    assert shape.geometry.wave_style is water.FLOWING


# --- moving it ----------------------------------------------------------------

def test_advance_moves_a_moving_style_and_says_so():
    """Nothing advances a loaded scene's wave until something is asked to."""
    scene, shape = _loaded({'kind': 'water', 'style': 'choppy'})
    assert shape.geometry.wave_time == pytest.approx(0.0)
    assert scene.advance(1.5) is True
    assert shape.geometry.wave_time == pytest.approx(1.5)


def test_still_water_costs_nothing_to_advance():
    """A pond's ripple is in the light on it; there is nothing to redraw for."""
    scene, shape = _loaded('water')
    assert scene.advance(1.5) is False
    assert shape.geometry.wave_time == pytest.approx(0.0)


def test_each_body_keeps_its_own_surface():
    """Two lakes on one mesh are two lakes: two boxes, and two wave clocks."""
    mesh = _sheet({'kind': 'water', 'style': 'choppy'})
    scene = gltf.load_gltf(write_glb([
        SceneNode(mesh=mesh, name='near'),
        SceneNode(mesh=mesh, name='far', translation=(0.0, 0.0, 50.0))]))
    first, second = _shapes(scene.group)
    assert first.geometry is not second.geometry
    assert len(scene.hook_data['water']) == 2
    boxes = sorted(body.volume.minimum[2] for body in scene.hook_data['water'])
    assert boxes == pytest.approx([0.0, 50.0])


def test_a_lake_with_coarser_levels_records_each_level_once():
    """``MSFT_lod`` on a tagged node: the finest level drawn is the one recorded."""
    import pygltflib
    document = pygltflib.GLTF2.load_from_bytes(write_glb([
        SceneNode(mesh=_sheet('water')),
        SceneNode(mesh=_sheet({'kind': 'water'}, side=2.0))]))
    finest, coarser = document.scenes[0].nodes
    document.nodes[finest].extensions = {'MSFT_lod': {'ids': [coarser]}}
    document.nodes[finest].extras = {'MSFT_screencoverage': [0.5, 0.1]}
    document.scenes[0].nodes = [finest]
    document.extensionsUsed = [*(document.extensionsUsed or []), 'MSFT_lod']
    scene = gltf.load_gltf(b''.join(document.save_to_bytes()))
    # The coarser level is water too, and is recorded as the level it is.
    drawn = [shape.geometry for shape in _all_shapes(scene.group)]
    bodies = scene.hook_data['water']
    assert len(bodies) == len(drawn) == 2
    assert all(any(body.mesh is mesh for mesh in drawn) for body in bodies)


def _all_shapes(node, out=None):
    """Every Shape, down through the levels of a switching node too."""
    out = [] if out is None else out
    if isinstance(node, Shape):
        out.append(node)
    for child in (getattr(node, 'children', None) or []) + \
            list(getattr(node, 'level', None) or []):
        _all_shapes(child, out)
    return out
