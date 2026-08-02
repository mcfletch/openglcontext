"""The viewer as a program, not a command line
(:mod:`OpenGLContext.viewer.sceneviewer`).

Opening a second scene into a running window, the screens that get you there,
and the keys that raise them.  A scene swap is the thing that makes a library
worth having, so it is checked here rather than left to a live run: a new source
means a new adapter, a new scenegraph, new framing, and an avatar that has to be
put somewhere in it.
"""
import os

import pytest

from OpenGLContext.testing.paths import tests_root
from OpenGLContext.viewer import ViewerOptions
from OpenGLContext.viewer.adapters.gltf import GLTFAdapter
from OpenGLContext.viewer.adapters.vrml import VRMLAdapter
from OpenGLContext.viewer.library import Entry, Library, MODELS
from OpenGLContext.viewer.sceneviewer import NO_MODIFIERS, ViewerContext

WRLS = os.path.join(str(tests_root(__file__)), 'wrls')
GLTF_MODEL = os.path.join(WRLS, 'instanced_lattice.gltf')
VRML_WORLD = os.path.join(WRLS, '3shapes.wrl')


class _Platform:
    quaternion = None

    def setFrustum(self, *a):
        self.frustum = a

    def setPosition(self, p):
        self.position = p

    def setOrientation(self, o):
        self.orientation = o


def _viewer(source=None, **named):
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
    viewer._animationPlaying = True
    viewer._animationClock = 0.0
    viewer._animationLast = None
    viewer._player = None
    viewer.physicsWalking = False
    viewer.physicsPlatform = None
    viewer.sceneLoaded = False
    viewer.triggerRedraw = lambda count=1: None
    viewer.requested = []
    viewer.requestScene = lambda produce, label='': viewer.requested.append(
        (produce, label))
    return viewer


class TestOpeningSomethingElse:
    def test_a_new_source_gets_the_adapter_for_it(self):
        """Opening a world from a screen full of glTF has to change format."""
        viewer = _viewer(GLTF_MODEL)
        viewer.prepareSource()
        assert isinstance(viewer.adapter, GLTFAdapter)
        viewer.openSource(VRML_WORLD)
        assert isinstance(viewer.adapter, VRMLAdapter)
        assert viewer.source == VRML_WORLD

    def test_the_load_happens_in_the_background(self):
        """The window keeps drawing the old scene through the download."""
        viewer = _viewer(GLTF_MODEL)
        viewer.prepareSource()
        viewer.openSource(VRML_WORLD)
        assert len(viewer.requested) == 1
        produce, label = viewer.requested[0]
        assert '3shapes.wrl' in label
        assert produce().radius > 0, 'and the producer really loads it'

    def test_a_source_that_cannot_be_opened_says_so_and_changes_nothing(self):
        viewer = _viewer(GLTF_MODEL)
        viewer.prepareSource()
        assert viewer.openSource('holiday.jpg') is False
        assert viewer.source == GLTF_MODEL
        assert viewer.overlayError is True
        assert viewer.requested == []

    def test_an_entrys_own_options_are_applied(self):
        """The roster records how each model has to be shown; opening it uses that."""
        viewer = _viewer(GLTF_MODEL)
        viewer.prepareSource()
        viewer.openEntry(Entry(name='X', source=VRML_WORLD, category=MODELS,
                               options={'yaw': 1.25, 'background': 'none'}))
        assert viewer.options.yaw == pytest.approx(1.25)
        assert viewer.options.background == 'none'
        assert viewer.source == VRML_WORLD

    def test_an_entry_option_that_is_not_a_viewer_option_is_refused(self):
        """A typo in a roster must not silently do nothing for ever."""
        viewer = _viewer(GLTF_MODEL)
        viewer.prepareSource()
        with pytest.raises(TypeError):
            viewer.openEntry(Entry(name='X', source=VRML_WORLD,
                                   options={'zoom': 2}))

    def test_options_from_one_entry_do_not_stick_to_the_next(self):
        """Browsing model to model must not accumulate the last one's framing."""
        viewer = _viewer(GLTF_MODEL)
        viewer.prepareSource()
        plain = viewer.options.background
        viewer.openEntry(Entry(name='A', source=VRML_WORLD,
                               options={'background': 'none'}))
        viewer.openEntry(Entry(name='B', source=VRML_WORLD))
        assert viewer.options.background == plain


class TestTheLibraryItOffers:
    def test_there_is_one_by_default(self):
        assert _viewer().viewerLibrary().entries

    def test_an_application_can_supply_its_own(self):
        class _Curated(ViewerContext):
            def viewerLibrary(self):
                return Library([Entry(name='Only', source='only.glb')])

        viewer = _Curated.__new__(_Curated)
        assert [e.name for e in viewer.viewerLibrary().entries] == ['Only']


class TestStartingWithNothingToShow:
    def test_no_source_is_a_menu_rather_than_an_exit(self):
        """The whole point: ``oglc-view`` on its own is a program."""
        viewer = _viewer(None)
        viewer.prepareSource()
        assert viewer.source is None
        assert viewer.adapter is not None

    def test_it_still_exits_when_told_to_open_something_missing(self, monkeypatch):
        monkeypatch.delenv('GLTF', raising=False)
        viewer = _viewer('/no/such/model.glb')
        with pytest.raises(SystemExit):
            viewer.prepareSource()

    def test_nothing_is_requested_when_there_is_nothing_to_load(self):
        viewer = _viewer(None)
        viewer.prepareSource()
        viewer.requestInitialScene()
        assert viewer.requested == []


