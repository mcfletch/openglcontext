"""``physics.backend``: the name of the compute backend the world steps with, and choosing another."""
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


def test_the_backend_is_named(physics):
    assert physics.backend == physics.worker.runtime.world.backend.name


def test_choosing_numpy_steps_the_world_on_numpy(physics):
    physics.backend = 'numpy'
    physics.flush()
    assert physics.backend == 'numpy'


def test_a_backend_that_cannot_be_made_leaves_the_world_as_it_was(physics, caplog, monkeypatch):
    physics.backend = 'numpy'
    physics.flush()

    def unavailable(prefer):
        raise RuntimeError('no GL 4.3 compute on this thread')

    monkeypatch.setattr(world, 'select_backend', unavailable)
    with caplog.at_level(logging.WARNING, logger='OpenGLContext.physics.runtime'):
        physics.backend = 'gpu'
        physics.flush()
    assert physics.backend == 'numpy'
    assert 'no GL 4.3 compute' in caplog.text


@pytest.mark.parametrize('name', ['quantum', 42, None])
def test_an_unknown_backend_name_is_refused(physics, name):
    with pytest.raises(ValueError, match='backend'):
        physics.backend = name
