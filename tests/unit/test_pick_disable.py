"""Tests for disabling scenegraph pick-renders via ContextDefinition.pickEnabled.

Pure/headless: exercises the env default, the field, and the addPickEvent gate
without needing a GL context.
"""
from OpenGLContext import contextdefinition as cd
from OpenGLContext.context import Context


class _FakeEvent:
    type = 'mousebutton'

    def __init__(self, key=(10, 20)):
        self._key = key

    def getKey(self):
        return self._key


class _StubContext:
    """Just enough of a Context to drive addPickEvent in isolation."""

    def __init__(self, definition):
        self.pickEvents = {}
        self.contextDefinition = definition


class TestPickingDefault:
    def test_enabled_by_default(self):
        assert cd._get_default_picking() is True
        assert bool(cd.ContextDefinition().pickEnabled) is True

    def test_env_disables(self, monkeypatch):
        for v in ('0', 'off', 'false', 'no', ''):
            monkeypatch.setenv('OPENGLCONTEXT_PICKING', v)
            assert cd._get_default_picking() is False, v

    def test_env_enables(self, monkeypatch):
        for v in ('1', 'on', 'true', 'yes'):
            monkeypatch.setenv('OPENGLCONTEXT_PICKING', v)
            assert cd._get_default_picking() is True, v

    def test_field_settable(self):
        d = cd.ContextDefinition()
        d.pickEnabled = False
        assert bool(d.pickEnabled) is False


class TestAddPickEventGate:
    def test_records_when_enabled(self):
        d = cd.ContextDefinition()
        d.pickEnabled = True
        ctx = _StubContext(d)
        Context.addPickEvent(ctx, _FakeEvent())
        assert len(ctx.pickEvents) == 1

    def test_dropped_when_disabled(self):
        d = cd.ContextDefinition()
        d.pickEnabled = False
        ctx = _StubContext(d)
        Context.addPickEvent(ctx, _FakeEvent())
        assert ctx.pickEvents == {}

    def test_records_when_definition_missing(self):
        # A context created before its definition is attached must still record
        # events (back-compat: the old behaviour was unconditional).
        ctx = _StubContext(None)
        Context.addPickEvent(ctx, _FakeEvent())
        assert len(ctx.pickEvents) == 1
