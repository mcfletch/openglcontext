"""Embedding the viewer, with no command line anywhere
(:mod:`OpenGLContext.viewer.sceneviewer`).

This is the point of the package: an application says what it wants with a
:class:`ViewerOptions` and gets a working viewer, without building an
``argparse`` namespace and without subclassing a console script.  A real glTF is
loaded and a real scenegraph built -- what is stubbed is only the view platform,
since aiming a camera needs no window.

The GL half (a live context actually rendering these scenes) is covered by
``tests/unit/test_gltf_view_physics_toggle.py`` and the visual suite.
"""
import os

import pytest

from OpenGLContext.scenegraph.background import Background
from OpenGLContext.scenegraph.light import Light
from OpenGLContext.testing.paths import tests_root
from OpenGLContext.viewer import ViewerOptions
from OpenGLContext.viewer.sceneviewer import ViewerContext, SceneViewerMixin
from OpenGLContext.viewer.source import load_gltf_source

MODEL = os.path.join(str(tests_root(__file__)), 'wrls', 'instanced_lattice.gltf')


class _Platform:
    """A view platform that records where it was aimed, without a window."""

    quaternion = None

    def setFrustum(self, fov, aspect, near, far):
        self.frustum = (fov, aspect, near, far)

    def setPosition(self, position):
        self.position = position

    def setOrientation(self, orientation):
        self.orientation = orientation


def _viewer(**named):
    """A viewer configured from options alone, ready to build a scenegraph."""
    viewer = ViewerContext.__new__(ViewerContext)
    viewer.options = ViewerOptions(source=MODEL, **named)
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
    return viewer


@pytest.fixture(scope='module')
def scene():
    return load_gltf_source(MODEL)


class TestConfiguredByOptionsAlone:
    def test_a_subclass_needs_nothing_but_options(self):
        """The documented way to embed one."""
        class MyViewer(ViewerContext):
            options = ViewerOptions(source='model.glb', physics=True)

        assert MyViewer.options.source == 'model.glb'
        assert MyViewer.options.physics is True
        assert isinstance(MyViewer.options, ViewerOptions)

    def test_the_component_carries_workable_defaults(self):
        assert isinstance(SceneViewerMixin.options, ViewerOptions)
        assert SceneViewerMixin.options.animate is True

    def test_the_source_is_resolved_from_the_options(self):
        viewer = _viewer()
        viewer.prepareSource()
        assert viewer.source == MODEL

    def test_the_source_may_come_from_the_environment(self, monkeypatch):
        monkeypatch.setenv('GLTF', MODEL)
        viewer = _viewer()
        viewer.options.source = None
        viewer.prepareSource()
        assert viewer.source == MODEL

    def test_nowhere_to_get_a_model_from_is_a_menu(self, monkeypatch):
        """A viewer with nothing named opens its shelf, not a usage message."""
        monkeypatch.delenv('GLTF', raising=False)
        viewer = _viewer()
        viewer.options.source = None
        viewer.prepareSource()
        assert viewer.source is None

    def test_a_source_that_was_named_and_is_missing_is_fatal(self, monkeypatch):
        """A typo must be answered, not shown as an empty window."""
        monkeypatch.delenv('GLTF', raising=False)
        viewer = _viewer()
        viewer.options.source = '/no/such/model.glb'
        with pytest.raises(SystemExit):
            viewer.prepareSource()


class TestBuildingAScene:
    def test_a_real_model_becomes_a_real_scenegraph(self, scene):
        viewer = _viewer()
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        assert viewer.sg is not None
        assert viewer.sg.children
        assert viewer.radius > 0.0

    def test_a_model_with_no_lights_of_its_own_is_given_some(self, scene):
        viewer = _viewer(lights='auto')
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        lit = [child for child in viewer.sg.children if isinstance(child, Light)]
        assert lit, 'the model would have been rendered in the dark'

    def test_the_light_rig_can_be_refused(self, scene):
        viewer = _viewer(lights='off')
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        assert not [c for c in viewer.sg.children if isinstance(c, Light)]

    def test_a_backdrop_is_added_by_default(self, scene):
        viewer = _viewer()
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        assert [c for c in viewer.sg.children if isinstance(c, Background)]

    def test_a_scene_can_be_shown_against_nothing(self, scene):
        viewer = _viewer(background='none')
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        assert not [c for c in viewer.sg.children if isinstance(c, Background)]

    def test_the_camera_is_aimed_at_the_model(self, scene):
        viewer = _viewer(no_cameras=True)
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        assert viewer.platform.position[2] > 0.0, 'backed off to see the model'
        assert viewer.platform.frustum[2] < viewer.platform.frustum[3]

    def test_building_again_swaps_the_model(self, scene):
        """A catalogue browser relies on this; the previous scene must go."""
        viewer = _viewer()
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        first = viewer.sg
        viewer.buildScenegraph(scene)
        assert viewer.sg is not first

    def test_the_caption_names_what_is_loaded(self, scene):
        viewer = _viewer()
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        assert 'instanced_lattice.gltf' in viewer.overlayText

    def test_the_exposure_the_renderer_reads_is_published(self, scene):
        viewer = _viewer(background='sky')
        viewer.source = MODEL
        viewer.buildScenegraph(scene)
        assert viewer.gltf_exposure == pytest.approx(1.0)
        assert viewer.gltf_scene_ambient == pytest.approx(0.0)


