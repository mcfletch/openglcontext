"""Spatialisation arithmetic: distance curves, cones, ellipsoids and panning.

Everything here is a pure function of geometry, so every assertion is a number
compared against the specification that defines it -- no device, no thread and
no clip.
"""

import math

import numpy as np
import pytest

from OpenGLContext.audio import spatial


TAU = 2.0 * math.pi


class TestDistanceGain:
    """The three glTF ``KHR_audio_emitter`` distance models."""

    def test_inverse_model_is_unity_inside_the_reference_distance(self):
        for distance in (0.0, 0.5, 1.0):
            assert spatial.distance_gain(distance, spatial.DistanceModel.INVERSE,
                                         ref_distance=1.0) == pytest.approx(1.0)

    def test_inverse_model_halves_at_twice_the_reference_distance(self):
        # ref / (ref + rolloff * (d - ref)) = 1 / (1 + 1) at d = 2, ref = 1.
        assert spatial.distance_gain(2.0, spatial.DistanceModel.INVERSE,
                                     ref_distance=1.0) == pytest.approx(0.5)

    def test_inverse_model_rolloff_factor_scales_the_falloff(self):
        assert spatial.distance_gain(3.0, spatial.DistanceModel.INVERSE,
                                     ref_distance=1.0,
                                     rolloff_factor=0.5) == pytest.approx(1.0 / 2.0)

    def test_linear_model_reaches_zero_at_the_maximum_distance(self):
        gain = spatial.distance_gain(11.0, spatial.DistanceModel.LINEAR,
                                     ref_distance=1.0, max_distance=11.0)
        assert gain == pytest.approx(0.0)

    def test_linear_model_is_half_way_at_the_midpoint(self):
        gain = spatial.distance_gain(6.0, spatial.DistanceModel.LINEAR,
                                     ref_distance=1.0, max_distance=11.0)
        assert gain == pytest.approx(0.5)

    def test_linear_model_clamps_beyond_the_maximum_rather_than_going_negative(self):
        gain = spatial.distance_gain(1000.0, spatial.DistanceModel.LINEAR,
                                     ref_distance=1.0, max_distance=11.0)
        assert gain == pytest.approx(0.0)

    def test_exponential_model_halves_at_twice_the_reference_distance(self):
        assert spatial.distance_gain(2.0, spatial.DistanceModel.EXPONENTIAL,
                                     ref_distance=1.0) == pytest.approx(0.5)

    def test_exponential_model_rolloff_factor_is_the_exponent(self):
        assert spatial.distance_gain(4.0, spatial.DistanceModel.EXPONENTIAL,
                                     ref_distance=1.0,
                                     rolloff_factor=0.5) == pytest.approx(0.5)

    def test_distance_is_clamped_to_the_maximum_before_the_curve_is_applied(self):
        """Past ``maxDistance`` the gain stops falling; it does not keep going."""
        at_max = spatial.distance_gain(10.0, spatial.DistanceModel.INVERSE,
                                       ref_distance=1.0, max_distance=10.0)
        beyond = spatial.distance_gain(500.0, spatial.DistanceModel.INVERSE,
                                       ref_distance=1.0, max_distance=10.0)
        assert beyond == pytest.approx(at_max)

    def test_zero_maximum_distance_means_no_maximum(self):
        """``maxDistance`` defaults to 0, which the extension defines as unbounded."""
        near = spatial.distance_gain(10.0, spatial.DistanceModel.INVERSE,
                                     ref_distance=1.0, max_distance=0.0)
        far = spatial.distance_gain(100.0, spatial.DistanceModel.INVERSE,
                                    ref_distance=1.0, max_distance=0.0)
        assert far < near

    def test_reference_distance_must_be_positive(self):
        with pytest.raises(ValueError):
            spatial.distance_gain(1.0, spatial.DistanceModel.INVERSE, ref_distance=0.0)

    def test_model_may_be_named_by_its_gltf_string(self):
        assert spatial.distance_gain(2.0, 'inverse', ref_distance=1.0) == pytest.approx(0.5)


