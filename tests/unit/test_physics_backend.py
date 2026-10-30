"""The compute backend the world steps with: ``physics.engine.compute``, and choosing another by the definition."""
import logging

import pytest
from omi_physics import world

from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition


@pytest.fixture
def physics():
    service = Physics(PhysicsDefinition(mode='inline'))
    yield service
    service.close()


def choose(physics, name):
    physics.set_config(physics.definition.replaced(backend=name))
    physics.flush()


def test_the_backend_is_named(physics):
    assert physics.engine.compute == physics.worker.runtime.world.backend.name


def test_choosing_numpy_steps_the_world_on_numpy(physics):
    choose(physics, 'numpy')
    assert physics.engine.compute == 'numpy'


def test_a_backend_that_cannot_be_made_leaves_the_world_as_it_was(physics, caplog, monkeypatch):
    choose(physics, 'numpy')

    def unavailable(prefer):
        raise RuntimeError('no GL 4.3 compute on this thread')

    monkeypatch.setattr(world, 'select_backend', unavailable)
    with caplog.at_level(logging.WARNING, logger='OpenGLContext.physics.runtime'):
        choose(physics, 'gpu')
    assert physics.engine.compute == 'numpy'
    assert 'no GL 4.3 compute' in caplog.text


@pytest.mark.parametrize('name', ['quantum', 42, None])
def test_an_unknown_backend_name_is_refused(physics, name):
    with pytest.raises(ValueError, match='backend'):
        choose(physics, name)


def test_the_backend_variable_is_the_definitions_default(monkeypatch):
    from OpenGLContext import renderoptions  # noqa: PLC0415 only these cases pin the variable

    monkeypatch.setattr(renderoptions.os, 'environ', {**renderoptions.os.environ,
                                                      'OPENGLCONTEXT_PHYSICS_BACKEND': 'numpy'})
    definition = PhysicsDefinition(mode='inline')
    assert definition.backend == 'numpy'
    service = Physics(definition)
    try:
        assert service.worker.runtime.world.backend_mode == 'fixed'
    finally:
        service.close()


def test_a_backend_variable_that_names_none_is_reported_and_auto_used(monkeypatch, caplog):
    from OpenGLContext import renderoptions  # noqa: PLC0415 only these cases pin the variable

    monkeypatch.setattr(renderoptions.os, 'environ', {**renderoptions.os.environ,
                                                      'OPENGLCONTEXT_PHYSICS_BACKEND': 'quantum'})
    assert PhysicsDefinition().backend == 'auto'
    assert 'quantum' in caplog.text


def test_a_definition_asking_for_a_backend_that_cannot_be_made_keeps_the_default(monkeypatch, caplog):
    def unavailable(prefer):
        raise RuntimeError('no GL 4.3 compute on this thread')

    monkeypatch.setattr(world, 'select_backend', unavailable)
    service = Physics(PhysicsDefinition(mode='inline', backend='gpu'))
    try:
        assert service.engine.compute == 'numpy'
        assert 'no GL 4.3 compute' in caplog.text
    finally:
        service.close()


def test_the_render_threads_copy_steps_on_numpy_whatever_the_variable(monkeypatch):
    from OpenGLContext.physics.replica import Replica  # noqa: PLC0415 only this case builds one

    monkeypatch.setenv('OPENGLCONTEXT_PHYSICS_BACKEND', 'gpu')
    monkeypatch.setattr(world, 'select_backend', lambda prefer: pytest.fail('asked for a GPU'))
    assert Replica().world.backend.name == 'numpy'


def test_a_definition_with_an_unknown_backend_is_refused():
    with pytest.raises(ValueError, match='backend'):
        PhysicsDefinition(backend='quantum').validate()
