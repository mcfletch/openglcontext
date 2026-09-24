"""The Blender add-on that writes ``OGLC_hook`` as an extension.

The add-on lives outside the package, in ``tools/blender/oglc_hook``, because
Blender runs it in its own interpreter and nothing there can import the engine.
What it says about a material therefore has to agree with what the loader reads,
and these tests are where the two meet: the block the panel builds is handed to
:mod:`OpenGLContext.loaders.gltf.hooks` and to a written document.

``tag.py`` is the half that holds the rules and imports no ``bpy``, so it is
tested as ordinary code. ``__init__.py`` is the Blender half -- properties,
panels and the exporter extension -- and is read as source here, which is what
catches a hook Blender no longer calls or a key spelled twice.
"""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph import particlehooks, particles, water
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.water import gltf as watergltf
from OpenGLContext.scenegraph.water.medium import MEDIA

ADDON = Path(__file__).resolve().parents[2] / 'tools' / 'blender' / 'oglc_hook'


def _module(name, path):
    """One file loaded as a module, since the add-on is not on the path."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tag = _module('oglc_hook_tag', ADDON / 'tag.py')


def settings(**named):
    """The panel's properties, as the add-on reads them off a datablock."""
    values = dict(enabled=True, kind='water', style='still', material='keep',
                  medium='water', depth=0.0, scale=1.0, density=1.0,
                  parameters='')
    values.update(named)
    return SimpleNamespace(**values)


# --- the add-on and the engine spell the same thing ---------------------------

def test_the_key_is_the_one_the_loader_reads():
    assert tag.EXTENSION == hooks.EXTENSION


def test_the_styles_offered_are_the_ones_the_engine_knows():
    assert set(tag.STYLES) == set(watergltf.STYLES)


def test_the_media_offered_are_the_ones_the_engine_has():
    assert set(tag.MEDIA) == set(MEDIA)


def test_the_kinds_offered_are_the_ones_the_engine_ships():
    assert set(tag.KINDS) == set(hooks.BUILTIN)


def test_the_effects_offered_are_the_engines_particle_kinds():
    assert set(tag.EFFECTS) == set(particlehooks.KINDS)


def test_the_tag_module_needs_no_blender():
    """What holds the rules is testable because it imports nothing of Blender."""
    tree = ast.parse((ADDON / 'tag.py').read_text(encoding='utf-8'))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split('.')[0])
    assert 'bpy' not in imported


# --- what the panel writes ----------------------------------------------------

def test_a_material_nobody_tagged_writes_nothing():
    assert tag.hook_block(settings(enabled=False)) is None


def test_a_kind_with_no_parameters_is_the_kind_alone():
    assert tag.hook_block(settings(enabled=True, kind='glisteel:rail',
                                   parameters='')) == {'kind': 'glisteel:rail'}


def test_a_blank_kind_writes_nothing():
    """The panel is on and names nothing; there is no tag to write."""
    assert tag.hook_block(settings(kind='   ')) is None


def test_water_writes_the_style_it_was_given():
    assert tag.hook_block(settings(style='choppy')) == {
        'kind': 'water', 'style': 'choppy',
    }


def test_water_leaves_out_what_it_never_changed():
    """Defaults are the loader's already; writing them says nothing extra."""
    block = tag.hook_block(settings(style='lake', medium='water',
                                    material='keep', depth=0.0))
    assert block == {'kind': 'water', 'style': 'lake'}


def test_water_writes_the_medium_the_depth_and_the_shading_it_was_given():
    block = tag.hook_block(settings(style='flowing', medium='lava',
                                    material='engine', depth=6.0))
    assert block == {
        'kind': 'water', 'style': 'flowing', 'material': 'engine',
        'medium': 'lava', 'depth': 6.0,
    }


def test_the_water_fields_belong_to_water():
    """Another kind gets what its own parameters field says, and no more."""
    block = tag.hook_block(settings(kind='twigbb:teleporter', style='choppy',
                                    medium='lava', depth=6.0,
                                    parameters='{"target": "gate-2"}'))
    assert block == {'kind': 'twigbb:teleporter', 'target': 'gate-2'}


def test_an_effect_left_at_its_defaults_is_the_kind_alone():
    assert tag.hook_block(settings(kind='fire')) == {'kind': 'fire'}


def test_an_effect_writes_the_scale_and_density_it_was_given():
    assert tag.hook_block(settings(kind='smoke', scale=2.5, density=0.5)) == {
        'kind': 'smoke', 'scale': 2.5, 'density': 0.5,
    }


def test_the_effect_fields_belong_to_the_effects():
    assert tag.hook_block(settings(style='choppy', scale=3.0, density=2.0)) == {
        'kind': 'water', 'style': 'choppy',
    }


@pytest.mark.parametrize('kind, on', [('fire', 'object'), ('sparks', 'object'),
                                      ('water', 'material'),
                                      ('twigbb:teleporter', 'object'),
                                      ('twigbb:teleporter', 'material')])
def test_a_kind_where_it_belongs_draws_no_warning(kind, on):
    assert tag.misplaced(kind, on) == ''


@pytest.mark.parametrize('kind, on, belongs', [('fire', 'material', 'object'),
                                               ('smoke', 'material', 'object'),
                                               ('water', 'object', 'material')])