class TestConeGain:
    """The Web Audio sound-cone algorithm ``KHR_audio_emitter`` adopts."""

    def test_default_full_circle_cone_never_attenuates(self):
        for angle in (0.0, math.pi / 2, math.pi):
            assert spatial.cone_gain(angle, TAU, TAU, 0.0) == pytest.approx(1.0)

    def test_inside_the_inner_cone_is_unattenuated(self):
        assert spatial.cone_gain(0.1, inner_angle=math.pi / 2,
                                 outer_angle=math.pi, outer_gain=0.2) == pytest.approx(1.0)

    def test_outside_the_outer_cone_is_the_outer_gain(self):
        assert spatial.cone_gain(math.pi, inner_angle=math.pi / 2,
                                 outer_angle=math.pi * 0.75,
                                 outer_gain=0.2) == pytest.approx(0.2)

    def test_between_the_cones_interpolates_linearly(self):
        """Half way from the inner to the outer half-angle is half way in gain."""
        # Half-angles: inner pi/8, outer 3*pi/8.  Midpoint is pi/4.
        gain = spatial.cone_gain(math.pi / 4, inner_angle=math.pi / 4,
                                 outer_angle=math.pi * 0.75, outer_gain=0.0)
        assert gain == pytest.approx(0.5)

    def test_angles_are_diameters_so_the_half_angle_is_the_boundary(self):
        """``coneInnerAngle`` is the whole cone, side to side, not the half-angle."""
        just_inside = spatial.cone_gain(math.pi / 4 - 1e-6, inner_angle=math.pi / 2,
                                        outer_angle=math.pi, outer_gain=0.0)
        just_outside = spatial.cone_gain(math.pi / 4 + 1e-6, inner_angle=math.pi / 2,
                                         outer_angle=math.pi, outer_gain=0.0)
        assert just_inside == pytest.approx(1.0)
        assert just_outside < 1.0

    def test_degenerate_cone_with_equal_angles_is_a_hard_edge(self):
        assert spatial.cone_gain(0.1, math.pi / 2, math.pi / 2, 0.3) == pytest.approx(1.0)
        assert spatial.cone_gain(1.0, math.pi / 2, math.pi / 2, 0.3) == pytest.approx(0.3)


class TestEllipsoidReach:
    """VRML97's two ellipsoids, each with a focus at the sound's location."""

    def test_directly_in_front_the_reach_is_the_front_distance(self):
        assert spatial.ellipsoid_reach(10.0, 2.0, 1.0) == pytest.approx(10.0)

    def test_directly_behind_the_reach_is_the_back_distance(self):
        assert spatial.ellipsoid_reach(10.0, 2.0, -1.0) == pytest.approx(2.0)

    def test_equal_front_and_back_is_a_sphere(self):
        for cos_theta in (-1.0, -0.3, 0.0, 0.5, 1.0):
            assert spatial.ellipsoid_reach(4.0, 4.0, cos_theta) == pytest.approx(4.0)

    def test_sideways_reach_is_the_semi_latus_rectum(self):
        """At right angles to the axis the focal chord is 2*f*b/(f+b)."""
        assert spatial.ellipsoid_reach(10.0, 2.0, 0.0) == pytest.approx(2 * 10 * 2 / 12)

    def test_degenerate_ellipsoid_has_no_reach(self):
        assert spatial.ellipsoid_reach(0.0, 5.0, 1.0) == pytest.approx(0.0)
        assert spatial.ellipsoid_reach(-1.0, 5.0, 1.0) == pytest.approx(0.0)


class TestEllipsoidGain:
    """VRML97's linear-in-decibels ramp between the two ellipsoids."""

    INNER = dict(min_front=1.0, min_back=1.0, max_front=11.0, max_back=11.0)

    def test_inside_the_inner_ellipsoid_is_full_volume(self):
        assert spatial.ellipsoid_gain(0.5, 1.0, **self.INNER) == pytest.approx(1.0)
        assert spatial.ellipsoid_gain(1.0, 1.0, **self.INNER) == pytest.approx(1.0)

    def test_outside_the_outer_ellipsoid_is_silence(self):
        assert spatial.ellipsoid_gain(11.5, 1.0, **self.INNER) == pytest.approx(0.0)

    def test_at_the_outer_ellipsoid_the_ramp_has_reached_minus_twenty_db(self):
        assert spatial.ellipsoid_gain(11.0, 1.0, **self.INNER) == pytest.approx(0.1)

    def test_half_way_between_is_minus_ten_db(self):
        assert spatial.ellipsoid_gain(6.0, 1.0, **self.INNER) == pytest.approx(
            10.0 ** -0.5)

    def test_the_ramp_follows_the_ellipsoid_not_the_sphere(self):
        """Behind a forward-facing sound the ramp starts and ends nearer."""
        fields = dict(min_front=10.0, min_back=1.0, max_front=20.0, max_back=2.0)
        assert spatial.ellipsoid_gain(1.5, -1.0, **fields) < 1.0
        assert spatial.ellipsoid_gain(1.5, 1.0, **fields) == pytest.approx(1.0)

    def test_coincident_ellipsoids_are_a_hard_edge(self):
        fields = dict(min_front=5.0, min_back=5.0, max_front=5.0, max_back=5.0)
        assert spatial.ellipsoid_gain(4.9, 1.0, **fields) == pytest.approx(1.0)
        assert spatial.ellipsoid_gain(5.1, 1.0, **fields) == pytest.approx(0.0)


