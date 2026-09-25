"""Each optional frame layer, made to fail every frame, is tried once and switched off.

Held by :func:`OpenGLContext.testing.layers.check_failing_layer`: planar
reflections, bloom (starting and compositing) and zone probe captures. A
layer is entered once, its failure is logged once with its traceback, the
frames go on being drawn, and it asks for no frame once it has failed.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.passes.reflectionplanner import SETTLE_FRAMES
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.layers import check_failing_layer
from OpenGLContext.testing.scenes import scene_context
from OpenGLContext.passes import renderpass
from OpenGLContext.passes.bloom import BloomPass
from tests.unit.test_pbr_zones import CaptureProbe, CapturingPass

SETTLING = SETTLE_FRAMES + 2

FLOOR = np.array([(-5, 0, -5), (5, 0, -5), (5, 0, 5), (-5, 0, 5)], 'f')


def _mirror_room():
    floor = basenodes.Shape(
        geometry=PBRMesh(positions=FLOOR, normals=np.array([(0, 1, 0)] * 4, 'f'),
                         indices=np.array([0, 2, 1, 0, 3, 2], np.uint32)),
        appearance=basenodes.Appearance(material=PBRMaterial(
            metallic=1.0, roughness=0.0, reflector=PlanarReflector())))
    box = basenodes.Transform(translation=(0, 1, 0), children=[basenodes.Shape(
        geometry=basenodes.Box(),
        appearance=basenodes.Appearance(material=PBRMaterial(baseColor=(1, 0, 0))))])
    return [basenodes.Transform(translation=(0, -1, -6), children=[floor, box])]


@pytest.fixture
def mirror_room():
    """A context drawing a mirror floor with bloom on, past the frames it settles in.

    Reflections ask for frames while their tiles settle, and a frame asked
    for then is not the failing layer's.
    """
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    with scene_context(_mirror_room(), environment={
            'OPENGLCONTEXT_RENDERER': 'pbr',
            'OPENGLCONTEXT_PLANAR_REFLECTIONS': '1',
            'OPENGLCONTEXT_BLOOM': '1'}) as context:
        for _frame in range(SETTLING):
            context.OnDraw(force=1)
        yield context, renderpass.FLAT


def test_reflections_that_fail_are_switched_off_once(mirror_room):
    context, passing = mirror_room
    assert passing.reflectsScene()
    check_failing_layer(lambda: context.OnDraw(force=1), passing,
                        '_renderReflections', context=context)
    assert not passing.planarReflectionsEnabled()


def test_bloom_that_fails_to_start_is_switched_off_once(mirror_room):
    context, passing = mirror_room
    check_failing_layer(lambda: context.OnDraw(force=1), passing, '_startBloom',
                        context=context)
    assert passing._bloomGuard().failed


def test_bloom_that_fails_to_composite_is_switched_off_once(mirror_room):
    context, passing = mirror_room
    check_failing_layer(lambda: context.OnDraw(force=1), BloomPass, 'composite',
                        context=context)
    assert passing._bloomGuard().failed


class _Context:
    def __init__(self):
        self.redraws = 0

    def triggerRedraw(self, force=0):
        self.redraws += 1


def test_a_zone_capture_that_fails_is_not_tried_again():
    zoned = CapturingPass(CaptureProbe())
    zoned.context = _Context()
    zoned.frames(1)
    zoned._ibl_probe.lost += 1           # every probe made again: capture anew
    check_failing_layer(lambda: zoned.frames(1), zoned, '_drawCapture',
                        context=zoned.context)
