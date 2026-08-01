"""The developer overlay: what registers into it, and how its rows lay out.

A provider is a callable and a section is a list of pairs, so the whole of this
is testable by handing in a fake provider and reading the laid-out rows back.
"""

import pytest

from OpenGLContext.ui.debugoverlay import (
    DebugOverlay, DebugSection, format_value,
)
from OpenGLContext.ui.metrics import FontMetrics


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


@pytest.fixture
def overlay():
    return DebugOverlay(margin=0)


class TestFormatValue:
    def test_a_flag_reads_as_a_word(self):
        assert format_value(True) == 'yes'
        assert format_value(False) == 'no'

    def test_a_float_is_cut_to_something_readable(self):
        assert format_value(1.0 / 3.0) == '0.33'

    def test_a_whole_float_keeps_no_pointless_decimals(self):
        assert format_value(60.0) == '60'

    def test_an_integer_is_itself(self):
        assert format_value(4096) == '4096'

    def test_a_vector_is_its_components(self):
        assert format_value((1.5, -2.0, 0.25)) == '1.5, -2, 0.25'

    def test_nothing_reads_as_a_dash(self):
        assert format_value(None) == '-'

    def test_anything_else_is_its_own_text(self):
        assert format_value('core') == 'core'


class TestRegistration:
    def test_a_registered_provider_becomes_a_section(self, overlay):
        overlay.register('Map', lambda: [('name', 'q3dm17')])
        assert [section.title for section in overlay.sections()] == ['Map']

    def test_the_rows_are_what_the_provider_returned(self, overlay):
        overlay.register('Map', lambda: [('name', 'q3dm17'), ('family', 'q3')])
        assert overlay.sections()[0].rows == [('name', 'q3dm17'),
                                              ('family', 'q3')]

    def test_a_provider_may_answer_with_a_mapping(self, overlay):
        overlay.register('Map', lambda: {'name': 'q3dm17'})
        assert overlay.sections()[0].rows == [('name', 'q3dm17')]

    def test_values_are_formatted_on_the_way_out(self, overlay):
        overlay.register('Frame', lambda: [('rate', 59.94), ('vsync', True)])
        assert overlay.sections()[0].rows == [('rate', '59.94'),
                                              ('vsync', 'yes')]

    def test_sections_come_out_in_the_order_they_asked_for(self, overlay):
        overlay.register('Last', lambda: [('a', 1)], order=90)
        overlay.register('First', lambda: [('b', 2)], order=10)
        assert [section.title for section in overlay.sections()] \
            == ['First', 'Last']

    def test_equal_orders_keep_the_order_they_registered_in(self, overlay):
        overlay.register('One', lambda: [('a', 1)])
        overlay.register('Two', lambda: [('b', 2)])
        assert [section.title for section in overlay.sections()] \
            == ['One', 'Two']

    def test_a_section_can_be_taken_away_again(self, overlay):
        overlay.register('Map', lambda: [('name', 'q3dm17')])
        overlay.unregister('Map')
        assert overlay.sections() == []

    def test_registering_the_same_title_twice_replaces_it(self, overlay):
        overlay.register('Map', lambda: [('name', 'first')])
        overlay.register('Map', lambda: [('name', 'second')])
        assert overlay.sections() == [DebugSection('Map', [('name', 'second')])]

    def test_a_provider_that_raises_says_so_instead_of_taking_the_frame(
            self, overlay):
        def broken():
            raise RuntimeError('no physics world yet')
        overlay.register('Physics', broken)
        section = overlay.sections()[0]
        assert section.rows[0][0] == 'error'
        assert 'no physics world' in section.rows[0][1]

    def test_a_provider_with_nothing_to_say_is_left_out(self, overlay):
        """An empty heading is noise; a subsystem with no numbers has none."""
        overlay.register('Physics', lambda: [])
        assert overlay.sections() == []


