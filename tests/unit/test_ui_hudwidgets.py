"""HUD primitives: anchoring, crosshair geometry, meters and the message queue.

All of it is arithmetic over a viewport and a font, so none of it needs a
window: a layer is laid out, and what comes back is rectangles.
"""

import pytest

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.hudwidgets import (
    CIRCLE, CROSS, CROSS_DOT, DOT, NONE,
    BarMeter, Crosshair, HUDGroup, HUDLayer, MessageQueue, Readout, place,
)
from OpenGLContext.ui.metrics import FontMetrics


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


def colour(value):
    """A colour field as plain floats, so two of them can be compared."""
    return tuple(float(component) for component in value)


@pytest.fixture
def doubled():
    """The same font at twice the size, for the interface-scale checks."""
    return FontMetrics(char_width=16, char_height=32, line_gap=4, scale=2.0)


class TestPlace:
    """Where an anchored box of a given size lands inside a container."""

    container = Rect(0, 0, 200, 100)

    def test_centre_puts_it_in_the_middle(self):
        assert place(self.container, (20, 10), 'center', (0, 0)) \
            == Rect(90, 45, 20, 10)

    def test_top_left_sits_against_the_top_left(self):
        assert place(self.container, (20, 10), 'top-left', (0, 0)) \
            == Rect(0, 90, 20, 10)

    def test_bottom_right_sits_against_the_bottom_right(self):
        assert place(self.container, (20, 10), 'bottom-right', (0, 0)) \
            == Rect(180, 0, 20, 10)

    def test_top_is_centred_horizontally(self):
        assert place(self.container, (20, 10), 'top', (0, 0)) \
            == Rect(90, 90, 20, 10)

    def test_offset_moves_it_up_and_right(self):
        """+y is up, as it is everywhere else in this coordinate system."""
        assert place(self.container, (20, 10), 'bottom-left', (5, 7)) \
            == Rect(5, 7, 20, 10)

    def test_an_unknown_anchor_is_treated_as_the_centre(self):
        assert place(self.container, (20, 10), 'nowhere', (0, 0)) \
            == place(self.container, (20, 10), 'center', (0, 0))


class TestHUDLayer:
    def test_it_fills_the_viewport(self, metrics):
        layer = HUDLayer(margin=0)
        layer.layout((800, 600), metrics)
        assert layer.rect == Rect(0, 0, 800, 600)

    def test_the_margin_keeps_children_clear_of_the_edge(self, metrics):
        readout = Readout(value='100', anchor='bottom-left')
        layer = HUDLayer(children=[readout], margin=10)
        layer.layout((800, 600), metrics)
        assert readout.rect.x == 10
        assert readout.rect.y == 10

    def test_the_margin_is_in_reference_pixels(self, doubled):
        """A margin authored at 10 is 20 real pixels on a doubled interface."""
        readout = Readout(value='100', anchor='bottom-left')
        layer = HUDLayer(children=[readout], margin=10)
        layer.layout((800, 600), doubled)
        assert readout.rect.x == 20

    def test_each_child_is_placed_by_its_own_anchor(self, metrics):
        left = Readout(value='100', anchor='bottom-left')
        right = Readout(value='25', anchor='bottom-right')
        layer = HUDLayer(children=[left, right], margin=0)
        layer.layout((800, 600), metrics)
        assert left.rect.x == 0
        assert right.rect.right == 800

    def test_a_child_with_no_anchor_is_given_the_whole_layer(self, metrics):
        """An ordinary container still lays out the way it always does."""
        from OpenGLContext.ui.layout import Column
        column = Column(children=[Readout(value='1')])
        layer = HUDLayer(children=[column], margin=0)
        layer.layout((800, 600), metrics)
        assert column.rect == Rect(0, 0, 800, 600)

    def test_an_invisible_child_is_not_placed(self, metrics):
        hidden = Readout(value='100', anchor='bottom-left', visible=False)
        layer = HUDLayer(children=[hidden], margin=0)
        layer.layout((800, 600), metrics)
        assert hidden.rect == Rect(0, 0, 0, 0)

    def test_nothing_in_a_hud_can_be_clicked(self, metrics):
        """A HUD is a picture, not a screen: it never takes the pointer."""
        readout = Readout(value='100', anchor='center')
        layer = HUDLayer(children=[readout], margin=0)
        layer.layout((800, 600), metrics)
        assert layer.widget_at(400, 300) is None

    def test_a_group_carries_its_children_to_one_corner(self, metrics):
        one, two = Readout(value='100'), Readout(value='50')
        group = HUDGroup(children=[one, two], anchor='bottom-left')
        layer = HUDLayer(children=[group], margin=0)
        layer.layout((800, 600), metrics)
        assert group.rect.x == 0
        assert group.rect.y == 0
        # A group stacks downward, so the first child is the upper one.
        assert one.rect.y > two.rect.y

    def test_ticking_reaches_the_children_that_want_a_clock(self, metrics):
        messages = MessageQueue(duration=1.0, fade=0.0)
        layer = HUDLayer(children=[messages])
        messages.post('picked up a shotgun', now=100.0)
        layer.tick(100.5)
        assert messages.entries(100.5)
        layer.tick(102.0)
        assert not messages.entries(102.0)


