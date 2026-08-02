"""One viewer, several formats (:mod:`OpenGLContext.viewer.sceneviewer`).

``oglc-view model.glb`` and ``oglc-view world.wrl`` are the same viewer with a
different adapter, so everything the glTF viewer grew -- framing, background
loading, the caption, screenshots, the settled capture, walking -- reaches every
format at once.  These check the join from the viewer's side: that the source
chooses the adapter, that the adapter's answers are the ones acted on, and that
what is true of a *model* is not quietly imposed on a *world*.
"""
import os

import pytest

from OpenGLContext.scenegraph.background import Background
from OpenGLContext.scenegraph.light import Light
from OpenGLContext.testing.paths import tests_root
from OpenGLContext.viewer import ViewerOptions
from OpenGLContext.viewer.adapters.gltf import GLTFAdapter
from OpenGLContext.viewer.adapters.vrml import VRMLAdapter
from OpenGLContext.viewer.sceneviewer import ViewerContext

WRLS = os.path.join(str(tests_root(__file__)), 'wrls')
GLTF_MODEL = os.path.join(WRLS, 'instanced_lattice.gltf')
VRML_WORLD = os.path.join(WRLS, '3shapes.wrl')
VRML_CAMERAS = os.path.join(WRLS, 'viewpoints.wrl')


class _Platform:
    """A view platform that records where it was aimed, without a window."""

    quaternion = None

    def setFrustum(self, fov, aspect, near, far):
        self.frustum = (fov, aspect, near, far)

    def setPosition(self, position):
        self.position = position

    def setOrientation(self, orientation):
        self.orientation = orientation


def _viewer(source, **named):
    """A viewer configured from options alone, ready to build a scenegraph."""
    viewer = ViewerContext.__new__(ViewerContext)
    viewer.options = ViewerOptions(source=source, **named)
    viewer.platform = _Platform()
    viewer.viewpoints = []
    viewer.cameraIndex = 0
    viewer._cameraNames = []
    viewer.modelTransform = None
    viewer._defaultModelRotation = (0, 1, 0, 0.0)
    viewer._animations = []
    viewer._animationNames = []
    viewer._animationIndex = 0
    viewer._animationPlaying = viewer.options.animate
    viewer._animationClock = 0.0
    viewer._animationLast = None
    viewer._player = None
    viewer.physicsWalking = False
    viewer.physicsPlatform = None
    viewer.triggerRedraw = lambda count=1: None
    viewer.prepareSource()
    return viewer


@pytest.fixture(scope='module')
def world():
    return VRMLAdapter().load(VRML_WORLD)


@pytest.fixture(scope='module')
def model():
    return GLTFAdapter().load(GLTF_MODEL)


class TestTheSourceChoosesTheAdapter:
    def test_a_model_gets_the_gltf_adapter(self):
        assert isinstance(_viewer(GLTF_MODEL).adapter, GLTFAdapter)

    def test_a_world_gets_the_vrml_adapter(self):
        assert isinstance(_viewer(VRML_WORLD).adapter, VRMLAdapter)

    def test_an_unopenable_source_is_refused_before_a_window_opens(self, tmp_path):
        picture = tmp_path / 'holiday.jpg'
        picture.write_bytes(b'not a scene')
        with pytest.raises(SystemExit):
            _viewer(str(picture))

    def test_the_format_can_be_named_when_the_source_does_not_say(self):
        """A URL that serves a model from ``/download`` has no suffix to read."""
        viewer = _viewer(VRML_WORLD, format='gltf')
        assert isinstance(viewer.adapter, GLTFAdapter)

    def test_an_unknown_format_name_is_refused(self):
        with pytest.raises(SystemExit):
            _viewer(VRML_WORLD, format='postscript')

    def test_loading_goes_through_the_adapter(self):
        """The viewer knows nothing about reading files; the adapter does."""
        viewer = _viewer(GLTF_MODEL)
        loaded = []

        class _Recording(GLTFAdapter):
            def load(self, source):
                loaded.append(source)
                return 'scene'

        viewer.adapter = _Recording()
        assert viewer.loadScene() == 'scene'
        assert loaded == [GLTF_MODEL]