class TestTheMovementItDeclares:
    """The modes are the viewer's navigation vocabulary, not a by-product.

    They used to be declared only as a side effect of building a physics avatar,
    so a viewer in free-fly -- which is the default -- had none: the controls
    page found nothing to offer and silently did not open, and ``m`` had nothing
    to cycle.
    """

    def _walker(self):
        viewer = _viewer(GLTF_MODEL)
        viewer.prepareSource()
        viewer.contextDefinition = _Definition()
        viewer.movementManager = None
        viewer.settleCapture = None
        viewer.sg = object()
        viewer.physicsYaw = 0.0
        viewer.setupPhysics = lambda enable=False: False
        return viewer

    def test_a_viewer_declares_them_before_anything_is_walked(self):
        viewer = self._walker()
        viewer.setupWalking()
        assert [str(mode.name) for mode in viewer.contextDefinition.movementModes] \
            == ['walk', 'fly']

    def test_a_host_that_declared_its_own_keeps_them(self):
        """A game embedding the viewer has its own vocabulary."""
        viewer = self._walker()
        mine = ['not-really-a-mode']
        viewer.contextDefinition.movementModes = mine
        viewer.setupWalking()
        assert viewer.contextDefinition.movementModes is mine

    def test_a_capture_declares_nothing(self):
        """One deterministic frame; nobody is going to move."""
        viewer = self._walker()
        viewer.settleCapture = object()
        viewer.setupWalking()
        assert not viewer.contextDefinition.movementModes


class _Definition:
    """The little of a ContextDefinition the declaration touches."""

    movementModes = ()
    movementMode = None


class TestSteppingThroughTheShelf:
    """PageUp/PageDown walk the list you chose from.

    Having picked something out of a category, the obvious next thing to want
    is the one after it -- without going back to the shelf, finding your place
    and clicking again. It steps the *category* the entry came from, because
    that is the list that was being browsed.

    Only once something has been chosen from the shelf: a viewer opened on a
    file named on the command line has no list to step, and those keys keep
    their older meaning of cycling the scene's own cameras.
    """

    SHELF = Library([
        Entry(name='A', source=VRML_WORLD, category=MODELS),
        Entry(name='B', source=VRML_WORLD, category=MODELS),
        Entry(name='C', source=VRML_WORLD, category=MODELS),
        Entry(name='W', source=VRML_WORLD, category='Worlds'),
    ])

    def _viewer(self):
        viewer = _viewer(GLTF_MODEL)
        viewer.prepareSource()
        viewer._library = self.SHELF
        viewer.cycled = []
        viewer.cycleViewpoint = viewer.cycled.append
        return viewer

    def test_nothing_chosen_yet_steps_nothing(self):
        """PageUp/PageDown are the cameras; this is a key of its own."""
        viewer = self._viewer()
        viewer.stepLibrary(1)
        assert viewer.cycled == [], 'it moved the camera instead'
        assert viewer.requested == []

    def test_it_opens_the_next_one_along(self):
        viewer = self._viewer()
        viewer.openEntry(self.SHELF.find('A'))
        viewer.requested.clear()
        viewer.stepLibrary(1)
        assert viewer.libraryEntry.name == 'B'
        assert viewer.requested, 'it did not actually load anything'

    def test_it_goes_back_too(self):
        viewer = self._viewer()
        viewer.openEntry(self.SHELF.find('B'))
        viewer.stepLibrary(-1)
        assert viewer.libraryEntry.name == 'A'

    def test_it_wraps_at_the_end_of_the_list(self):
        viewer = self._viewer()
        viewer.openEntry(self.SHELF.find('C'))
        viewer.stepLibrary(1)
        assert viewer.libraryEntry.name == 'A'

    def test_it_stays_in_the_category_that_was_browsed(self):
        viewer = self._viewer()
        viewer.openEntry(self.SHELF.find('C'))
        viewer.stepLibrary(1)
        assert viewer.libraryEntry.category == MODELS

    def test_a_category_of_one_steps_to_itself(self):
        viewer = self._viewer()
        viewer.openEntry(self.SHELF.find('W'))
        viewer.stepLibrary(1)
        assert viewer.libraryEntry.name == 'W'

    def test_opening_a_plain_source_forgets_the_list(self):
        """Typing an address is leaving the shelf behind."""
        viewer = self._viewer()
        viewer.openEntry(self.SHELF.find('A'))
        viewer.requested.clear()
        viewer.openSource(VRML_WORLD)
        assert viewer.libraryEntry is None
        viewer.requested.clear()
        viewer.stepLibrary(1)
        assert viewer.requested == []

    def test_the_keys_are_bound_to_it(self):
        from OpenGLContext.viewer.sceneviewer import SceneViewerMixin
        assert hasattr(SceneViewerMixin, 'nextInLibrary')
        assert hasattr(SceneViewerMixin, 'previousInLibrary')

    def test_it_is_on_ctrl_and_the_cameras_keep_the_plain_key(self):
        """A world's own cameras are what PageUp/PageDown mean inside it.

        Which key runs which method is checked by driving real events through a
        real manager, in :mod:`tests.unit.test_viewer_keys`; this is only that
        the two live on the same key and are told apart by Ctrl.
        """
        from OpenGLContext.viewer.sceneviewer import CONTROL, SceneViewerMixin
        bound = {(binding.name, binding.modifiers): binding.method
                 for binding in SceneViewerMixin.viewerKeys}
        assert bound[('<pagedown>', CONTROL)] == 'nextInLibrary'
        assert bound[('<pageup>', CONTROL)] == 'previousInLibrary'
        assert bound[('<pagedown>', NO_MODIFIERS)] == 'nextCamera'
        assert bound[('<pageup>', NO_MODIFIERS)] == 'previousCamera'