class TestCrosshair:
    def test_a_cross_is_four_arms_around_a_gap(self, metrics):
        cross = Crosshair(shape=CROSS, gap=4, length=8, thickness=2)
        cross.arrange(Rect(0, 0, 40, 40), metrics)
        assert len(cross.segments(metrics)) == 4

    def test_the_arms_leave_the_gap_clear(self, metrics):
        cross = Crosshair(shape=CROSS, gap=4, length=8, thickness=2)
        cross.arrange(Rect(0, 0, 40, 40), metrics)
        centre_x, centre_y = cross.rect.centre
        for segment in cross.segments(metrics):
            assert not segment.contains(centre_x, centre_y)

    def test_spread_widens_the_gap(self, metrics):
        tight = Crosshair(shape=CROSS, gap=4, length=8, thickness=2)
        wide = Crosshair(shape=CROSS, gap=4, length=8, thickness=2, spread=6)
        for cross in (tight, wide):
            cross.arrange(Rect(0, 0, 60, 60), metrics)
        assert wide.natural_size(metrics)[0] > tight.natural_size(metrics)[0]

    def test_a_dot_is_one_square(self, metrics):
        dot = Crosshair(shape=DOT, dotSize=3)
        dot.arrange(Rect(0, 0, 40, 40), metrics)
        assert len(dot.segments(metrics)) == 1

    def test_a_cross_with_a_dot_has_both(self, metrics):
        cross = Crosshair(shape=CROSS_DOT, gap=4, length=8, thickness=2)
        cross.arrange(Rect(0, 0, 40, 40), metrics)
        assert len(cross.segments(metrics)) == 5

    def test_a_circle_is_drawn_from_four_arcs(self, metrics):
        circle = Crosshair(shape=CIRCLE, gap=6, thickness=2)
        circle.arrange(Rect(0, 0, 40, 40), metrics)
        assert len(circle.segments(metrics)) == 4

    def test_shape_none_draws_nothing(self, metrics):
        nothing = Crosshair(shape=NONE)
        nothing.arrange(Rect(0, 0, 40, 40), metrics)
        assert nothing.segments(metrics) == []

    def test_the_arms_grow_with_the_interface_scale(self, metrics, doubled):
        cross = Crosshair(shape=CROSS, gap=4, length=8, thickness=2)
        assert (cross.natural_size(doubled)[0]
                == cross.natural_size(metrics)[0] * 2)

    def test_a_hit_shows_marks_and_then_stops(self, metrics):
        cross = Crosshair(shape=CROSS, hitDuration=0.5)
        cross.arrange(Rect(0, 0, 40, 40), metrics)
        assert cross.hitMarks(metrics) == []
        cross.hit(now=10.0)
        cross.tick(10.2)
        assert len(cross.hitMarks(metrics)) == 4
        cross.tick(10.6)
        assert cross.hitMarks(metrics) == []


