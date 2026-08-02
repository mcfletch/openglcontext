"""The viewer's screens on the context (:mod:`OpenGLContext.viewer.screens`).

Which key raises what, that pressing it twice raises the one already up rather
than stacking another over it, and that choosing something in the library
actually opens it.  The panels themselves are checked in
``test_viewer_menu.py``; this is the wiring between them and a running viewer.
"""

from OpenGLContext.viewer import menu
from OpenGLContext.viewer.library import Entry, Library
from OpenGLContext.viewer.screens import ViewerScreensMixin


class _Host(ViewerScreensMixin):
    """A viewer with the window taken out: an overlay stack and a library."""

    def __init__(self, library=None, source='model.glb'):
        from OpenGLContext.ui.overlay import OverlayStack
        self._overlays = OverlayStack()
        self._library = library if library is not None else Library([
            Entry(name='Duck', source='Duck.glb'),
        ])
        self.source = source
        self.opened = []
        self.sources = []
        self.openable = True
        self.quit = 0
        self.handlers = []

    @property
    def overlays(self):
        return self._overlays

    def pushOverlay(self, panel):
        self._overlays.push(panel, viewport=(800, 600), metrics=None)
        return panel

    def viewerLibrary(self):
        return self._library

    def openEntry(self, entry):
        self.opened.append(entry)
        return self.openable

    def openSource(self, source):
        self.sources.append(source)
        return self.openable

    def addEventHandler(self, kind, name=None, function=None, **named):
        self.handlers.append((kind, name, function))

    def triggerRedraw(self, force=0):
        pass

    def OnQuit(self, event=None):
        self.quit += 1

    def removeHUDLayer(self, layer):
        pass


class TestTheKeys:
    def test_the_screens_are_on_keys_that_produce_no_character(self):
        """A function key raises no keypress, so it must be bound key-down."""
        host = _Host()
        host.setupScreens()
        bound = {name: kind for kind, name, _fn in host.handlers}
        for key in ViewerScreensMixin.LIBRARY_KEY, ViewerScreensMixin.SETTINGS_KEY:
            assert bound.get(key) == 'keyboard', key

    def test_the_library_key_is_bound_to_the_library(self):
        host = _Host()
        host.setupScreens()
        assert ('keyboard', ViewerScreensMixin.LIBRARY_KEY,
                host.showLibrary) in host.handlers

    def test_a_viewer_may_decline_a_key(self):
        class _Quiet(_Host):
            LIBRARY_KEY = ''
        host = _Quiet()
        host.setupScreens()
        assert not [h for h in host.handlers if h[1] == '']


class TestRaisingAScreen:
    def test_the_menu_goes_up(self):
        host = _Host()
        host.showMenu()
        assert host.overlays.top.name == menu.MENU_NAME

    def test_asking_twice_raises_the_one_already_up(self):
        """Otherwise a second press buries the first behind a copy of itself."""
        host = _Host()
        first = host.showMenu()
        assert host.showMenu() is first
        assert len(host.overlays.panels) == 1

    def test_the_library_goes_up(self):
        host = _Host()
        host.showLibrary()
        assert host.overlays.top.name == menu.BROWSE_NAME

    def test_choosing_something_opens_it_and_closes_the_screen(self):
        host = _Host()
        panel = host.showLibrary()
        panel.find('entry').activate()
        assert [entry.name for entry in host.opened] == ['Duck']
        assert panel.closed

    def test_choosing_something_leaves_nothing_on_screen(self):
        """Launching a world means seeing the world, not the launch menu.

        Closing the browse screen ran its Cancel handler, and Cancel with
        nothing yet open puts the menu back -- so opening a model from the
        library left the menu over the top of it.
        """
        host = _Host(source=None)
        host.showMenu()
        panel = host.showLibrary()
        panel.find('entry').activate()
        assert host.overlays.top is None, [p.name for p in host.overlays.panels]

    def test_a_screen_replaces_the_menu_rather_than_covering_it(self):
        """Two panels up means the one underneath showing through the one above."""
        host = _Host(source=None)
        host.showMenu()
        host.showLibrary()
        assert len(host.overlays.panels) == 1
        assert host.overlays.top.name == menu.BROWSE_NAME

    def test_cancelling_the_library_goes_back_to_the_menu_when_there_is_one(self):
        """Browse was reached from the menu, so Cancel returns to it."""
        host = _Host(source=None)
        host.showMenu()
        host.showLibrary()
        host.overlays.top.close()
        assert host.overlays.top.name == menu.MENU_NAME
        assert len(host.overlays.panels) == 1

    def test_cancelling_goes_back_to_the_scene_when_there_is_one(self):
        host = _Host(source='model.glb')
        host.showLibrary()
        host.overlays.top.close()
        assert host.overlays.top is None

    def test_quitting_from_the_menu_quits(self):
        host = _Host()
        host.showMenu().find('quit').activate()
        assert host.quit == 1


