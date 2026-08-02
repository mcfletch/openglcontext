"""An application's own binding beats the default for the same key.

``setupCallbacks`` is where a context binds what *it* wants a key to do;
``setupDefaultEventCallbacks`` is where the framework binds what a key does when
nobody said otherwise. Only one handler can hold a key -- registering a second
for the same (name, state, modifiers) replaces the first -- so the order the two
run in decides which wins, and the defaults ran last.

The viewer binds PageDown to its own camera cycling, and
``Context.setupDefaultEventCallbacks`` binds the same key to
``OnNextViewpoint``. The application asked, the framework overruled it, and the
key silently did the other thing.
"""
import pytest

from OpenGLContext.context import Context


class _Bindings:
    """Records every registration, in the order it happened."""

    def __init__(self):
        self.order = []

    def addEventHandler(self, kind, **named):
        # The real registry keys on all three: Ctrl+PageDown and PageDown are
        # different bindings of the same key name.
        key = (named.get('name'), named.get('state', 0),
               tuple(named.get('modifiers', (0, 0, 0))))
        self.order.append((key, named.get('function')))

    def whoHolds(self, name, state=0, modifiers=(0, 0, 0)):
        """The last registration for a press, which is the one that answers."""
        wanted = (name, state, tuple(modifiers))
        for key, function in reversed(self.order):
            if key == wanted:
                return function
        return None


class _Host(_Bindings):
    """A context stripped to the two setup methods and the order they run in."""

    setupCallbacks = Context.setupCallbacks
    setupDefaultEventCallbacks = Context.setupDefaultEventCallbacks

    def OnEscape(self, event=None):
        pass

    def OnFrameRate(self, event=None):
        pass

    def OnNextViewpoint(self, event=None):
        pass

    def OnSaveImage(self, event=None):
        pass


class _Application(_Host):
    """One that wants PageDown for itself, as the viewer does."""

    def nextCamera(self, event=None):
        pass

    def setupCallbacks(self):
        super().setupCallbacks()
        self.addEventHandler('keyboard', name='<pagedown>',
                             function=self.nextCamera)


def _setup(host):
    """The pair, in the order :meth:`Context.__init__` runs them."""
    import inspect
    source = inspect.getsource(Context.__init__)
    first = source.index('self.setupCallbacks()')
    second = source.index('self.setupDefaultEventCallbacks()')
    for _position, call in sorted([(first, host.setupCallbacks),
                                   (second, host.setupDefaultEventCallbacks)]):
        call()


class TestWhoHoldsAKeyBothWant:
    def test_the_application_does(self):
        host = _Application()
        _setup(host)
        assert host.whoHolds('<pagedown>') == host.nextCamera

    def test_the_default_still_holds_a_key_nobody_claimed(self):
        host = _Application()
        _setup(host)
        assert host.whoHolds('<escape>') == host.OnEscape

    def test_an_application_that_claims_nothing_gets_every_default(self):
        host = _Host()
        _setup(host)
        assert host.whoHolds('<pagedown>') == host.OnNextViewpoint


class TestTheOrderItself:
    def test_the_defaults_are_bound_first(self):
        """They are the fallback, so everything else lands on top of them."""
        import inspect
        source = inspect.getsource(Context.__init__)
        assert (source.index('self.setupDefaultEventCallbacks()')
                < source.index('self.setupCallbacks()'))

    def test_the_docstring_lists_them_in_the_order_they_run(self):
        source = Context.__init__.__doc__
        assert (source.index('setupDefaultEventCallbacks')
                < source.index('setupCallbacks,'))


class TestTheViewerGetsItsPageKeys:
    """The case that found this: PageUp worked and PageDown did not."""

    @pytest.mark.parametrize('key, method', [
        ('<pagedown>', 'nextCamera'),
        ('<pageup>', 'previousCamera'),
    ])
    def test_both_page_keys_reach_the_viewer(self, key, method):
        from OpenGLContext.viewer.sceneviewer import SceneViewerMixin

        class _Viewer(_Host):
            def setupCallbacks(self):
                super().setupCallbacks()
                for binding in SceneViewerMixin.viewerKeys:
                    self.addEventHandler('keyboard', name=binding.name,
                                         state=binding.state,
                                         modifiers=binding.modifiers,
                                         function=binding.method)
        host = _Viewer()
        _setup(host)
        assert host.whoHolds(key) == method