class TestShowingAWorld:
    """A VRML world is authored complete; the viewer must not paint over it."""

    def test_it_becomes_a_real_scenegraph(self, world):
        viewer = _viewer(VRML_WORLD)
        viewer.buildScenegraph(world)
        assert viewer.sg.children
        assert viewer.radius > 0.0

    def test_the_worlds_own_backdrop_is_not_doubled(self, world):
        """Two bound Backgrounds would fight over which sky is drawn."""
        viewer = _viewer(VRML_WORLD)
        viewer.buildScenegraph(world)
        skies = _find(viewer.sg, Background)
        assert len(skies) == 1, 'the world brought its own'

    def test_a_world_that_lights_itself_is_not_re_lit(self, world):
        viewer = _viewer(VRML_WORLD, lights='auto')
        viewer.buildScenegraph(world)
        assert len(_find(viewer.sg, Light)) == 2, "the world's own two"

    def test_a_world_is_shown_where_it_was_authored(self, world):
        """Re-centring would move its ground plane out from under the avatar."""
        viewer = _viewer(VRML_WORLD)
        viewer.buildScenegraph(world)
        assert viewer.modelTransform.children[0] is world.group

    def test_the_camera_still_backs_off_to_see_it(self, world):
        viewer = _viewer(VRML_WORLD)
        viewer.buildScenegraph(world)
        assert viewer.platform.position[2] > world.radius

    def test_a_worlds_viewpoints_become_the_cameras(self):
        scene = VRMLAdapter().load(VRML_CAMERAS)
        viewer = _viewer(VRML_CAMERAS)
        viewer.buildScenegraph(scene)
        assert len(viewer.viewpoints) == 5
        assert viewer.resolveCamera('cam03') == 2

    def test_the_caption_names_the_world(self, world):
        viewer = _viewer(VRML_WORLD)
        viewer.buildScenegraph(world)
        assert '3shapes.wrl' in viewer.overlayText


class TestShowingAModel:
    """The glTF behaviour the world case must not have changed."""

    def test_a_model_with_no_backdrop_of_its_own_is_given_one(self, model):
        viewer = _viewer(GLTF_MODEL)
        viewer.buildScenegraph(model)
        assert len(_find(viewer.sg, Background)) == 1

    def test_a_model_is_moved_to_the_middle_of_the_frame(self, model):
        """Its origin is wherever the exporter left it."""
        viewer = _viewer(GLTF_MODEL, no_cameras=True)
        viewer.buildScenegraph(model)
        centring = viewer.modelTransform.children[0]
        assert centring is not model.group, 'wrapped in a centring transform'
        assert tuple(centring.translation) == pytest.approx(
            tuple(-v for v in model.center))


class TestStreamingFormats:
    """A source that is still arriving gets a say in every frame."""

    def test_a_static_scene_asks_for_no_extra_work(self):
        viewer = _viewer(GLTF_MODEL)
        assert viewer.advanceStreaming() is False

    def test_a_streaming_scene_is_stepped_against_the_viewer(self):
        seen = []

        class _Streaming(GLTFAdapter):
            def update(self, viewer):
                seen.append(viewer)
                return True

        viewer = _viewer(GLTF_MODEL)
        viewer.adapter = _Streaming()
        assert viewer.advanceStreaming() is True
        assert seen == [viewer]


def _find(node, kind, seen=None):
    """Every node of ``kind`` reachable from ``node``."""
    if seen is None:
        seen = set()
    if id(node) in seen:
        return []
    seen.add(id(node))
    found = [node] if isinstance(node, kind) else []
    for child in getattr(node, 'children', None) or ():
        found.extend(_find(child, kind, seen))
    return found
