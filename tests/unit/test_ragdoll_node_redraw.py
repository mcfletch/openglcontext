"""A Ragdoll node asks for a redraw while its figure moves or follows its animation, and not once it rests."""
import pytest

from OpenGLContext.scenegraph.softnodes import Ragdoll
from tests.unit.test_character_ragdoll import BONES, figure
from tests.unit.test_softnodes import _Context


class _Model:
    """A character model of the test skeleton, with no clips."""

    def __init__(self):
        from OpenGLContext.scenegraph.basenodes import Transform

        self.mixer = figure()
        self.humanoid = type('Humanoid', (), {'bones': BONES})()
        self.group = Transform()
        self.clips = {}


def test_a_ragdoll_that_has_come_to_rest_asks_for_no_redraw(monkeypatch):
    from OpenGLContext.character import model as model_module
    from OpenGLContext.physics import Physics, PhysicsDefinition, Proxy

    monkeypatch.setattr(model_module.CharacterModel, 'load', classmethod(lambda cls, url: _Model()))
    physics = Physics(PhysicsDefinition(mode='inline', tickHz=120.0))
    try:
        physics.add_static(None, proxy=Proxy.box((40.0, 1.0, 40.0)), translation=(0.0, -0.5, 0.0))
        doll = Ragdoll(url=['figure.glb'], mode='LIMP', translation=(0.0, 0.2, 0.0))
        context = _Context(physics)
        doll.bind(context)
        physics.frame(1 / 60)
        assert doll.step(context)
        figure_ = doll.figure(context)
        for _ in range(600):
            if figure_.settled:
                break
            doll.step(context)
            physics.frame(1 / 60)
        assert figure_.settled
        doll.step(context)
        assert not doll.step(context)
        figure_.ragdoll.bones[0].apply_impulse((0.0, 30.0, 0.0))
        physics.frame(1 / 60)
        assert doll.step(context)
    finally:
        physics.close()
