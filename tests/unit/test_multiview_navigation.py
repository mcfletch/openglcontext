"""What the pointer does in one view, and what says so.

Each view carries its own navigation: the gestures its camera can be moved by
-- pan, zoom and, where the camera turns, rotate -- and the bindings that say
which button raises each. The bindings are ``KeyBinding`` nodes, the same ones
the movement modes use, so the settings screen rebinds them and the binding
file saves them.

Headless: cameras, bindings and arithmetic.
"""
import numpy as np
import pytest

from OpenGLContext.edit.mapview import MapView, MapViewPlatform
from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP, button_name
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.navigation import (
    PAN,
    ROTATE,
    ZOOM_DRAG,
    ZOOM_IN,
    ZOOM_OUT,
    ViewNavigation,
    examine_mode,
    navigation_for,
    plan_mode,
)
from OpenGLContext.multiview.views import View

SIZE = (400, 300)
NONE = (0, 0, 0)


def _plan():
    view = View(MapViewPlatform(MapView(span=400.0), SIZE), name='plan')
    view.rect = (0, 0, *SIZE)
    return view


def _elevation():
    view = View(OrthoViewPlatform(OrthoView('front'), SIZE), name='front')
    view.rect = (0, 0, *SIZE)
    return view


def _angled():
    view = View(OrbitViewPlatform(OrbitView(distance=100.0), SIZE), name='angled')
    view.rect = (0, 0, *SIZE)
    return view


class TestWhatACameraCanBeMovedBy:
    def test_a_plan_view_pans_and_zooms(self):
        navigation = navigation_for(_plan())
        assert set(navigation.commands()) == {PAN, ZOOM_IN, ZOOM_OUT, ZOOM_DRAG}

    def test_an_elevation_pans_and_zooms(self):
        assert set(navigation_for(_elevation()).commands()) \
            == {PAN, ZOOM_IN, ZOOM_OUT, ZOOM_DRAG}

    def test_a_camera_that_turns_also_rotates(self):
        assert ROTATE in navigation_for(_angled()).commands()

    def test_a_view_with_no_camera_has_nothing_to_move(self):
        assert navigation_for(View(name='nothing')) is None


class TestTheBindingsItStartsWith:
    def test_the_right_and_middle_buttons_pan_a_plan_view(self):
        navigation = navigation_for(_plan())
        for button in (2, 1):
            assert navigation.command_for(button_name(button), NONE) == PAN

    def test_the_primary_click_is_left_unbound_in_every_view(self):
        """It is what an editor's tools and its selection are reached with."""
        for view in (_plan(), _elevation(), _angled()):
            assert navigation_for(view).command_for(button_name(0), NONE) is None

    def test_the_right_button_turns_a_camera_that_turns(self):
        """...and the middle one pans it; the left is the tools'."""
        navigation = navigation_for(_angled())
        assert navigation.command_for(button_name(2), NONE) == ROTATE
        assert navigation.command_for(button_name(1), NONE) == PAN

    def test_the_wheel_zooms_either_way(self):
        navigation = navigation_for(_angled())
        assert navigation.command_for(button_name(WHEEL_UP), NONE) == ZOOM_IN
        assert navigation.command_for(button_name(WHEEL_DOWN), NONE) == ZOOM_OUT

    def test_zooming_by_dragging_is_offered_and_unbound(self):
        """An alternate for a pointer with no wheel; switched on per view."""
        navigation = navigation_for(_plan())
        assert ZOOM_DRAG in navigation.commands()
        assert navigation.keys_for(ZOOM_DRAG) == ()

    def test_a_button_nothing_claims_raises_nothing(self):
        assert navigation_for(_plan()).command_for('<mouse-7>', NONE) is None


class TestChangingThem:
    def test_a_command_can_be_pointed_at_another_button(self):
        navigation = navigation_for(_angled())
        assert navigation.rebind(PAN, [button_name(1)])
        assert navigation.rebind(ROTATE, [button_name(0)])
        assert navigation.command_for(button_name(0), NONE) == ROTATE

    def test_a_command_can_be_taken_away(self):
        navigation = navigation_for(_plan())
        navigation.rebind(PAN, [])
        assert navigation.command_for(button_name(0), NONE) is None

    def test_dragging_to_zoom_is_switched_on_by_binding_it(self):
        navigation = navigation_for(_plan())
        navigation.rebind(PAN, [button_name(2)])
        navigation.rebind(ZOOM_DRAG, [button_name(1)])
        assert navigation.command_for(button_name(1), NONE) == ZOOM_DRAG

    def test_where_two_bindings_claim_a_button_the_first_declared_has_it(self):
        """A conflict is settled, and a screen that rebinds says so and asks."""
        navigation = navigation_for(_plan())
        navigation.rebind(ZOOM_DRAG, [button_name(1)])
        assert navigation.command_for(button_name(1), NONE) == PAN
        assert navigation.keys_for(ZOOM_DRAG) == (button_name(1),)

    def test_a_command_can_be_taken_off_the_button_it_shares(self):
        navigation = navigation_for(_plan())
        navigation.rebind(PAN, [button_name(2)])
        navigation.rebind(ZOOM_DRAG, [button_name(1)])
        assert navigation.command_for(button_name(1), NONE) == ZOOM_DRAG

    def test_a_command_this_camera_has_not_got_is_not_bound(self):
        navigation = navigation_for(_plan())
        assert not navigation.rebind(ROTATE, [button_name(1)])

    def test_a_binding_may_ask_for_a_modifier(self):
        navigation = navigation_for(_plan())
        navigation.rebind(ZOOM_DRAG, [button_name(2)], modifier='ctrl')
        assert navigation.command_for(button_name(2), (0, 1, 0)) == ZOOM_DRAG
        assert navigation.command_for(button_name(2), NONE) == PAN


