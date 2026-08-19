"""Every shape says whether its geometry carries per-vertex colours.

``hasVertexColor`` tells the PBR shader to modulate the base colour by the
vertex colour attribute. It is one uniform for the whole pass, so a shape that
does not set it inherits whatever the shape before it did -- and geometry with
no colour attribute reads it as black, which is what an unlit marker drawn
after a vertex-coloured terrain came out as.

Driven with a recording shader rather than a window: what is asserted is that
the shape *says*, for every shape, which is the whole of the fix.
"""
from typing import Any

import numpy as np
import pytest

from vrml import node

from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.shape import Shape


class RecordingProgram:
    """As much of the PBR shader program as a shape asks anything of."""

    def __init__(self):
        self.vertex_colors = []

    def configure_appearance(self, appearance: Any, mode: Any) -> None:
        pass

    def set_vertex_color(self, enabled: bool) -> None:
        self.vertex_colors.append(bool(enabled))


class Recording:
    """A mode that is in shader mode and nothing else."""

    def __init__(self, program):
        self.shader_program = program
        self.shader_mode = True
        self.visible = True


class Plain(node.Node):
    """Geometry that draws nothing and carries no per-vertex colours."""

    PROTO = 'PlainTestGeometry'
    colors = None

    def render(self, **named: Any) -> int:
        DRAWN.append(self)
        return 1


class Coloured(Plain):
    """The same, with colours."""

    PROTO = 'ColouredTestGeometry'
    colors = np.ones((3, 3), 'f')


#: What has been drawn, so a test can say the geometry still was.
DRAWN: list = []


@pytest.fixture(autouse=True)
def _drawn():
    DRAWN.clear()
    yield
    DRAWN.clear()


def _shape(coloured=False):
    return Shape(geometry=(Coloured() if coloured else Plain()),
                 appearance=Appearance(material=PBRMaterial(
                     baseColor=(0.9, 0.7, 0.2))))


class TestWhatAShapeSays:
    def test_geometry_with_colours_asks_for_them(self) -> None:
        program = RecordingProgram()
        _shape(coloured=True)._render_shader(Recording(program))
        assert program.vertex_colors[-1] is True

    def test_geometry_without_colours_turns_them_off(self) -> None:
        program = RecordingProgram()
        _shape()._render_shader(Recording(program))
        assert program.vertex_colors[-1] is False

    def test_a_plain_shape_after_a_coloured_one_is_not_left_coloured(self) -> None:
        """The failure this exists for: an unlit marker drawn after terrain."""
        program = RecordingProgram()
        mode = Recording(program)
        _shape(coloured=True)._render_shader(mode)
        _shape()._render_shader(mode)
        assert program.vertex_colors == [True, False]

    def test_the_geometry_is_still_drawn(self) -> None:
        program = RecordingProgram()
        _shape()._render_shader(Recording(program))
        assert len(DRAWN) == 1

    def test_the_shadow_pass_is_left_alone(self) -> None:
        """It draws with the position-only depth program, which has no such
        uniform, and setting one on it targets the wrong program."""
        program = RecordingProgram()
        mode = Recording(program)
        mode.shadow_pass = True
        _shape()._render_shader(mode)
        assert program.vertex_colors == []

    def test_a_program_that_knows_nothing_of_it_is_not_asked(self) -> None:
        """The VRML97 program has no vertex-colour flag of this kind."""

        class Plain:
            def configure_appearance(self, appearance, mode):
                pass

        _shape()._render_shader(Recording(Plain()))
