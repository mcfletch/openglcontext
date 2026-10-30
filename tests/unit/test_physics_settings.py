"""Tests for PhysicsDefinition, the node a context's physics is configured by."""
import numpy as np
import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.physics.settings import MODES, PhysicsDefinition, definition_for


def test_defaults_are_the_games_starting_point():
    definition = PhysicsDefinition()
    assert definition.enabled
    assert definition.mode == 'thread'
    assert definition.tickHz == pytest.approx(120.0)
    assert definition.maxCatchUp == pytest.approx(0.1)
    assert np.allclose(definition.gravity, (0.0, -9.81, 0.0))
    assert definition.colliders == 'scene'
    assert definition.linearDamping == pytest.approx(0.3)
    assert definition.angularDamping == pytest.approx(1.5)


def test_a_context_definition_carries_one():
    assert isinstance(ContextDefinition().physics, PhysicsDefinition)


def test_the_environment_switches_physics_off(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '0')
    assert not PhysicsDefinition().enabled


def test_the_environment_names_the_mode(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_PHYSICS_MODE', 'inline')
    assert PhysicsDefinition().mode == 'inline'


def test_an_unknown_environment_mode_falls_back_to_the_default(monkeypatch, caplog):
    monkeypatch.setenv('OPENGLCONTEXT_PHYSICS_MODE', 'process')
    assert PhysicsDefinition().mode == 'thread'
    assert 'OPENGLCONTEXT_PHYSICS_MODE' in caplog.text


def test_fields_are_set_by_keyword():
    definition = PhysicsDefinition(mode='inline', tickHz=240.0, gravity=(0, -1.6, 0),
                                   colliders='explicit')
    assert definition.mode == 'inline'
    assert definition.tickHz == pytest.approx(240.0)
    assert np.allclose(definition.gravity, (0, -1.6, 0))
    assert definition.colliders == 'explicit'


def test_modes_lists_what_a_definition_accepts():
    assert MODES == ('thread', 'inline')


@pytest.mark.parametrize('field, value', [('mode', 'process'), ('colliders', 'everything')])
def test_validate_rejects_a_value_the_service_cannot_run(field, value):
    definition = PhysicsDefinition(**{field: value})
    with pytest.raises(ValueError, match=field):
        definition.validate()


@pytest.mark.parametrize('field, value', [('tickHz', 0.0), ('tickHz', -5.0), ('maxCatchUp', 0.0)])
def test_validate_rejects_a_step_that_cannot_advance(field, value):
    definition = PhysicsDefinition(**{field: value})
    with pytest.raises(ValueError, match=field):
        definition.validate()


def test_validate_accepts_the_defaults():
    assert PhysicsDefinition().validate() is None


def test_definition_for_reads_a_contexts_definition():
    class Holder:
        contextDefinition = ContextDefinition(physics=PhysicsDefinition(mode='inline'))

    assert definition_for(Holder()).mode == 'inline'


def test_definition_for_defaults_a_context_that_has_none():
    assert definition_for(object()).mode == 'thread'


def test_gravity_as_a_world_gravity_record():
    from OpenGLContext.physics import omi_adapter

    gravity = omi_adapter.gravity(PhysicsDefinition(gravity=(0, -3.0, 0)).gravity)
    assert gravity.gravity == pytest.approx(3.0)
    assert np.allclose(gravity.direction, (0, -1, 0))


def test_zero_gravity_gives_a_world_with_none():
    from OpenGLContext.physics import omi_adapter

    gravity = omi_adapter.gravity(PhysicsDefinition(gravity=(0, 0, 0)).gravity)
    assert gravity.gravity == 0.0


def test_replaced_gives_a_new_definition_with_some_fields_changed():
    original = PhysicsDefinition(mode='thread', tickHz=90.0)
    changed = original.replaced(mode='inline')
    assert changed is not original
    assert changed.mode == 'inline' and changed.tickHz == pytest.approx(90.0)
    assert original.mode == 'thread'
