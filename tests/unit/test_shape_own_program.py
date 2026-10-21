"""A geometry that draws through a program of its own is not given the pass's material.

The vegetation and the other layers that make their own GL objects sit in a ``Shape`` so that the
scene holds them like any other node, and draw with their own program, their own textures and
their own uniforms. The pass's PBR program has no use for the shape's material, textures or fill
style then, and setting them for each of the nodes is work a frame does for nothing.

Driven with a recording shader rather than a window.
"""
from typing import Any

import pytest
from vrml import node
from vrml.vrml97 import nodetypes

from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.shape import Shape

DRAWN: list = []


class RecordingProgram:
    """As much of the PBR shader program as a shape asks anything of."""

    def __init__(self):
        self.configured = []
        self.fill_styles = []

    def configure_appearance(self, appearance: Any, mode: Any, geometry: Any = None,
                             back: bool = False) -> None:
        self.configured.append(appearance)

    def set_fill_style(self, style: Any) -> None:
        self.fill_styles.append(style)


class Recording:
    def __init__(self, program, visible=True, shadow_pass=False):
        self.shader_program = program
        self.shader_mode = True
        self.visible = visible
        self.shadow_pass = shadow_pass


class Layer(nodetypes.Geometry, node.Node):
    """Geometry that draws with a program of its own."""

    PROTO = 'OwnProgramTestLayer'
    drawsOwnProgram = True

    def render(self, **named: Any) -> int:
        DRAWN.append(named)
        return 1


class Ordinary(Layer):
    PROTO = 'OrdinaryTestGeometry'
    drawsOwnProgram = False


@pytest.fixture(autouse=True)
def _clear():
    DRAWN.clear()


def _shape(geometry):
    return Shape(geometry=geometry, appearance=Appearance(material=PhysicalMaterial()))


def test_a_layer_is_drawn_and_the_pass_is_given_none_of_its_material():
    program = RecordingProgram()
    _shape(Layer()).Render(Recording(program))
    assert len(DRAWN) == 1
    assert program.configured == [] and program.fill_styles == []


def test_the_geometry_is_told_the_mode_it_is_drawn_in():
    mode = Recording(RecordingProgram())
    _shape(Layer()).Render(mode)
    assert DRAWN[0]['mode'] is mode


def test_ordinary_geometry_is_given_the_pass_material():
    program = RecordingProgram()
    shape = _shape(Ordinary())
    shape.Render(Recording(program))
    assert len(DRAWN) == 1
    assert program.configured == [shape.appearance]
    assert len(program.fill_styles) == 1


def test_a_layer_is_not_drawn_into_a_shadow_map_by_the_shape():
    program = RecordingProgram()
    _shape(Layer()).Render(Recording(program, shadow_pass=True))
    assert program.configured == []
    assert len(DRAWN) == 1


def test_a_layer_is_still_drawn_where_a_pass_selects_what_is_under_the_pointer():
    program = RecordingProgram()
    _shape(Layer()).Render(Recording(program, visible=False))
    assert len(DRAWN) == 1
    assert DRAWN[0]['textured'] is False


def test_the_vegetation_nodes_are_such_layers():
    from OpenGLContext.scenegraph.vegetation.base import InstancedVegBase
    assert InstancedVegBase.drawsOwnProgram is True