class TestMovingTheCamera:
    def test_panning_carries_the_world_with_the_pointer(self):
        view = _elevation()
        navigation = navigation_for(view)
        under = view.camera.view.world_from_screen(200, 150, SIZE)
        navigation.begin(PAN, 200, 150)
        navigation.drag(230, 130)
        assert np.allclose(
            view.camera.view.world_from_screen(230, 130, SIZE), under)

    def test_rotating_turns_the_camera_about_what_it_looks_at(self):
        view = _angled()
        navigation = navigation_for(view)
        heading = view.camera.view.heading
        target = view.camera.view.target().copy()
        navigation.begin(ROTATE, 200, 150)
        navigation.drag(240, 150)
        assert view.camera.view.heading != heading
        assert np.allclose(view.camera.view.target(), target)

    def test_panning_a_camera_that_turns_carries_its_target(self):
        view = _angled()
        navigation = navigation_for(view)
        target = view.camera.view.target().copy()
        navigation.begin(PAN, 200, 150)
        navigation.drag(240, 150)
        assert not np.allclose(view.camera.view.target(), target)

    def test_a_notch_zooms_about_the_pointer(self):
        view = _plan()
        navigation = navigation_for(view)
        under = view.camera.view.world_from_screen(80, 60, SIZE)
        span = view.camera.view.span
        navigation.zoom(1, 80, 60)
        assert view.camera.view.span < span
        assert np.allclose(view.camera.view.world_from_screen(80, 60, SIZE), under)

    def test_a_notch_the_other_way_undoes_it(self):
        view = _plan()
        navigation = navigation_for(view)
        span = view.camera.view.span
        navigation.zoom(1, 200, 150)
        navigation.zoom(-1, 200, 150)
        assert view.camera.view.span == pytest.approx(span)

    def test_dragging_up_zooms_in_and_down_zooms_out(self):
        view = _plan()
        navigation = navigation_for(view)
        span = view.camera.view.span
        navigation.begin(ZOOM_DRAG, 200, 150)
        navigation.drag(200, 180)
        closer = view.camera.view.span
        assert closer < span
        navigation.drag(200, 120)
        assert view.camera.view.span > closer

    def test_a_drag_with_nothing_begun_moves_nothing(self):
        view = _plan()
        navigation = navigation_for(view)
        centre = view.camera.view.centre
        assert not navigation.drag(240, 150)
        assert view.camera.view.centre == centre

    def test_the_release_ends_the_gesture(self):
        view = _plan()
        navigation = navigation_for(view)
        navigation.begin(PAN, 200, 150)
        assert navigation.release()
        centre = view.camera.view.centre
        assert not navigation.drag(240, 150)
        assert view.camera.view.centre == centre

    def test_a_command_the_camera_has_not_got_begins_nothing(self):
        navigation = navigation_for(_plan())
        assert not navigation.begin(ROTATE, 200, 150)


class TestWhatASettingsScreenSees:
    def test_the_modes_and_their_bindings_are_enumerable(self):
        navigation = navigation_for(_angled())
        table = navigation.binding_table()
        assert [command for _mode, command in
                ((mode, binding.command) for mode, binding in table)] \
            == [ROTATE, PAN, ZOOM_IN, ZOOM_OUT, ZOOM_DRAG]
        for mode, binding in table:
            assert mode == navigation.mode.name
            assert binding.label

    def test_every_binding_is_a_key_binding_node(self):
        from OpenGLContext.move.modes import KeyBinding
        navigation = navigation_for(_plan())
        assert all(isinstance(binding, KeyBinding)
                   for _mode, binding in navigation.binding_table())

    def test_the_mode_can_be_replaced_with_one_of_your_own(self):
        view = _angled()
        mine = examine_mode()
        mine.name = 'mine'
        navigation = ViewNavigation(view, mode=mine)
        assert navigation.mode is mine
        assert navigation.binding_table()[0][0] == 'mine'

    def test_the_two_modes_it_ships_with(self):
        assert plan_mode().name == 'plan'
        assert examine_mode().name == 'examine'
