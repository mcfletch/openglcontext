"""De-registering an event callback, and what "still registered" means.

``EventManager.registerCallback`` allows one receiver per key, so it removes
whatever was there before registering.  It then checks that nothing was left --
a check worth having, because a handler that survives means a *second* context's
key press reaching a first context's method.

What it must not count is a **tombstone**: an entry whose weak reference has
died.  That is not a registered callback, it is bookkeeping pydispatch has not
yet swept, and counting it turns an ordinary second window into an
``AssertionError`` raised from a constructor.
"""

import gc
import sys

import pytest
from pydispatch import dispatcher

from OpenGLContext import plugins
from OpenGLContext.events.keyboardevents import KeyboardEventManager

#: The backend that renders on no window here -- a WGL pbuffer on Windows, EGL
#: elsewhere.  Both are registered everywhere, since which one a machine can
#: actually create is a question its answer already gives.
OFFSCREEN_BACKEND = (
    'wgl' if sys.platform.startswith(('win32', 'cygwin')) else 'egl'
)


class _Handler:
    """Stands where a Context stands: one method bound to two keys.

    ``Context`` does exactly this -- F2 and Alt+S both call
    ``requestScreenshot`` -- and it is what produces the tombstone, because
    pydispatch keeps one back-reference per receiver and de-registering either
    key removes it.
    """

    def __init__(self, seen):
        self.seen = seen

    def screenshot(self, event=None):
        self.seen.append(self)


FIRST = ('<f2>', 1, (False, False, False))
SECOND = ('s', 1, (False, False, True))


@pytest.fixture(autouse=True)
def clean_signals():
    """Leave the two keys with no handlers and no tombstones.

    Disconnecting the live ones is not enough: a test here *makes* a tombstone,
    and leaving it would seed the next one.
    """

    def clear():
        for key in (FIRST, SECOND):
            metaKey = (KeyboardEventManager.type, 0, key)
            entries = dispatcher.getReceivers(sender=None, signal=metaKey)
            for receiver in list(dispatcher.liveReceivers(entries)):
                dispatcher.disconnect(receiver, signal=metaKey, sender=None)
            try:
                entries[:] = []
            except TypeError:              # an empty tuple, nothing to clear
                pass

    clear()
    yield
    clear()


def _register(handler, key):
    """Register through the base-class entry point the contexts reach.

    ``KeyboardEventManager`` takes the key apart into name/state/modifiers; this
    passes the assembled key, which is what ``registerCallback`` builds and what
    ``_removeCurrentCallbacks`` is given.
    """
    name, state, modifiers = key
    KeyboardEventManager().registerCallback(
        name=name, state=state, modifiers=modifiers,
        function=getattr(handler, 'screenshot', None),
    )


def _leave_a_tombstone(manager, key, other):
    """Put the connections table into the state a collected context leaves it in.

    ``raw 1, live 0``: an entry whose weak reference has died and which
    pydispatch has not swept.

    Getting there needs only what ``Context`` does.  One bound method is bound
    to two keys -- F2 and Alt+S both call ``requestScreenshot`` -- and pydispatch
    keeps *one* back-reference per receiver, so de-registering either key takes
    it away.  When the object is then collected, the death callback finds no
    back-reference, removes nothing, and the surviving key keeps a dead entry.
    """
    doomed = _Handler([])
    for one in (key, other):
        name, state, modifiers = one
        manager.registerCallback(
            name=name, state=state, modifiers=modifiers, function=doomed.screenshot
        )
    name, state, modifiers = other
    manager.registerCallback(
        name=name, state=state, modifiers=modifiers, function=None
    )
    del doomed
    gc.collect()

    metaKey = (KeyboardEventManager.type, 0, key)
    raw = dispatcher.getReceivers(sender=None, signal=metaKey)
    live = list(dispatcher.liveReceivers(raw))
    assert raw and not live, (len(raw), len(live))


class TestATombstoneIsNotARegisteredCallback:
    def test_a_dead_entry_does_not_read_as_a_registered_handler(self):
        """``_removeCurrentCallbacks`` walks *live* receivers, so it correctly
        disconnects nothing -- and must not then report that de-registration
        failed."""
        manager = KeyboardEventManager()
        _leave_a_tombstone(manager, SECOND, FIRST)
        manager._removeCurrentCallbacks(SECOND, node=None)

    def test_a_second_context_can_bind_a_key_the_first_one_held(self):
        manager = KeyboardEventManager()
        _leave_a_tombstone(manager, SECOND, FIRST)
        second = _Handler([])
        _register(second, SECOND)

        metaKey = (KeyboardEventManager.type, 0, SECOND)
        live = list(
            dispatcher.liveReceivers(
                dispatcher.getReceivers(sender=None, signal=metaKey)
            )
        )
        assert len(live) == 1
        assert live[0].__self__ is second

class TestTwoContextsInSequence:
    """The failure this covers arrives as an ``AssertionError`` out of a
    constructor, a long way from the first context that caused it."""

    def test_a_context_can_be_built_after_another_has_gone(self):
        """Through the offscreen backend, which is a whole context per call.

        The windowed backends share one GLFW window across the suite, so a
        second *context* is what this needs and the offscreen one is where a
        test can have it.  Which of the two that is depends on the machine, so
        the registry is asked rather than a module named -- and a backend whose
        bindings this platform cannot load says so at the import.
        """
        pytest.importorskip('glfw')
        from OpenGLContext.testing.glcontext import gl_available

        if not gl_available():
            pytest.skip('no GL context can be created in this process')
        try:
            offscreen = plugins.Context.match(OFFSCREEN_BACKEND).load()
        except ImportError as error:
            pytest.skip('no %s bindings here: %s' % (OFFSCREEN_BACKEND, error))

        try:
            first = offscreen(size=(32, 32))
        except RuntimeError as error:
            pytest.skip('no offscreen context available here: %s' % (error,))
        first.close()
        del first
        gc.collect()

        second = offscreen(size=(32, 32))
        try:
            assert second.contextDefinition is not None
        finally:
            second.close()
