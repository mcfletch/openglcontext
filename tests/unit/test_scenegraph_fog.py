"""VRML97's ``Fog`` node, and what it hands the shader.

pyvrml97 has declared ``Fog`` for twenty-odd years and the render pass has
collected its paths for nearly as long; nothing ever drew one.  It does now.

The arithmetic is the specification's and not an approximation of it, which is
the whole reason to have the node rather than a density number on a context:
``LINEAR`` and ``EXPONENTIAL`` are different curves that reach full obscurity at
the same range, and an author choosing between them is choosing between those.

Reference:
    ISO/IEC 14772-1:1997 (VRML97) 6.19 ``Fog``
    https://www.web3d.org/documents/specifications/14772/V2.0/part1/nodesRef.html#Fog
"""

import numpy as np
import pytest

from OpenGLContext.scenegraph.fog import (
    FOG_EXPONENTIAL, FOG_LINEAR, FOG_NONE, Fog,
)


def scaled(factor):
    """A row-vector 4x4 uniform scale, as ``NodePath.transformMatrix`` returns."""
    matrix = np.identity(4, dtype='d')
    matrix[0, 0] = matrix[1, 1] = matrix[2, 2] = factor
    return matrix


class TestWhetherItFogsAtAll:

    def test_the_default_node_does_nothing(self):
        """visibilityRange defaults to 0, which the specification says is off.

        A ``Fog`` dropped into a scene and left alone must leave it looking
        exactly as it did.
        """
        assert Fog().fogParameters(np.identity(4))[0] == FOG_NONE

    def test_a_visibility_range_switches_it_on(self):
        mode, _density, _color = Fog(visibilityRange=50.0).fogParameters(np.identity(4))
        assert mode != FOG_NONE

    def test_a_negative_range_is_off_rather_than_inverted(self):
        assert Fog(visibilityRange=-5.0).fogParameters(np.identity(4))[0] == FOG_NONE


class TestTheTwoCurves:

    def test_linear_is_the_default_type(self):
        """The specification's default, and the one an author gets unasked."""
        assert Fog(visibilityRange=10.0).fogParameters(np.identity(4))[0] == FOG_LINEAR

    def test_exponential_is_selected_by_name(self):
        fog = Fog(visibilityRange=10.0, fogType='EXPONENTIAL')
        assert fog.fogParameters(np.identity(4))[0] == FOG_EXPONENTIAL

    def test_an_unknown_type_falls_back_to_linear(self):
        """An unreadable field must not be a scene that will not draw."""
        fog = Fog(visibilityRange=10.0, fogType='SOMETHING-ELSE')
        assert fog.fogParameters(np.identity(4))[0] == FOG_LINEAR


class TestTheRangeHandedToTheShader:
    """One number serves both curves: the reciprocal of the visible range."""

    def test_the_density_is_the_reciprocal_of_the_range(self):
        _mode, density, _color = Fog(visibilityRange=50.0).fogParameters(np.identity(4))
        assert density == pytest.approx(1 / 50.0)

    def test_a_shorter_range_is_a_higher_density(self):
        near = Fog(visibilityRange=5.0).fogParameters(np.identity(4))[1]
        far = Fog(visibilityRange=500.0).fogParameters(np.identity(4))[1]
        assert near > far

    def test_the_range_is_in_the_nodes_own_coordinates(self):
        """6.19: the range is in the local system, so a scale scales it."""
        fog = Fog(visibilityRange=10.0)
        plain = fog.fogParameters(np.identity(4))[1]
        assert fog.fogParameters(scaled(2.0))[1] == pytest.approx(plain / 2.0)

    def test_a_degenerate_transform_does_not_divide_by_zero(self):
        """A zero scale is a range of nothing, which is fog everywhere."""
        assert Fog(visibilityRange=10.0).fogParameters(scaled(0.0))[0] == FOG_NONE


class TestTheColour:

    def test_the_colour_is_carried_through(self):
        fog = Fog(visibilityRange=10.0, color=(0.1, 0.2, 0.3))
        assert fog.fogParameters(np.identity(4))[2] == pytest.approx((0.1, 0.2, 0.3))

    def test_the_default_colour_is_white(self):
        """6.19's default.  White fog over a bright scene is nearly invisible,
        which is the right thing for a node nobody has configured."""
        assert Fog().color == pytest.approx((1.0, 1.0, 1.0))


class TestBinding:
    """``Fog`` is bindable, so a scene may hold several and one applies."""

    def test_a_fog_is_bindable(self):
        from vrml.vrml97 import nodetypes
        assert isinstance(Fog(), nodetypes.Bindable)

    def test_a_fog_is_not_drawn_and_has_no_bounding_volume_of_its_own(self):
        """It affects everything, so it bounds nothing."""
        assert not hasattr(Fog(), 'render')