def test_a_kind_where_the_engine_ignores_it_says_where_it_goes(kind, on, belongs):
    """A flame on a material, or water on an empty, loads as nothing at all."""
    assert belongs in tag.misplaced(kind, on)


def test_the_kinds_are_offered_as_they_are_typed():
    """The kind field is free text with the engine's own kinds suggested."""
    assert tag.suggestions('') == sorted(tag.KINDS)
    assert tag.suggestions('SP') == ['sparks']
    assert tag.suggestions('glisteel:rail') == []


def test_the_parameters_field_outranks_the_panel():
    """The escape hatch for a kind whose parameters the panel has no fields for."""
    block = tag.hook_block(settings(style='still',
                                    parameters='{"style": "choppy", "level": 12.5}'))
    assert block == {'kind': 'water', 'style': 'choppy', 'level': 12.5}


def test_a_kind_in_the_parameters_is_not_the_kind():
    """The kind has a field of its own; the JSON object carries parameters."""
    block = tag.hook_block(settings(kind='water', style='still',
                                    parameters='{"kind": "lava"}'))
    assert block == {'kind': 'water', 'style': 'still'}


def test_parameters_that_are_not_json_are_reported():
    with pytest.raises(ValueError) as raised:
        tag.hook_block(settings(parameters='{style: choppy}'))
    assert 'parameters' in str(raised.value).lower()


def test_parameters_that_are_not_an_object_are_reported():
    """A list has no parameter names in it, so there is nothing to merge."""
    with pytest.raises(ValueError) as raised:
        tag.hook_block(settings(parameters='["choppy"]'))
    assert 'object' in str(raised.value).lower()


def test_blank_parameters_are_no_parameters():
    assert tag.hook_block(settings(kind='portal', parameters='   ')) == {
        'kind': 'portal',
    }


def test_the_panel_can_show_what_the_file_will_carry():
    line = tag.preview(tag.hook_block(settings(style='choppy')))
    assert line == '%s: {"kind": "water", "style": "choppy"}' % tag.EXTENSION


def test_there_is_nothing_to_show_for_a_material_nobody_tagged():
    assert tag.preview(tag.hook_block(settings(enabled=False))) == ''


# --- the block the panel builds is the block the loader reads -----------------

def test_the_block_reads_back_as_the_tag_it_meant():
    block = tag.hook_block(settings(style='choppy', depth=6.0))
    read = hooks.tag_from(None, {hooks.EXTENSION: block})
    assert read.kind == 'water'
    assert read.params == {'style': 'choppy', 'depth': 6.0}


def test_a_tagged_material_loads_as_moving_water():
    """The whole path: panel -> extension block -> written file -> a wave."""
    material = PBRMaterial(baseColor=(0.05, 0.1, 0.12))
    material.hook = tag.hook_block(settings(style='choppy', depth=4.0))
    mesh = PBRMesh(
        positions=np.array([(0, 0, 0), (8, 0, 0), (8, 0, 8), (0, 0, 8)], 'f'),
        normals=np.array([(0, 1, 0)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=material,
    )
    scene = gltf.load_gltf(write_glb(SceneNode(mesh=mesh)))
    shapes = [node for node in _walk(scene.group) if isinstance(node, Shape)]
    assert shapes[0].geometry.waveStyle is water.CHOPPY
    body = scene.hook_data['water'][0]
    assert body.volume.minimum[1] == pytest.approx(-4.0)


def test_a_tagged_object_loads_burning():
    """The whole path: panel -> extension block -> written file -> an emitter."""
    block = tag.hook_block(settings(kind='fire', scale=2.0))
    scene = gltf.load_gltf(write_glb(SceneNode(name='torch', hook=block)))
    emitter, = scene.hook_data['fire']
    assert emitter.size == pytest.approx(2.0 * particles.PRESETS['fire']['size'])


def _walk(node, out=None):
    out = [] if out is None else out
    out.append(node)
    for child in getattr(node, 'children', None) or []:
        _walk(child, out)
    return out


# --- the Blender half ---------------------------------------------------------

def _addon_source():
    return (ADDON / '__init__.py').read_text(encoding='utf-8')


def _addon_tree():
    return ast.parse(_addon_source())


def test_the_addon_declares_the_exporter_hooks_blender_calls():
    """``gather_material_hook`` and ``gather_node_hook`` are the two names
    glTF-Blender-IO looks for on a user extension."""
    defined = {node.name for node in ast.walk(_addon_tree())
               if isinstance(node, ast.FunctionDef)}
    assert 'gather_material_hook' in defined
    assert 'gather_node_hook' in defined


def test_the_addon_declares_what_blender_it_needs():
    """``bl_info`` is what Blender reads before it imports anything else."""
    info = next(node for node in ast.walk(_addon_tree())
                if isinstance(node, ast.Assign)
                and any(getattr(target, 'id', None) == 'bl_info'
                        for target in node.targets))
    declared = ast.literal_eval(info.value)
    assert declared['blender'][0] >= 4
    assert 'category' in declared and 'name' in declared


def test_the_key_is_spelled_in_one_place():
    """The Blender half names the key through ``tag``, so there is one copy.

    The prose says the word; nothing the exporter writes with does.
    """
    tree = _addon_tree()
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            docstrings.add(first.value)
    written = [node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)
               and node not in docstrings]
    assert hooks.EXTENSION not in written
