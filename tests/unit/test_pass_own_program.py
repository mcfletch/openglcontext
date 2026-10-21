"""A pass sets up the draw of a shape for its own program, and not for a layer's.

A shape whose geometry draws with a program of its own (``drawsOwnProgram``) reads none of what the
pass sets for the PBR program: its matrices, the zones and light grid it stands in, a reflection. The
pass leaves them out, and still draws it where it is.
"""
from typing import Any

import numpy as np
import pytest
from vrml import node
from vrml.vrml97 import nodetypes

from OpenGLContext.passes import shaderpass
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.testing.scenes import drawn_image, scene_context

DRAWN: list = []


class Layer(nodetypes.Geometry, node.Node):
    """Geometry that draws with a program of its own, and draws nothing."""

    PROTO = 'PassOwnProgramTestLayer'
    drawsOwnProgram = True

    def render(self, **named: Any) -> int:
        DRAWN.append(named['mode'].matrix.copy())
        return 1

    def boundingVolume(self, mode: Any = None) -> Any:
        from OpenGLContext.scenegraph import boundingvolume
        return boundingvolume.UnboundedVolume()


def _mesh(x):
    return basenodes.Transform(translation=(x, 0, -6), children=[basenodes.Shape(
        geometry=PBRMesh(
            positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0)], 'f'),
            normals=np.array([(0, 0, 1)] * 3, 'f'),
            texcoords=np.array([(0, 0), (1, 0), (1, 1)], 'f'),
            indices=np.array([0, 1, 2], np.uint32)),
        appearance=basenodes.Appearance(material=PhysicalMaterial()))])


def _layer(x):
    return basenodes.Transform(translation=(x, 0, -6), children=[basenodes.Shape(
        geometry=Layer(), appearance=basenodes.Appearance(material=PhysicalMaterial()))])


@pytest.fixture(autouse=True)
def _clear():
    DRAWN.clear()


@pytest.mark.usefixtures('gl_context')
def test_matrices_are_set_for_the_meshes_and_not_for_the_layers(monkeypatch):
    sets = []
    real = shaderpass.VRML97ShaderProgram.set_matrices
    monkeypatch.setattr(shaderpass.VRML97ShaderProgram, 'set_matrices',
                        lambda self, *a, **k: sets.append(1) or real(self, *a, **k))
    scene = [basenodes.Viewpoint(position=(0, 0, 3)), basenodes.NavigationInfo(headlight=True),
             _mesh(-2), _mesh(1), _layer(-1), _layer(0), _layer(2)]
    with scene_context(scene, size=(64, 64), shadows=False) as context:
        context.OnDraw(force=1)
        sets.clear()
        DRAWN.clear()
        drawn_image(context)
    assert len(DRAWN) == 3
    assert len(sets) == 2


@pytest.mark.usefixtures('gl_context')
def test_a_layer_is_still_drawn_with_the_matrix_of_the_place_it_is_in(monkeypatch):
    scene = [basenodes.Viewpoint(position=(0, 0, 3)), basenodes.NavigationInfo(headlight=True),
             _layer(-1), _layer(2)]
    with scene_context(scene, size=(64, 64), shadows=False) as context:
        context.OnDraw(force=1)
        DRAWN.clear()
        drawn_image(context)
    assert len(DRAWN) == 2
    assert not np.allclose(DRAWN[0], DRAWN[1])
