"""A bound ``Fog`` node reaches the pixels, on a real driver.

The node's arithmetic is tested without GL in ``test_scenegraph_fog``; this is
the other half, and the half that would rot silently -- a uniform that is
computed and never bound looks exactly like one that is.

Each test renders the same red box twice, once with fog and once without, and
compares the framebuffer.  Absolute colours depend on tone mapping, exposure and
the driver; the *relations* between two renders of one scene do not, which is
what these assert.
"""
import os

os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

import numpy as np  # noqa: E402
import pytest  # noqa: E402

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402
from OpenGLContext.scenegraph.fog import Fog  # noqa: E402

pytest_plugins = ['tests.unit.test_passes_render_gl']

#: How far down -Z the box sits, and the fog ranges either side of that: one
#: that has barely started at the box and one that is nearly finished.
BOX_DISTANCE = 20.0
NEAR_RANGE = 25.0
FAR_RANGE = 400.0


@pytest.fixture(autouse=True)
def shader_paths(monkeypatch):
    """Fog is a shader uniform, so every test here needs the shader paths.

    Through ``monkeypatch`` rather than at import: ``renderoptions`` memoises
    what it reads from the environment and the suite's conftest clears that
    memo around each test, so a variable set at import time is read before
    anything can act on it and cleared before anything does.
    """
    from tests.unit.test_passes_render_gl import _base_env
    _base_env(monkeypatch)


def box_scene(*extra):
    """A red box at :data:`BOX_DISTANCE`, plus whatever else is wanted."""
    shape = basenodes.Transform(
        translation=(0, 0, -BOX_DISTANCE),
        children=[basenodes.Shape(
            geometry=basenodes.Box(size=(8, 8, 8)),
            appearance=basenodes.Appearance(
                material=basenodes.Material(diffuseColor=(1, 0, 0))),
        )],
    )
    return [shape, basenodes.PointLight(location=(0, 5, 0), intensity=1.0)] + list(extra)


def rendered(render_scene, *extra):
    """The middle of the frame this scene draws."""
    from tests.unit.test_passes_render_gl import frames_of
    return middle(frames_of(render_scene, box_scene(*extra))[-1])


def middle(image, span=8):
    """The mean colour of the middle of the image, where the box is."""
    height, width = image.shape[:2]
    patch = image[height // 2 - span:height // 2 + span,
                  width // 2 - span:width // 2 + span]
    return patch.reshape(-1, 3).mean(axis=0)


def test_no_fog_node_leaves_the_scene_alone(render_scene):
    """The commonest case by far, and the one that must cost nothing."""
    plain = rendered(render_scene)
    unbound = rendered(render_scene, Fog())
    assert np.allclose(plain, unbound, atol=2)


def test_a_bound_fog_tints_the_scene_toward_its_colour(render_scene):
    blue = Fog(color=(0, 0, 1), visibilityRange=NEAR_RANGE)
    plain = rendered(render_scene)
    fogged = rendered(render_scene, blue)
    assert fogged[2] > plain[2] + 10        # blue arrived
    assert fogged[0] < plain[0] - 10        # at the red's expense


def test_a_shorter_visible_range_fogs_more(render_scene):
    near = Fog(color=(0, 0, 1), visibilityRange=NEAR_RANGE)
    far = Fog(color=(0, 0, 1), visibilityRange=FAR_RANGE)
    close = rendered(render_scene, near)
    distant = rendered(render_scene, far)
    assert close[2] > distant[2] + 10


def test_the_two_curves_differ_at_the_same_range(render_scene):
    """Not approximations of each other, which is why the mode is a uniform.

    At two-fifths of the way to full obscurity the exponential curve is still
    hanging back while the linear one has faded steadily, so the same range
    gives visibly different pictures.
    """
    linear = Fog(color=(0, 0, 1), visibilityRange=50.0, fogType='LINEAR')
    exponential = Fog(color=(0, 0, 1), visibilityRange=50.0, fogType='EXPONENTIAL')
    steady = rendered(render_scene, linear)
    closing = rendered(render_scene, exponential)
    assert abs(float(steady[2]) - float(closing[2])) > 5


def test_a_range_the_geometry_is_beyond_hides_it_completely(render_scene):
    """The far end of the curve: fog colour and nothing else."""
    swallowing = Fog(color=(0, 1, 0), visibilityRange=BOX_DISTANCE * 0.5)
    image = rendered(render_scene, swallowing)
    assert image[1] > image[0] + 40 and image[1] > image[2] + 40
