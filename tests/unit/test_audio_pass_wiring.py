"""Every render pass drives the scene's sounds, not just the one that was wired.

The bug this exists to prevent: sound was hooked into the core-profile pass's
``Render``, and the compatibility pass -- which is the *default* -- overrides
``Render`` completely and so never called it.  A scene's emitters were silent on
a default install, while a sound played directly through the engine still
worked, which is a maddening thing to debug from the outside.

So the hook lives in ``__call__``, which no subclass overrides, and these tests
hold every concrete pass to it by name.  A new pass that overrides ``Render``
cannot silently drop audio, and a new pass that overrides ``__call__`` fails
here.
"""

import numpy as np
import pytest

from OpenGLContext.passes import _flat, flatcompat, flatcore, pbrpass


#: Every pass a context can actually be rendered by.
PASSES = [
    ('base', _flat.FlatPass),
    ('compatibility', flatcompat.FlatPass),
    ('core', flatcore.FlatPass),
    ('pbr', pbrpass.PBRPass),
]


class FakeViewPlatform:
    position = np.array([0.0, 0.0, 0.0, 1.0])

    def viewMatrix(self, *args, **named):
        return np.identity(4, dtype='f')

    def modelMatrix(self, *args, **named):
        return np.identity(4, dtype='f')


class FakeContext:
    def getViewPlatform(self):
        return FakeViewPlatform()


@pytest.mark.parametrize('name,cls', PASSES, ids=[p[0] for p in PASSES])
def test_the_pass_drives_scene_audio_from_its_entry_point(name, cls, monkeypatch):
    """``__call__`` must reach ``renderAudio`` whatever ``Render`` does."""
    calls = []
    monkeypatch.setattr(cls, 'Render', lambda self, context, mode: None)
    monkeypatch.setattr(_flat.FlatPass, 'renderAudio',
                        lambda self, context: calls.append(context) or 0)

    instance = cls.__new__(cls)
    instance.paths = {}
    instance.nodePaths = {}
    instance.MAX_LIGHTS = 8
    context = FakeContext()
    context.cache = None
    context.getViewPort = lambda: (16, 16)
    instance(context)
    assert calls == [context], '%s pass did not drive scene audio' % (name,)


@pytest.mark.parametrize('name,cls', PASSES, ids=[p[0] for p in PASSES])
def test_the_pass_collects_auditory_nodes(name, cls):
    """A pass that does not collect them has nothing to drive."""
    from vrml.vrml97 import nodetypes

    assert nodetypes.Auditory in cls.INTERESTING_TYPES, name


@pytest.mark.parametrize('name,cls', PASSES, ids=[p[0] for p in PASSES])
def test_no_pass_overrides_the_entry_point(name, cls):
    """The hook is in ``__call__``; an override there would step around it."""
    assert cls.__call__ is _flat.FlatPass.__call__, (
        '%s overrides __call__, which is where audio is driven' % (name,))


def test_a_failure_in_the_audio_update_never_costs_a_frame(monkeypatch, caplog):
    """A sound card that vanishes mid-session is a log line, not a black window."""
    from OpenGLContext.audio import scene as audioscene

    def explode(context, paths, now=None):
        raise RuntimeError('the sound card fell out')

    monkeypatch.setattr(audioscene, 'update', explode)
    instance = _flat.FlatPass.__new__(_flat.FlatPass)
    instance.paths = {__import__('vrml.vrml97.nodetypes', fromlist=['x']).Auditory:
                      ['not-really-a-path']}
    with caplog.at_level('WARNING'):
        assert instance.renderAudio(FakeContext()) == 0
    assert 'audio' in caplog.text


def test_a_scene_with_no_audible_nodes_costs_nothing():
    """The common case: no paths, so no engine, no device, no thread."""
    instance = _flat.FlatPass.__new__(_flat.FlatPass)
    instance.paths = {}
    assert instance.renderAudio(FakeContext()) == 0


# -- anything pinned to the view ---------------------------------------------
# Same rule, same reason: the hook is in ``__call__`` so no pass can forget it.

@pytest.mark.parametrize('name,cls', PASSES, ids=[p[0] for p in PASSES])
def test_the_pass_places_view_attachments_from_its_entry_point(name, cls,
                                                               monkeypatch):
    """A first-person model is posed once the camera is settled, before drawing.

    Anything pinned to the view -- a weapon in the player's hands -- has to be
    written *after* the view platform is settled and *before* any geometry is
    gathered, or it is drawn from the previous frame's camera and swims about
    the screen as the player moves.  ``__call__`` is the only place both are
    true, and no pass overrides it.
    """
    seen = []
    monkeypatch.setattr(cls, 'Render', lambda self, context, mode: None)
    monkeypatch.setattr(_flat.FlatPass, 'renderAudio', lambda self, ctx: 0)

    class Context(FakeContext):
        def placeViewAttachments(self, pass_):
            seen.append(pass_)

    instance = cls.__new__(cls)
    instance.paths = {}
    instance.nodePaths = {}
    instance.MAX_LIGHTS = 8
    context = Context()
    context.cache = None
    context.getViewPort = lambda: (16, 16)
    instance(context)
    assert len(seen) == 1, '%s pass did not place its view attachments' % (name,)


def test_a_context_with_nothing_pinned_to_the_view_is_unaffected(monkeypatch):
    """The hook is optional: most contexts have nothing attached to the camera."""
    monkeypatch.setattr(_flat.FlatPass, 'Render', lambda self, ctx, mode: None)
    monkeypatch.setattr(_flat.FlatPass, 'renderAudio', lambda self, ctx: 0)
    instance = _flat.FlatPass.__new__(_flat.FlatPass)
    instance.paths = {}
    instance.nodePaths = {}
    instance.MAX_LIGHTS = 8
    context = FakeContext()
    context.cache = None
    context.getViewPort = lambda: (16, 16)
    assert instance(context) is True


def test_view_attachments_are_placed_before_the_scene_is_gathered(monkeypatch):
    """Order is the whole point: after the camera, before anything is drawn."""
    order = []
    monkeypatch.setattr(_flat.FlatPass, 'renderAudio', lambda self, ctx: 0)
    monkeypatch.setattr(_flat.FlatPass, 'Render',
                        lambda self, ctx, mode: order.append('render'))

    class Context(FakeContext):
        def placeViewAttachments(self, pass_):
            order.append('place')

    instance = _flat.FlatPass.__new__(_flat.FlatPass)
    instance.paths = {}
    instance.nodePaths = {}
    instance.MAX_LIGHTS = 8
    context = Context()
    context.cache = None
    context.getViewPort = lambda: (16, 16)
    instance(context)
    assert order == ['place', 'render']