class TestOpeningATypedAddress:
    def test_the_menu_opens_what_was_typed(self):
        host = _Host(source=None)
        panel = host.showMenu()
        panel.find('url').value = 'https://example.com/model.glb'
        panel.find('open-url').activate()
        assert host.sources == ['https://example.com/model.glb']

    def test_the_menu_goes_away_when_it_opens(self):
        host = _Host(source=None)
        panel = host.showMenu()
        panel.find('url').value = 'https://example.com/model.glb'
        panel.find('open-url').activate()
        assert host.overlays.top is None

    def test_an_address_that_will_not_open_leaves_the_menu_up(self):
        """Somewhere to correct the typo, rather than an empty window."""
        host = _Host(source=None)
        host.openable = False
        panel = host.showMenu()
        panel.find('url').value = 'not-a-model.jpg'
        panel.find('open-url').activate()
        assert host.overlays.top is panel


class TestEscape:
    """Escape must never throw a loaded world away without asking."""

    def test_it_raises_the_menu_rather_than_quitting(self):
        host = _Host(source='model.glb')
        host.OnEscape()
        assert host.overlays.top.name == menu.MENU_NAME
        assert host.quit == 0

    def test_the_menu_it_raises_can_be_resumed_out_of(self):
        host = _Host(source='model.glb')
        panel = host.OnEscape()
        panel.find('resume').activate()
        assert host.overlays.top is None
        assert host.quit == 0

    def test_quitting_is_still_one_click_away(self):
        host = _Host(source='model.glb')
        host.OnEscape().find('quit').activate()
        assert host.quit == 1

    def test_with_nothing_loaded_the_menu_has_nothing_to_resume(self):
        host = _Host(source=None)
        panel = host.OnEscape()
        assert panel.find('resume') is None


class TestStartingWithNothingToShow:
    def test_a_host_that_has_its_own_scenes_is_not_offered_the_menu(self):
        """A catalogue browser has no single ``source`` and is not empty.

        The question is whether there is anything to show, not whether one file
        was named -- ``oglc-gltf-demo`` opened on its launch menu until it was
        asked the right one.
        """
        class _Catalogue(_Host):
            def hasSceneToShow(self):
                return True

        host = _Catalogue(source=None)
        host.setupScreens()
        assert host.overlays.top is None

    def test_a_viewer_with_no_source_opens_the_menu(self):
        host = _Host(source=None)
        host.setupScreens()
        assert host.overlays.top.name == menu.MENU_NAME

    def test_a_viewer_with_a_source_does_not(self):
        host = _Host(source='model.glb')
        host.setupScreens()
        assert host.overlays.top is None

    def test_the_menu_says_how_much_there_is_to_open(self):
        host = _Host(source=None)
        host.setupScreens()
        assert '1' in host.overlays.top.find('subtitle').text

    def test_that_menu_cannot_be_escaped_out_of_into_nothing(self):
        host = _Host(source=None)
        host.setupScreens()
        assert not host.overlays.top.closeOnEscape
