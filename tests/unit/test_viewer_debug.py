"""What the developer overlay says about what is being viewed
(:mod:`OpenGLContext.viewer.debug`).

Every context already reports its frame rate, its renderer and where its camera
is.  A viewer can say more, and it is the more that answers the questions a
viewer actually raises: which adapter read this, how big the thing turned out to
be, which of its cameras is bound, and whether the avatar is walking.
"""

from OpenGLContext.viewer.debug import scene_provider


class _Viewer:
    source = '/models/Duck.glb'
    radius = 2.5
    viewpoints = ()
    cameraIndex = 0
    physicsWalking = False
    sceneLoaded = True
    _cameraNames = ()
    _animations = ()
    _animationNames = ()
    _animationIndex = 0
    _animationPlaying = False

    class adapter:
        name = 'gltf'


def rows(viewer):
    return dict(scene_provider(viewer)())


class TestWhatItReports:
    def test_it_names_the_source(self):
        assert rows(_Viewer())['source'] == 'Duck.glb'

    def test_it_names_the_adapter_that_read_it(self):
        """The one question a multi-format viewer raises that no other does."""
        assert rows(_Viewer())['format'] == 'gltf'

    def test_it_gives_the_size_the_framing_came_from(self):
        assert '2.5' in rows(_Viewer())['radius']

    def test_it_says_which_camera_is_bound(self):
        viewer = _Viewer()
        viewer.viewpoints = ('a', 'b', 'c')
        viewer._cameraNames = ('front', 'side', 'top')
        viewer.cameraIndex = 1
        assert rows(viewer)['camera'] == '2/3 side'

    def test_a_scene_with_no_cameras_says_so(self):
        assert rows(_Viewer())['camera'] == 'auto-framed'

    def test_it_says_how_you_are_moving(self):
        assert rows(_Viewer())['moving'] == 'free-fly'
        viewer = _Viewer()
        viewer.physicsWalking = True
        assert rows(viewer)['moving'] == 'walk'

    def test_an_animation_is_reported_when_there_is_one(self):
        viewer = _Viewer()
        viewer._animations = ('a',)
        viewer._animationNames = ('idle',)
        viewer._animationPlaying = True
        assert rows(viewer)['animation'] == '1/1 idle (playing)'

    def test_a_scene_with_no_animation_does_not_mention_it(self):
        assert 'animation' not in rows(_Viewer())

    def test_a_viewer_with_nothing_loaded_says_that_much(self):
        viewer = _Viewer()
        viewer.source = None
        viewer.sceneLoaded = False
        assert rows(viewer)['source'] == '(nothing loaded)'

    def test_it_never_raises_on_a_half_built_viewer(self):
        """The overlay is what you look at when things are going wrong."""
        class _Bare:
            pass
        assert isinstance(dict(scene_provider(_Bare())()), dict)