class TestBarMeter:
    def test_the_fill_is_the_fraction_of_the_track(self, metrics):
        bar = BarMeter(value=50, maximum=200, barWidth=100, barHeight=10)
        bar.arrange(Rect(0, 0, 100, 40), metrics)
        assert bar.fillRect(metrics).width == 25

    def test_the_track_takes_the_room_the_meter_was_given(self, metrics):
        """Stretched in a group, the bar stretches with it."""
        bar = BarMeter(value=50, maximum=100, barWidth=100, barHeight=10)
        bar.arrange(Rect(0, 0, 200, 40), metrics)
        assert bar.barRect(metrics).width == 200

    def test_an_empty_bar_fills_nothing(self, metrics):
        bar = BarMeter(value=0, maximum=100, barWidth=100, barHeight=10)
        bar.arrange(Rect(0, 0, 100, 40), metrics)
        assert bar.fillRect(metrics).empty

    def test_more_than_the_maximum_does_not_overflow_the_bar(self, metrics):
        bar = BarMeter(value=250, maximum=100, barWidth=100, barHeight=10)
        bar.arrange(Rect(0, 0, 100, 40), metrics)
        assert bar.fillRect(metrics).width == 100

    def test_a_label_leaves_the_bar_less_room(self, metrics):
        bar = BarMeter(value=100, maximum=100, barWidth=100, barHeight=10,
                       label='ARMOUR')
        bar.arrange(Rect(0, 0, 200, 40), metrics)
        assert bar.barRect(metrics).x > 0

    def test_a_maximum_of_zero_is_not_a_division(self, metrics):
        bar = BarMeter(value=5, maximum=0, barWidth=100, barHeight=10)
        assert bar.fraction == 0.0

    def test_the_colour_crosses_the_warning_threshold(self, metrics):
        skin = HUDLayer().activeSkin()
        healthy = BarMeter(value=100, maximum=100)
        warned = BarMeter(value=40, maximum=100)
        critical = BarMeter(value=10, maximum=100)
        assert colour(healthy.stateColour(skin)) == colour(skin.hudGood)
        assert colour(warned.stateColour(skin)) == colour(skin.hudWarn)
        assert colour(critical.stateColour(skin)) == colour(skin.hudCritical)

    def test_an_explicit_colour_overrides_the_thresholds(self, metrics):
        skin = HUDLayer().activeSkin()
        bar = BarMeter(value=1, maximum=100, color=(1, 0, 1, 1))
        assert colour(bar.stateColour(skin)) == (1.0, 0.0, 1.0, 1.0)

    def test_a_label_widens_the_meter(self, metrics):
        bare = BarMeter(value=1, maximum=1, barWidth=100, barHeight=10)
        labelled = BarMeter(value=1, maximum=1, barWidth=100, barHeight=10,
                            label='ARMOUR')
        assert (labelled.natural_size(metrics)[0]
                > bare.natural_size(metrics)[0])


class TestReadout:
    def test_it_measures_its_own_text(self, metrics):
        readout = Readout(label='AMMO', value='42')
        width, height = readout.natural_size(metrics)
        assert width >= metrics.text_width('AMMO 42')
        assert height >= metrics.char_height

    def test_the_value_can_be_told_it_is_low(self, metrics):
        skin = HUDLayer().activeSkin()
        readout = Readout(value='2', critical=True)
        assert colour(readout.valueColour(skin)) == colour(skin.hudCritical)

    def test_an_icon_reserves_room_beside_the_text(self, metrics):
        from OpenGLContext.ui.skin import NineSlice
        bare = Readout(value='42')
        iconed = Readout(value='42', icon=NineSlice(url=['nothing.png']),
                         iconSize=24)
        assert (iconed.natural_size(metrics)[0]
                > bare.natural_size(metrics)[0])


class TestMessageQueue:
    def test_a_posted_message_is_shown(self):
        queue = MessageQueue(duration=4.0)
        queue.post('you have the flag', now=0.0)
        assert [text for text, _colour in queue.entries(1.0)] \
            == ['you have the flag']

    def test_a_message_expires(self):
        queue = MessageQueue(duration=4.0)
        queue.post('you have the flag', now=0.0)
        assert queue.entries(5.0) == []

    def test_it_fades_towards_the_end(self):
        queue = MessageQueue(duration=4.0, fade=2.0)
        queue.post('gone soon', now=0.0)
        solid = queue.entries(1.0)[0][1][3]
        faint = queue.entries(3.0)[0][1][3]
        assert solid == pytest.approx(1.0)
        assert 0.0 < faint < solid

    def test_the_newest_message_is_first(self):
        queue = MessageQueue(duration=4.0)
        queue.post('one', now=0.0)
        queue.post('two', now=0.5)
        assert [text for text, _colour in queue.entries(1.0)] == ['two', 'one']

    def test_it_keeps_only_as_many_as_it_can_show(self):
        queue = MessageQueue(duration=100.0, capacity=2)
        for index in range(5):
            queue.post('message %d' % index, now=float(index))
        assert len(queue.entries(5.0)) == 2

    def test_ticking_drops_what_has_expired(self):
        queue = MessageQueue(duration=1.0)
        queue.post('brief', now=0.0)
        queue.tick(0.5)
        assert queue.messages
        queue.tick(2.0)
        assert not queue.messages

    def test_it_grows_to_hold_what_it_is_showing(self, metrics):
        queue = MessageQueue(duration=100.0)
        empty = queue.natural_size(metrics)[1]
        queue.post('a message', now=0.0)
        queue.tick(0.0)
        assert queue.natural_size(metrics)[1] > empty


