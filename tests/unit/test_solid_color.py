"""The one colour a line or a point set with no colours of its own is drawn in.

X3D (19775-1, 11.4.9 IndexedLineSet, 11.4.11 PointSet; VRML97 likewise): with
no Color node, a Material's emissiveColor, unlit. A scene built in code draws
an emitting material's emissive colour and any other material's diffuse or
base colour, so a red line drawn with a red Material is red.
"""
import pytest

from OpenGLContext.passes.shaderpass import appearance_solid_color
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.material import Material


def test_x3ds_rule_is_the_emissive_colour():
    look = Appearance(material=Material(diffuseColor=(1, 0, 0), emissiveColor=(0, 0, 0)))
    assert appearance_solid_color(look, x3d=True) == (0.0, 0.0, 0.0, 1.0)
    look.material.emissiveColor = (0, 0.5, 0)
    assert appearance_solid_color(look, x3d=True) == (0.0, 0.5, 0.0, 1.0)


def test_the_engines_rule_falls_back_to_the_diffuse_colour():
    look = Appearance(material=Material(diffuseColor=(1, 0, 0), transparency=0.25))
    assert appearance_solid_color(look) == (1.0, 0.0, 0.0, 0.75)


@pytest.mark.parametrize('x3d', [False, True])
def test_no_material_is_white(x3d):
    assert appearance_solid_color(Appearance(), x3d=x3d) == (1.0, 1.0, 1.0, 1.0)
    assert appearance_solid_color(None, x3d=x3d) == (1.0, 1.0, 1.0, 1.0)