class TestListener:
    """The listener's pose, and where a point is relative to it."""

    #: Looking down -Z with +Y up -- the VRML/glTF default view.
    DEFAULT = dict(position=(0.0, 0.0, 0.0), forward=(0.0, 0.0, -1.0), up=(0.0, 1.0, 0.0))

    def test_right_is_the_cross_of_forward_and_up(self):
        listener = spatial.Listener(**self.DEFAULT)
        assert np.allclose(listener.right, (1.0, 0.0, 0.0))

    def test_axes_are_normalised_on_construction(self):
        listener = spatial.Listener(position=(0, 0, 0), forward=(0, 0, -7), up=(0, 3, 0))
        assert np.allclose(listener.forward, (0, 0, -1))
        assert np.allclose(listener.up, (0, 1, 0))

    def test_a_source_straight_ahead_has_zero_azimuth(self):
        listener = spatial.Listener(**self.DEFAULT)
        azimuth, elevation = listener.azimuth_elevation((0.0, 0.0, -5.0))
        assert azimuth == pytest.approx(0.0)
        assert elevation == pytest.approx(0.0)

    def test_a_source_to_the_right_has_positive_azimuth(self):
        listener = spatial.Listener(**self.DEFAULT)
        azimuth, _ = listener.azimuth_elevation((5.0, 0.0, 0.0))
        assert azimuth == pytest.approx(math.pi / 2)

    def test_a_source_to_the_left_has_negative_azimuth(self):
        listener = spatial.Listener(**self.DEFAULT)
        azimuth, _ = listener.azimuth_elevation((-5.0, 0.0, 0.0))
        assert azimuth == pytest.approx(-math.pi / 2)

    def test_a_source_behind_has_azimuth_of_half_a_turn(self):
        listener = spatial.Listener(**self.DEFAULT)
        azimuth, _ = listener.azimuth_elevation((0.0, 0.0, 5.0))
        assert abs(azimuth) == pytest.approx(math.pi)

    def test_a_source_overhead_has_a_quarter_turn_elevation(self):
        listener = spatial.Listener(**self.DEFAULT)
        _, elevation = listener.azimuth_elevation((0.0, 5.0, 0.0))
        assert elevation == pytest.approx(math.pi / 2)

    def test_azimuth_is_measured_in_the_listeners_own_frame(self):
        """Turn the listener to face +X and the source at +X is now ahead."""
        listener = spatial.Listener(position=(0, 0, 0), forward=(1, 0, 0), up=(0, 1, 0))
        azimuth, _ = listener.azimuth_elevation((5.0, 0.0, 0.0))
        assert azimuth == pytest.approx(0.0)

    def test_a_source_at_the_listener_is_dead_ahead_rather_than_undefined(self):
        listener = spatial.Listener(**self.DEFAULT)
        assert listener.azimuth_elevation((0.0, 0.0, 0.0)) == (0.0, 0.0)

    def test_distance_to_a_point(self):
        listener = spatial.Listener(position=(1.0, 2.0, 3.0), forward=(0, 0, -1),
                                    up=(0, 1, 0))
        assert listener.distance_to((1.0, 2.0, 8.0)) == pytest.approx(5.0)

    def test_built_from_a_view_platform_matrix(self):
        """The inverse of the view matrix is the listener's world pose."""
        from OpenGLContext.move import viewplatform

        platform = viewplatform.ViewPlatform(position=(3.0, 4.0, 5.0))
        listener = spatial.Listener.from_view_platform(platform)
        assert np.allclose(listener.position, (3.0, 4.0, 5.0))
        assert np.allclose(listener.forward, (0.0, 0.0, -1.0), atol=1e-6)
        assert np.allclose(listener.up, (0.0, 1.0, 0.0), atol=1e-6)


class TestEqualPowerPan:
    """Equal-power stereo panning about the listener's forward axis."""

    def test_dead_ahead_is_equal_in_both_ears(self):
        left, right = spatial.equal_power_pan(0.0)
        assert left == pytest.approx(right)
        assert left == pytest.approx(math.sqrt(0.5))

    def test_hard_right_puts_everything_in_the_right_ear(self):
        left, right = spatial.equal_power_pan(math.pi / 2)
        assert left == pytest.approx(0.0, abs=1e-9)
        assert right == pytest.approx(1.0)

    def test_hard_left_puts_everything_in_the_left_ear(self):
        left, right = spatial.equal_power_pan(-math.pi / 2)
        assert left == pytest.approx(1.0)
        assert right == pytest.approx(0.0, abs=1e-9)

    def test_power_is_constant_across_the_arc(self):
        for azimuth in np.linspace(-math.pi, math.pi, 33):
            left, right = spatial.equal_power_pan(float(azimuth))
            assert left * left + right * right == pytest.approx(1.0)

    def test_behind_the_listener_mirrors_the_front_pan(self):
        """A source behind-and-right pans right, as the Web Audio fold specifies."""
        front = spatial.equal_power_pan(math.pi / 4)
        behind = spatial.equal_power_pan(math.pi * 3 / 4)
        assert behind == pytest.approx(front)