class TestTheMixinsComposeCleanly:
    """A mix-in must not quietly shadow something the context already has.

    ``ScreenMixin`` gives every context ``overlayFontSize()``; a viewer mix-in
    that declared ``overlayFontSize = 16`` replaced that method with an integer
    and the whole render died on the first frame, in a traceback that named
    neither mix-in.  So the composition is asserted rather than discovered.
    """

    #: Names the viewing component deliberately overrides, and why.
    DELIBERATE = {
        'OnInit', 'OnIdle', 'OnShutdown', 'SwapBuffers',      # the frame
        'setupCallbacks',
        'getNavigationPlatform',        # walking drives the avatar, not the camera
        'onPhysicsModeChanged',         # the caption names the mode in force
        'physicsSpawnViewpoints',       # the model's cameras are curated spawns
        'options',                      # the component's own configuration
        'setMovementManager',           # sizes free-fly stepping to the scene
        'physicsAvatarScale',           # a metric world gets a person, not a giant
    }

    def _declared(self, klass):
        return {name for name in vars(klass) if not name.startswith('__')}

    def test_no_viewer_mix_in_shadows_a_context_member_by_accident(self):
        from OpenGLContext.viewer.asyncscene import AsyncSceneMixin
        from OpenGLContext.viewer.capture import SettleCaptureMixin
        from OpenGLContext.viewer.sceneviewer import _Base
        from OpenGLContext.viewer.caption import CaptionMixin

        inherited = set()
        for klass in _Base.__mro__:
            inherited |= self._declared(klass)
        for mixin in (AsyncSceneMixin, CaptionMixin,
                      SettleCaptureMixin, SceneViewerMixin):
            clashes = self._declared(mixin) & inherited - self.DELIBERATE
            assert not clashes, '%s shadows %s' % (mixin.__name__, sorted(clashes))

    def test_the_caption_is_sized_by_the_interface_scale_like_everything_else(self):
        """It used to carry a font size of its own, which no setting reached."""
        viewer = _viewer()
        assert callable(viewer.overlayFontSize)
        assert not hasattr(ViewerContext, 'captionFontSize')


class TestTheOverridableSeams:
    def test_a_host_may_produce_scenes_of_its_own(self, scene):
        """A catalogue browser has no single source and loads by name instead."""
        class _Catalogue(ViewerContext):
            def prepareSource(self):
                self.source = 'catalogue'

            def loadScene(self):
                return scene

        viewer = _Catalogue.__new__(_Catalogue)
        viewer.options = ViewerOptions()
        viewer.prepareSource()
        assert viewer.source == 'catalogue'
        assert viewer.loadScene() is scene

    def test_walking_is_available_on_the_component(self):
        """It comes from the context, not from the viewer."""
        from OpenGLContext.move.physicswalk import PhysicsWalkMixin
        assert issubclass(ViewerContext, PhysicsWalkMixin)
        for seam in ('enablePhysics', 'buildPhysicsWorld', 'spawnAvatar',
                     'moveAvatarToViewpoint', 'stepPhysics'):
            assert hasattr(ViewerContext, seam), seam

    def test_the_model_supplies_the_spawn_viewpoints(self):
        viewer = _viewer()
        assert viewer.physicsSpawnViewpoints() == ()
        viewer.viewpoints = ['a', 'b', 'c']
        viewer.cameraIndex = 1
        assert viewer.physicsSpawnViewpoints() == ['b', 'c', 'a'], 'selected first'