class FakeRenderer:
    """Records what a widget asked to have drawn, in order."""

    def __init__(self, metrics, skin):
        self.metrics = metrics
        self.skin = skin
        self.rects = []
        self.texts = []

    def rect(self, rect, colour):
        self.rects.append((rect, colour(colour) if callable(colour) else
                           tuple(float(v) for v in colour)))

    def textIn(self, rect, text, colour, align='left', pad=0):
        self.texts.append((rect, text, tuple(float(v) for v in colour)))

    def ninepatch(self, rect, image):
        return False


class TestLegibility:
    """A HUD is read over a world whose colours nobody controls."""

    def renderer(self, layer, metrics):
        return FakeRenderer(metrics, layer.activeSkin())

    def test_a_reticule_is_outlined_so_it_reads_on_white(self, metrics):
        cross = Crosshair(shape=CROSS, gap=4, length=8, thickness=2)
        cross.arrange(Rect(0, 0, 40, 40), metrics)
        outlines = cross.outlineSegments(metrics)
        assert len(outlines) == len(cross.segments(metrics))
        for segment, outline in zip(cross.segments(metrics), outlines,
                                    strict=True):
            assert outline.width > segment.width
            assert outline.height > segment.height

    def test_the_outline_can_be_turned_off(self, metrics):
        cross = Crosshair(shape=CROSS, outline=False)
        cross.arrange(Rect(0, 0, 40, 40), metrics)
        assert cross.outlineSegments(metrics) == []

    def test_the_outline_is_drawn_under_the_reticule(self, metrics):
        layer = HUDLayer(children=[Crosshair(shape=DOT, dotSize=3)])
        layer.layout((100, 100), metrics)
        renderer = self.renderer(layer, metrics)
        layer.layoutChildren()[0].paint(renderer)
        assert len(renderer.rects) == 2
        outline, mark = renderer.rects
        assert outline[0].width > mark[0].width

    def test_hud_text_is_drawn_over_its_own_shadow(self, metrics):
        layer = HUDLayer()
        renderer = self.renderer(layer, metrics)
        from OpenGLContext.ui.hudwidgets import hud_text
        hud_text(renderer, Rect(0, 0, 100, 16), 'AMMO', (1, 1, 1, 1))
        assert [text for _rect, text, _colour in renderer.texts] \
            == ['AMMO', 'AMMO']
        shadow, front = renderer.texts
        assert shadow[0] != front[0], 'the shadow is not offset'
        assert colour(shadow[2]) == colour(layer.activeSkin().hudShadow)

    def test_a_skin_with_no_shadow_draws_the_text_once(self, metrics):
        from OpenGLContext.ui.hudwidgets import hud_text
        layer = HUDLayer()
        layer.activeSkin().hudShadow = (0, 0, 0, 0)
        renderer = self.renderer(layer, metrics)
        hud_text(renderer, Rect(0, 0, 100, 16), 'AMMO', (1, 1, 1, 1))
        assert len(renderer.texts) == 1

    def test_a_meter_s_label_and_value_are_shadowed_too(self, metrics):
        layer = HUDLayer(children=[BarMeter(label='HEALTH', value=100,
                                            maximum=100)])
        layer.layout((300, 100), metrics)
        renderer = self.renderer(layer, metrics)
        layer.layoutChildren()[0].paint(renderer)
        assert len(renderer.texts) == 4, 'label and value, each with a shadow'