class TestLayout:
    def rows(self, overlay, metrics):
        overlay.refresh()
        overlay.layout((800, 600), metrics)
        return overlay.panel.laidOutRows(metrics)

    def test_a_heading_and_its_rows_are_laid_out_in_order(self, overlay,
                                                          metrics):
        overlay.register('Frame', lambda: [('fps', 60), ('ms', 16)])
        laid = self.rows(overlay, metrics)
        assert [(row.label, row.heading) for row in laid] \
            == [('Frame', True), ('fps', False), ('ms', False)]

    def test_rows_run_down_the_plate(self, overlay, metrics):
        overlay.register('Frame', lambda: [('fps', 60), ('ms', 16)])
        laid = self.rows(overlay, metrics)
        assert laid[0].rect.y > laid[1].rect.y > laid[2].rect.y

    def test_the_plate_holds_every_row(self, overlay, metrics):
        overlay.register('Frame', lambda: [('fps', 60), ('ms', 16)])
        laid = self.rows(overlay, metrics)
        plate = overlay.panel.rect
        for row in laid:
            assert plate.contains(row.rect.x, row.rect.y)

    def test_it_grows_to_fit_the_widest_value(self, overlay, metrics):
        overlay.register('Map', lambda: [('name', 'short')])
        overlay.refresh()
        narrow = overlay.panel.natural_size(metrics)[0]
        overlay.unregister('Map')
        overlay.register('Map', lambda: [('name', 'a very much longer name')])
        overlay.refresh()
        assert overlay.panel.natural_size(metrics)[0] > narrow

    def test_two_sections_are_taller_than_one(self, overlay, metrics):
        overlay.register('One', lambda: [('a', 1)])
        overlay.refresh()
        single = overlay.panel.natural_size(metrics)[1]
        overlay.register('Two', lambda: [('b', 2)])
        overlay.refresh()
        assert overlay.panel.natural_size(metrics)[1] > single

    def test_an_empty_overlay_takes_no_room(self, overlay, metrics):
        overlay.refresh()
        assert overlay.panel.natural_size(metrics) == (0, 0)

    def test_ticking_refreshes_what_the_providers_say(self, overlay, metrics):
        readings = iter([[('fps', 30)], [('fps', 60)]])
        overlay.register('Frame', lambda: next(readings))
        overlay.tick(1.0)
        assert overlay.panel.sections[0].rows == [('fps', '30')]
        overlay.tick(2.0)
        assert overlay.panel.sections[0].rows == [('fps', '60')]


