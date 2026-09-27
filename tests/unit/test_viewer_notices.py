"""The viewer shows the copyright and licence notices a file carries.

``i`` raises them, and so does a Notices button on the menu when the scene has
any.  Every scene a viewer shows answers ``notices``: a glTF with what its
asset and its ``KHR_xmp_json_ld`` packets say, a VRML97 world with its
``WorldInfo``, anything else with an empty list.
"""
from OpenGLContext.loaders.notices import NONE, Notice
from OpenGLContext.scenegraph.basenodes import Shape, Sphere, WorldInfo, sceneGraph as SceneGraph
from OpenGLContext.ui.overlay import OverlayStack
from OpenGLContext.viewer import menu
from OpenGLContext.viewer.adapters.base import ViewerScene
from OpenGLContext.viewer.adapters.scenegraph import SceneGraphAdapter
from OpenGLContext.viewer.library import Entry, Library
from OpenGLContext.viewer.screens import NOTICES_NAME, ViewerScreensMixin
from OpenGLContext.viewer.sceneviewer import SceneViewerMixin


class _Host(ViewerScreensMixin):
    """A viewer with the window taken out, showing ``scene``."""

    def __init__(self, scene=None, source='model.glb'):
        self._overlays = OverlayStack()
        self.scene = scene
        self.source = source

    @property
    def overlays(self):
        return self._overlays

    def pushOverlay(self, panel):
        self._overlays.push(panel, viewport=(800, 600), metrics=None)
        return panel

    def viewerLibrary(self):
        return Library([Entry(name='Duck', source='Duck.glb')])

    def triggerRedraw(self, force=0):
        pass

    def OnQuit(self, event=None):
        pass


def text_of(panel):
    return str(panel.find('text').text)


STATUE = Notice(covers='athena_parthenos', title='Athena #3DST8',
                creator='Digitage', licence='CC-BY 4.0')


class TestTheScreen:
    def test_it_shows_every_notice_the_scene_carries(self):
        host = _Host(ViewerScene(group=None))
        host.scene.notices = [Notice(copyright='(c) The Builder'), STATUE]
        panel = host.showNotices()
        assert panel.name == NOTICES_NAME
        assert '(c) The Builder' in text_of(panel)
        assert 'Athena #3DST8' in text_of(panel)

    def test_a_scene_with_none_says_so(self):
        host = _Host(ViewerScene(group=None))
        assert text_of(host.showNotices()) == NONE

    def test_a_scene_from_elsewhere_that_answers_nothing_says_so(self):
        """A third party's scene object may not know the question."""
        host = _Host(object())
        assert text_of(host.showNotices()) == NONE

    def test_with_nothing_loaded_there_is_nothing_to_show(self):
        assert _Host(None, source=None).showNotices() is None

    def test_asking_twice_raises_the_one_already_up(self):
        host = _Host(ViewerScene(group=None))
        first = host.showNotices()
        assert host.showNotices() is first
        assert len(host.overlays.panels) == 1

    def test_it_closes(self):
        host = _Host(ViewerScene(group=None))
        host.showNotices().find('close').activate()
        assert host.overlays.top is None


class TestTheMenu:
    def test_a_scene_with_notices_offers_them(self):
        scene = ViewerScene(group=None)
        scene.notices = [STATUE]
        host = _Host(scene)
        host.showMenu().find('notices').activate()
        assert host.overlays.top.name == NOTICES_NAME
        assert len(host.overlays.panels) == 1

    def test_a_scene_without_them_does_not(self):
        host = _Host(ViewerScene(group=None))
        assert host.showMenu().find('notices') is None

    def test_the_button_calls_what_it_was_given(self):
        rang = []
        menu.main_menu(on_notices=lambda: rang.append(True)).find('notices').activate()
        assert rang == [True]


class TestEachViewsMenu:
    """The menu a view's name opens offers them, in the viewer only."""

    def test_a_scene_with_notices_offers_them(self):
        scene = ViewerScene(group=None)
        scene.notices = [STATUE]
        host = _Host(scene)
        [item] = host.viewMenuItems(view=None)
        assert str(item.text) == menu.NOTICES_LABEL
        item.on_activate(item)
        assert host.overlays.top.name == NOTICES_NAME

    def test_a_scene_without_them_adds_nothing(self):
        assert _Host(ViewerScene(group=None)).viewMenuItems(view=None) == []

    def test_it_keeps_what_the_window_underneath_adds(self):
        class _Below:
            def viewMenuItems(self, view):
                return ['from below']

        class _Stacked(_Host, _Below):
            pass

        scene = ViewerScene(group=None)
        scene.notices = [STATUE]
        items = _Stacked(scene).viewMenuItems(view=None)
        assert items[0] == 'from below' and len(items) == 2


class TestTheKey:
    def test_i_raises_the_notices(self):
        bound = {binding.name: binding.method for binding in SceneViewerMixin.viewerKeys}
        assert bound['i'] == 'showNotices'


class TestAVRMLWorld:
    def test_its_world_info_is_its_notice(self):
        graph = SceneGraph(children=[
            WorldInfo(title='The Valley', info=['(c) 2026 The Surveyor', 'CC-BY 4.0']),
            Shape(geometry=Sphere()),
        ])
        [notice] = SceneGraphAdapter().sceneFrom(graph).notices
        assert notice == Notice(title='The Valley',
                                copyright='(c) 2026 The Surveyor\nCC-BY 4.0')

    def test_a_world_with_none_has_no_notices(self):
        graph = SceneGraph(children=[Shape(geometry=Sphere())])
        assert SceneGraphAdapter().sceneFrom(graph).notices == []

    def test_an_empty_world_info_is_no_notice(self):
        graph = SceneGraph(children=[WorldInfo()])
        assert SceneGraphAdapter().sceneFrom(graph).notices == []
