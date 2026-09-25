"""``check_mirrored_render`` refuses a picture of nothing and one that does not mirror."""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing import mirrored
from OpenGLContext.testing.mirrored import MirroredRender, NotMirrored


def _found(drawn, differing):
    blank = np.zeros((4, 4, 3), np.uint8)
    return MirroredRender(blank, blank, drawn, differing)


def test_a_geometry_out_of_sight_is_refused(monkeypatch):
    monkeypatch.setattr(mirrored, 'mirrored_render', lambda geometry, **named: _found(0.0, 0.0))
    with pytest.raises(NotMirrored, match='covers 0.0% of the frame'):
        mirrored.check_mirrored_render(basenodes.Box())


def test_a_picture_that_is_not_turned_over_is_refused(monkeypatch):
    monkeypatch.setattr(mirrored, 'mirrored_render', lambda geometry, **named: _found(0.3, 0.3))
    with pytest.raises(NotMirrored, match='Box under a mirroring transform differs'):
        mirrored.check_mirrored_render(basenodes.Box())


def test_the_plugin_offers_it_as_a_fixture(check_mirrored_render):
    found = check_mirrored_render(basenodes.Sphere())
    assert found.drawn > 0.1 and found.differing < 0.02
    assert found.plain.shape == found.mirrored.shape == (64, 64, 3)