class TestVisibility:
    def test_it_starts_hidden_when_the_fps_display_is_disabled(self,
                                                              monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
        assert DebugOverlay.startsVisible() is False

    def test_it_starts_visible_otherwise(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', raising=False)
        assert DebugOverlay.startsVisible() is True

    def test_toggling_turns_it_on_and_off(self, overlay):
        overlay.visible = False
        assert overlay.toggle() is True
        assert overlay.visible
        assert overlay.toggle() is False
        assert not overlay.visible


class TestBuiltInProviders:
    """The providers shipped with the overlay, against stand-in contexts."""

    def test_the_frame_rate_keeps_its_decimals_so_it_does_not_jump(self):
        """A number that changes width every frame is a number that twitches.

        `_number` drops trailing zeros, which is right for a position — 512.00
        is three characters of nothing on a crowded line — and wrong for
        anything that updates sixty times a second, where 60, 59.97 and 60.1
        are three different widths in three consecutive frames.
        """
        from OpenGLContext.framecounter import FrameCounter
        from OpenGLContext.ui.debugoverlay import format_value, frame_provider

        counter = FrameCounter()
        for _index in range(10):
            counter.addFrame(1 / 60.0)

        class Context:
            frameCounter = counter

            def getViewPort(self):
                return (800, 600)

        rows = dict(frame_provider(Context())())
        for name in ('fps', 'frame ms'):
            drawn = format_value(rows[name])
            assert drawn.count('.') == 1, name
            assert len(drawn.split('.')[1]) == 2, name

    def test_a_whole_frame_rate_still_shows_its_decimals(self):
        """Exactly 60 fps must read 60.00, not 60."""
        from OpenGLContext.ui.debugoverlay import Fixed, format_value

        assert format_value(Fixed(60.0)) == '60.00'

    def test_a_fixed_number_can_ask_for_more_or_fewer_decimals(self):
        from OpenGLContext.ui.debugoverlay import Fixed, format_value

        assert format_value(Fixed(1.23456, decimals=3)) == '1.235'
        assert format_value(Fixed(1.6, decimals=0)) == '2'

    def test_an_ordinary_number_still_drops_its_trailing_zeros(self):
        """The position rows are not being changed; they are not twitching."""
        from OpenGLContext.ui.debugoverlay import format_value

        assert format_value(512.0) == '512'

    def test_the_frame_provider_reports_the_windowed_rate(self):
        from OpenGLContext.framecounter import FrameCounter
        from OpenGLContext.ui.debugoverlay import frame_provider

        counter = FrameCounter()
        for _index in range(10):
            counter.addFrame(1 / 60.0)

        class Context:
            frameCounter = counter

            def getViewPort(self):
                return (800, 600)

        rows = dict(frame_provider(Context())())
        assert rows['fps'].value == pytest.approx(60.0, rel=0.05)
        assert rows['viewport'] == '800x600'

    def test_the_frame_provider_survives_a_context_with_no_counter(self):
        from OpenGLContext.ui.debugoverlay import frame_provider

        class Context:
            frameCounter = None

            def getViewPort(self):
                return (0, 0)

        assert dict(frame_provider(Context())())['fps'] == 0

    def test_the_render_provider_reports_the_features_in_use(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.ui.debugoverlay import render_provider

        class Context:
            contextDefinition = ContextDefinition(shadows=True, bloom=False)
            coreProfile = True

        rows = dict(render_provider(Context())())
        assert rows['profile'] == 'core'
        assert rows['shadows'] is True
        assert rows['bloom'] is False

    def test_the_render_provider_counts_what_the_pass_drew(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.passes.renderstats import RenderStats
        from OpenGLContext.ui.debugoverlay import render_provider

        stats = RenderStats()
        stats.shapes = 120
        stats.instanceGroups = 3
        stats.instances = 90
        stats.draws = 33

        class Context:
            contextDefinition = ContextDefinition()
            coreProfile = True
            renderStats = stats

        rows = dict(render_provider(Context())())
        assert rows['shapes'] == 120
        assert rows['draws'] == 33
        assert rows['instanced'] == '90 in 3 groups'

    def test_the_platform_provider_reports_where_the_camera_is(self):
        from OpenGLContext.ui.debugoverlay import platform_provider

        class Platform:
            position = (1.0, 2.0, 3.0)

        class Context:
            def getViewPlatform(self):
                return Platform()

        rows = dict(platform_provider(Context())())
        assert rows['position'] == (1.0, 2.0, 3.0)

    def test_the_physics_provider_counts_bodies_and_contacts(self):
        from OpenGLContext.ui.debugoverlay import physics_provider

        class World:
            bodies = [object(), object()]
            contacts = [object()]

        rows = dict(physics_provider(lambda: World())())
        assert rows['bodies'] == 2
        assert rows['contacts'] == 1

    def test_the_physics_provider_says_nothing_with_no_world(self):
        from OpenGLContext.ui.debugoverlay import physics_provider

        assert physics_provider(lambda: None)() == []


    def test_the_audio_provider_reports_what_the_engine_is_doing(self):
        """The one subsystem you cannot see, so the overlay is where it shows.

        A sound that is not audible has four possible causes -- audio off, no
        device, no voice, or a gain of nothing -- and they are indistinguishable
        by listening.
        """
        from omi_audio.device import NullDevice
        from omi_audio.engine import AudioEngine

        from OpenGLContext.audio import scene as audioscene
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.ui.debugoverlay import audio_provider

        class Context:
            contextDefinition = ContextDefinition()

        context = Context()
        engine = AudioEngine(device=NullDevice(sample_rate=8000), voices=4)
        try:
            audioscene._engines[context] = engine
            rows = dict(audio_provider(context)())
            assert rows['voices'] == 0
            assert rows['audio']
        finally:
            audioscene.close(context)

    def test_the_audio_provider_says_a_context_with_no_engine_is_idle(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.ui.debugoverlay import audio_provider

        class Context:
            contextDefinition = ContextDefinition()

        assert dict(audio_provider(Context())())['audio'] == 'idle'

    def test_the_audio_provider_survives_a_context_with_no_definition(self):
        from OpenGLContext.ui.debugoverlay import audio_provider

        class Context:
            pass

        assert audio_provider(Context())() == []

    def test_the_default_sections_include_audio(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.ui.debugoverlay import (
            DebugOverlay, install_default_providers,
        )

        class Context:
            contextDefinition = ContextDefinition()
            coreProfile = True
            frameCounter = None

            def getViewPort(self):
                return (0, 0)

            def getViewPlatform(self):
                return None

        overlay = DebugOverlay()
        install_default_providers(overlay, Context())
        assert 'Audio' in [section.title for section in overlay.sections()]


class TestTheLoopProvider:
    """The section that reports what the frame rate structurally cannot.

    The frame counter times the inside of OnDraw; these rows time the whole
    iteration and divide it among its phases, so a loop that spends most of a
    second in its idle callback says so instead of reading as sixty healthy
    frames.
    """

    @staticmethod
    def _traced(iterations):
        """A context whose loop trace has run ``iterations`` -- [(phase, s)...]."""
        from OpenGLContext.looptrace import LoopTrace

        clock = _FakeClock()
        trace = LoopTrace(stall_ms=50.0, clock=clock)
        for phases in iterations:
            with trace.iteration():
                for name, seconds in phases:
                    with trace.phase(name):
                        clock.advance(seconds)

        class Context:
            loopTrace = trace

        return Context()

    def test_the_rate_is_wall_clock_not_the_renderers_own(self):
        from OpenGLContext.ui.debugoverlay import loop_provider

        context = self._traced([[('draw', 0.100)]] * 10)
        rows = dict(loop_provider(context)())
        assert rows['loop fps'].value == pytest.approx(10.0)
        assert rows['loop ms'].value == pytest.approx(100.0)

    def test_the_worst_iteration_is_reported_beside_the_median(self):
        from OpenGLContext.ui.debugoverlay import loop_provider

        context = self._traced([[('draw', 0.020)]] * 30
                               + [[('idle', 1.000)]]
                               + [[('draw', 0.020)]] * 30)
        rows = dict(loop_provider(context)())
        assert rows['loop ms'].value == pytest.approx(20.0)
        assert rows['worst ms'].value == pytest.approx(1000.0)

    def test_stalls_are_counted(self):
        from OpenGLContext.ui.debugoverlay import loop_provider

        context = self._traced([[('draw', 0.020)]] * 5
                               + [[('idle', 0.500)]] * 3)
        assert dict(loop_provider(context)())['stalls'] == 3

    def test_the_last_stall_names_the_phase_that_ate_it(self):
        from OpenGLContext.ui.debugoverlay import loop_provider

        context = self._traced([[('poll', 0.001), ('idle', 0.900),
                                 ('draw', 0.010)]])
        assert dict(loop_provider(context)())['last stall'] == 'idle 900ms'

    def test_a_loop_that_has_never_stalled_says_nothing_about_stalls(self):
        from OpenGLContext.ui.debugoverlay import loop_provider

        context = self._traced([[('draw', 0.005)]] * 10)
        rows = dict(loop_provider(context)())
        assert rows['stalls'] == 0
        assert 'last stall' not in rows

    def test_every_phase_gets_its_own_row(self):
        from OpenGLContext.ui.debugoverlay import loop_provider

        context = self._traced([[('poll', 0.001), ('idle', 0.010),
                                 ('draw', 0.005)]])
        rows = dict(loop_provider(context)())
        assert rows['idle'].value == pytest.approx(10.0)
        assert rows['draw'].value == pytest.approx(5.0)
        assert rows['poll'].value == pytest.approx(1.0)

    def test_the_phases_come_out_worst_first(self):
        """A crowded panel should read top-down as most-to-least expensive."""
        from OpenGLContext.ui.debugoverlay import loop_provider

        context = self._traced([[('poll', 0.001), ('idle', 0.010),
                                 ('draw', 0.005)]])
        names = [name for name, _value in loop_provider(context)()]
        assert names[-3:] == ['idle', 'draw', 'poll']

    def test_a_backend_that_does_not_drive_the_loop_gets_no_section(self):
        """GLUT, pygame and wx run their own loops and never open an iteration.

        Rows of zeroes would read as a loop that is doing nothing, which is a
        worse answer than no rows at all.
        """
        from OpenGLContext.ui.debugoverlay import loop_provider

        assert loop_provider(self._traced([])) () == []

    def test_a_context_with_no_trace_at_all_is_not_an_error(self):
        from OpenGLContext.ui.debugoverlay import loop_provider

        class Context:
            loopTrace = None

        assert loop_provider(Context())() == []

    def test_the_section_is_registered_by_default(self):
        from OpenGLContext.ui.debugoverlay import (
            DebugOverlay, install_default_providers,
        )
        from OpenGLContext.looptrace import LoopTrace

        # A trace that has actually run, since a loop nobody drives is left out
        # on purpose and would make this pass for the wrong reason.
        trace = LoopTrace()
        with trace.iteration():
            with trace.phase('draw'):
                pass

        class Context:
            loopTrace = trace
            contextDefinition = None
            frameCounter = None

            def getViewPort(self):
                return (800, 600)

            def getViewPlatform(self):
                return None

        overlay = DebugOverlay(margin=0)
        install_default_providers(overlay, Context())
        titles = [section.title for section in overlay.sections()]
        assert 'Frame' in titles
        # Directly under Frame: the two are read together, and a reader who has
        # to hunt down the panel to compare them will not compare them.
        assert titles.index('Loop') == titles.index('Frame') + 1


class TestTheSimulationProvider:
    """Whether a background physics thread is getting the turns it asked for.

    Registered by an application that runs one; the bodies-and-contacts section
    reports on the world, and this reports on the thread stepping it.
    """

    class Simulation:
        sim_hz = 120.0
        steps = 4200
        dropped = 0

        def rate(self):
            return 119.6

    def test_the_achieved_rate_is_reported_against_the_one_asked_for(self):
        from OpenGLContext.ui.debugoverlay import simulation_provider

        rows = dict(simulation_provider(lambda: self.Simulation())())
        assert rows['sim hz'].value == pytest.approx(119.6)
        assert rows['asked'].value == pytest.approx(120.0)
        assert rows['steps'] == 4200

    def test_dropped_ticks_are_reported_only_when_there_are_some(self):
        """Zero is the healthy answer, and a healthy row is a row not worth space."""
        from OpenGLContext.ui.debugoverlay import simulation_provider

        assert 'dropped' not in dict(simulation_provider(
            lambda: self.Simulation())())

        class Starved(self.Simulation):
            dropped = 91

        rows = dict(simulation_provider(lambda: Starved())())
        assert rows['dropped'] == 91

    def test_no_simulation_means_no_section(self):
        from OpenGLContext.ui.debugoverlay import simulation_provider

        assert simulation_provider(lambda: None)() == []


class _FakeClock:
    """A clock the test advances by hand, so timings are exact, not flaky."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
