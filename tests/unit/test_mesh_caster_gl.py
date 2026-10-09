"""A mesh casts its shadow in both renderers.

Geometry drawn as a `PBRMesh` (a triangle set, a face set, a primitive, a glTF
mesh) writes its positions into the shadow maps through `depthDraw`, under the
PBR program and under the VRML97 one, which has no skinning.
"""
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context

FLOOR = [(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)]


def floor():
    return basenodes.Shape(
        geometry=basenodes.IndexedFaceSet(coord=basenodes.Coordinate(point=FLOOR),
                                          coordIndex=[0, 1, 2, 3, -1]),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(1, 1, 1))))


def lit_floor(caster, renderer, shadows=True):
    """The frame's brightness: the floor under a spot light, with `caster` over it or not"""
    light = basenodes.SpotLight(location=(0, 0, 6), direction=(0, 0, -1), cutOffAngle=0.785,
                                beamWidth=1.5)
    children = [basenodes.Viewpoint(position=(0, -3, 12)),
                basenodes.NavigationInfo(headlight=False), light, floor()]
    if caster is not None:
        shape = basenodes.Shape(geometry=caster, appearance=basenodes.Appearance(
            material=basenodes.Material(diffuseColor=(1, 1, 1))))
        children.append(basenodes.Transform(translation=(0, 0, 2), children=[shape]))
    environment = {'OPENGLCONTEXT_IBL': 'off'}
    if not shadows:
        environment['OPENGLCONTEXT_SHADOWS'] = '0'
    with scene_context(children, size=(48, 48), renderer=renderer,
                       environment=environment) as context:
        drawn_image(context)
        return int(drawn_image(context).astype(int).sum())


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
@pytest.mark.parametrize('caster', [
    lambda: basenodes.Box(),
    lambda: basenodes.Sphere(),
    lambda: basenodes.IndexedFaceSet(coord=basenodes.Coordinate(point=[
        (-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]), coordIndex=[0, 1, 2, 3, -1],
        solid=False),
], ids=['Box', 'Sphere', 'IndexedFaceSet'])
def test_a_mesh_shadows_the_floor(gl_context, renderer, caster):
    """The caster itself is lit less than the floor it hides, so the frame
    with it is darker by more than its own area could make it"""
    bare = lit_floor(None, renderer)
    shadowed = lit_floor(caster(), renderer)
    unshadowed = lit_floor(caster(), renderer, shadows=False)
    assert shadowed < unshadowed - 0.02 * bare, (bare, shadowed, unshadowed)
