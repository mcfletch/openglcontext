"""``Light.modelMatrix`` takes world coordinates into a light's own frame
(:mod:`OpenGLContext.scenegraph.light`).

The default is the world-to-light direction, which is what a shadow pass
multiplies by: it carries the light's ``location`` to the origin and its
``direction`` onto -Z.  ``inverse=True`` gives the other one, the light's
placement in the world.

The three light types carry different fields -- a ``DirectionalLight`` has a
direction and no location, a ``PointLight`` a location and no direction, and a
``SpotLight`` both -- and every one of them has to answer with a 4x4 matrix,
including the cases where there is nothing to rotate or translate by and the
answer is the identity.

``tests/shadow_1.py`` is the tutorial that consumes it.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.light import (
    DirectionalLight, PointLight, SpotLight,
)

IDENTITY = np.identity(4, dtype='f')


def _matrix(light, **named):
    found = light.modelMatrix(**named)
    assert found is not None, "modelMatrix gave nothing"
    found = np.asarray(found, dtype='f')
    assert found.shape == (4, 4), found.shape
    return found


class TestEveryLightTypeAnswers:
    """A 4x4 matrix from each of the three, with their default fields."""

    def test_directional_light(self):
        _matrix(DirectionalLight())

    def test_point_light(self):
        _matrix(PointLight())

    def test_spot_light(self):
        _matrix(SpotLight())


class TestNothingToPlaceBy:
    """A light at the origin shining down -Z is placed by the identity.

    ``rotMatrix`` and ``transMatrix`` both answer ``None`` for a null
    rotation and a null translation, so this is the case where there is no
    matrix to compose and one has to be produced.
    """

    def test_spot_light_at_the_origin(self):
        assert np.allclose(
            _matrix(SpotLight(location=(0, 0, 0), direction=(0, 0, -1))),
            IDENTITY,
        )

    def test_point_light_at_the_origin(self):
        assert np.allclose(_matrix(PointLight(location=(0, 0, 0))), IDENTITY)

    def test_directional_light_down_z(self):
        assert np.allclose(_matrix(DirectionalLight(direction=(0, 0, -1))), IDENTITY)


class TestLocationIsTheTranslation:
    """A point light has no direction, so the frame differs only by its location."""

    def test_the_location_maps_to_the_origin(self):
        found = _matrix(PointLight(location=(1, 2, 3)))
        location = np.array([1.0, 2.0, 3.0, 1.0], dtype='f')
        assert np.allclose((location @ found)[:3], (0, 0, 0), atol=1e-5)

    def test_the_inverse_carries_the_origin_back_out(self):
        found = _matrix(PointLight(location=(1, 2, 3)), inverse=True)
        origin = np.array([0.0, 0.0, 0.0, 1.0], dtype='f')
        assert np.allclose((origin @ found)[:3], (1, 2, 3), atol=1e-5)


class TestTheDirectionMapsOntoMinusZ:
    """What the world-to-light matrix is for: the light looks down -Z in it."""

    @pytest.mark.parametrize('direction', [
        (0, -1, 0), (1, 0, 0), (1, -1, -1), (0, 0, 1),
    ])
    def test_the_direction_becomes_minus_z(self, direction):
        found = _matrix(SpotLight(location=(0, 0, 0), direction=direction))
        d = np.asarray(direction, dtype='f')
        d = d / np.sqrt(np.sum(d * d))
        rotated = (np.append(d, 0.0) @ found)[:3]
        assert np.allclose(rotated, (0, 0, -1), atol=1e-5), rotated


class TestTheInverseUndoesIt:
    """The two directions compose to the identity."""

    @pytest.mark.parametrize('light', [
        PointLight(location=(1, 2, 3)),
        SpotLight(location=(1, 2, 3), direction=(0, -1, 0)),
        SpotLight(location=(0, 0, 0), direction=(0, 0, -1)),
        DirectionalLight(direction=(1, -1, 0)),
    ], ids=['point', 'spot', 'spot-identity', 'directional'])
    def test_the_two_compose_to_the_identity(self, light):
        forward = _matrix(light)
        back = _matrix(light, inverse=True)
        assert np.allclose(forward @ back, IDENTITY, atol=1e-5)


class TestTheDirectionCanBeOverridden:
    """A caller with a direction in hand passes it rather than setting a field.

    ``renderLightTexture`` in ``tests/shadow_1.py`` does this for the animated
    light whose direction it is already tracking.
    """

    def test_the_argument_wins_over_the_field(self):
        light = SpotLight(location=(0, 0, 0), direction=(0, 0, -1))
        assert not np.allclose(_matrix(light, direction=(0, -1, 0)), IDENTITY)
