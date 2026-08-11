"""The overlay grows with the window: font size, widget sizes, spacing.

A settings screen laid out in fixed pixels is a screen that is comfortable at
one resolution and unusable at another.  These are the pieces that make the
whole thing scale together -- the font size chosen for a window, the factor
that carries from the font to every measurement in the skin, and the panel's
maximum width, which is what stops a dialog stretching across a 4K display.
"""

import pytest

from OpenGLContext.ui import metrics as uimetrics
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.layout import Column
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.session import nodes_equal
from OpenGLContext.ui.skin import DEFAULT_SKIN, Skin
from OpenGLContext.ui.widgets import Button, Label


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


class TestChoosingAFontSize:
    def test_a_1080p_window_gets_the_reference_size(self):
        assert uimetrics.font_size_for(1080) == uimetrics.REFERENCE_FONT_SIZE

    def test_a_4k_window_gets_roughly_twice_the_reference(self):
        assert uimetrics.font_size_for(2160) == 32

    def test_a_small_window_is_not_shrunk_below_the_reference(self):
        """Text sized down for a 720p window is unreadable, not merely small."""
        assert uimetrics.font_size_for(720) == uimetrics.REFERENCE_FONT_SIZE

    def test_the_player_scale_multiplies_the_automatic_one(self):
        assert uimetrics.font_size_for(1080, 1.5) > uimetrics.font_size_for(1080)

    def test_it_only_ever_asks_for_a_size_that_exists(self):
        from OpenGLContext.scenegraph.text import fonts
        available = set(fonts.get_available_sizes())
        for height in range(240, 4321, 137):
            for scale in (0.5, 0.75, 1.0, 1.25, 2.0, 4.0):
                assert uimetrics.font_size_for(height, scale) in available

    def test_an_absurd_scale_is_capped_by_the_largest_atlas(self):
        from OpenGLContext.scenegraph.text import fonts
        assert uimetrics.font_size_for(2160, 10.0) == max(
            fonts.get_available_sizes())


class TestTheScaleCarriedOnTheMetrics:
    def test_hand_built_metrics_are_unscaled(self, metrics):
        """So a layout test states pixel sizes and means them."""
        assert metrics.scale == 1.0

    def test_a_measurement_is_rounded_to_whole_pixels(self):
        assert FontMetrics(8, 16, scale=1.5).pixels(5) == 8

    def test_the_reference_font_measures_as_scale_one(self):
        rendered = _FakeRenderer(uimetrics.REFERENCE_FONT_SIZE)
        assert uimetrics.metrics_for(rendered).scale == 1.0

    def test_a_bigger_font_scales_everything_with_it(self):
        rendered = _FakeRenderer(32)
        assert uimetrics.metrics_for(rendered).scale > 1.5

    def test_the_gap_between_lines_grows_with_the_font(self):
        small = uimetrics.metrics_for(_FakeRenderer(uimetrics.REFERENCE_FONT_SIZE))
        large = uimetrics.metrics_for(_FakeRenderer(32))
        assert large.line_gap > small.line_gap


class _FakeRenderer:
    """A text renderer's measurements, taken from the real shipped atlas."""

    def __init__(self, size):
        from OpenGLContext.scenegraph.text import fonts
        _actual, module = fonts.get_closest_atlas(size)
        self.char_width = module.char_width
        self.char_height = module.char_height


class TestScalingASkin:
    def test_pixel_measurements_are_multiplied(self):
        assert DEFAULT_SKIN.scaled(2.0).panelPadding == DEFAULT_SKIN.panelPadding * 2

    def test_character_measurements_are_left_alone(self):
        """Button padding is in characters, so the text already carries it."""
        assert (DEFAULT_SKIN.scaled(2.0).buttonPaddingX
                == DEFAULT_SKIN.buttonPaddingX)

    def test_colours_are_left_alone(self):
        assert tuple(DEFAULT_SKIN.scaled(2.0).panelFill) == tuple(
            DEFAULT_SKIN.panelFill)

    def test_artwork_is_shared_rather_than_copied(self):
        from OpenGLContext.ui.skin import NineSlice
        art = NineSlice(url=['button.png'])
        skin = Skin(buttonImage=art)
        assert skin.scaled(2.0).buttonImage is art

    def test_scaling_by_one_hands_back_the_same_skin(self):
        assert DEFAULT_SKIN.scaled(1.0) is DEFAULT_SKIN

    def test_the_original_is_not_touched(self):
        before = float(DEFAULT_SKIN.panelPadding)
        DEFAULT_SKIN.scaled(3.0)
        assert float(DEFAULT_SKIN.panelPadding) == before


class TestAPanelPaintsWithTheScaledSkin:
    def test_the_panel_scales_its_skin_when_it_is_laid_out(self):
        panel = Panel(title='x', children=[Column(children=[Label(text='a')])])
        panel.layout((800, 600), FontMetrics(8, 16, 2, scale=2.0))
        assert panel.activeSkin().panelPadding == DEFAULT_SKIN.panelPadding * 2

    def test_a_widget_inside_it_sees_the_same_skin(self):
        button = Button(text='ok')
        panel = Panel(children=[Column(children=[button])])
        panel.layout((800, 600), FontMetrics(8, 16, 2, scale=2.0))
        assert button.activeSkin() is panel.activeSkin()

    def test_an_unscaled_layout_leaves_the_skin_as_authored(self, metrics):
        panel = Panel(children=[Column(children=[Label(text='a')])])
        panel.layout((800, 600), metrics)
        assert nodes_equal(panel.activeSkin(), DEFAULT_SKIN)

    def test_a_widget_with_no_panel_falls_back_to_the_default(self):
        assert nodes_equal(Button(text='ok').activeSkin(), DEFAULT_SKIN)

    def test_a_panel_gets_its_own_copy_of_the_default(self):
        """A game adjusting one screen's colours must not adjust every screen."""
        one = Panel(children=[Column(children=[Label(text='a')])])
        other = Panel(children=[Column(children=[Label(text='b')])])
        assert one.activeSkin() is not other.activeSkin()
        assert one.activeSkin() is not DEFAULT_SKIN

    def test_changing_one_panels_skin_leaves_the_others_alone(self, metrics):
        one = Panel(children=[Column(children=[Label(text='a')])])
        other = Panel(children=[Column(children=[Label(text='b')])])
        one.layout((800, 600), metrics)
        other.layout((800, 600), metrics)
        one.activeSkin().panelPadding = 99.0
        assert float(other.activeSkin().panelPadding) != 99.0
        assert float(DEFAULT_SKIN.panelPadding) != 99.0

    def test_the_padding_a_scaled_panel_keeps_grows_with_it(self, metrics):
        """Same window, same contents: the frame around them gets thicker."""
        plain = Panel(fill=True, children=[Column(children=[Label(text='a')])])
        plain.layout((800, 600), metrics)
        scaled = Panel(fill=True, children=[Column(children=[Label(text='a')])])
        scaled.layout((800, 600), FontMetrics(8, 16, 2, scale=2.0))
        assert scaled.contentRect().width < plain.contentRect().width


class TestAPanelHasAMaximumWidth:
    """``preferredColumns`` caps a filled panel as well as sizing a dialog."""

    def test_a_filled_panel_stops_at_its_preferred_width(self, metrics):
        panel = Panel(fill=True, preferredColumns=40,
                      children=[Column(children=[Label(text='a')])])
        panel.layout((4000, 1000), metrics)
        assert panel.rect.width < 4000 // 2

    def test_it_is_centred_in_the_window(self, metrics):
        panel = Panel(fill=True, preferredColumns=40,
                      children=[Column(children=[Label(text='a')])])
        panel.layout((4000, 1000), metrics)
        left = panel.rect.x
        right = 4000 - panel.rect.right
        assert abs(left - right) <= 1

    def test_it_still_fills_the_height(self, metrics):
        panel = Panel(fill=True, preferredColumns=40, margin=10,
                      children=[Column(children=[Label(text='a')])])
        panel.layout((4000, 1000), metrics)
        assert panel.rect.height == 1000 - 20

    def test_a_narrow_window_is_filled_edge_to_edge(self, metrics):
        panel = Panel(fill=True, preferredColumns=40, margin=10,
                      children=[Column(children=[Label(text='a')])])
        panel.layout((300, 1000), metrics)
        assert panel.rect.width == 300 - 20

    def test_a_filled_panel_with_no_preference_still_fills(self, metrics):
        panel = Panel(fill=True, margin=10,
                      children=[Column(children=[Label(text='a')])])
        panel.layout((4000, 1000), metrics)
        assert panel.rect.width == 4000 - 20

    def test_the_cap_is_in_characters_so_it_grows_with_the_font(self):
        wide = Panel(fill=True, preferredColumns=40,
                     children=[Column(children=[Label(text='a')])])
        wide.layout((4000, 1000), FontMetrics(16, 32, 4, scale=2.0))
        narrow = Panel(fill=True, preferredColumns=40,
                       children=[Column(children=[Label(text='a')])])
        narrow.layout((4000, 1000), FontMetrics(8, 16, 2))
        assert wide.rect.width == narrow.rect.width * 2


class TestTheContextChoosesTheSize:
    """What a window's height and the player's preference add up to."""

    @pytest.fixture
    def context(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.ui.overlay import OverlayMixin
        from OpenGLContext.ui.screen import ScreenMixin

        class World:
            viewport = (1920, 1080)

            def __init__(self):
                self.contextDefinition = ContextDefinition()

            def getViewPort(self):
                return self.viewport

        class Context(OverlayMixin, ScreenMixin, World):
            pass

        return Context()

    def test_a_1080p_window_draws_at_the_reference_size(self, context):
        assert context.overlayFontSize() == uimetrics.REFERENCE_FONT_SIZE

    def test_a_4k_window_draws_larger(self, context):
        context.viewport = (3840, 2160)
        assert context.overlayFontSize() > uimetrics.REFERENCE_FONT_SIZE

    def test_the_players_preference_is_honoured(self, context):
        context.contextDefinition.uiScale = 2.0
        assert context.overlayFontSize() > uimetrics.REFERENCE_FONT_SIZE

    def test_a_smaller_preference_shrinks_it(self, context):
        context.contextDefinition.uiScale = 0.5
        assert context.overlayFontSize() < uimetrics.REFERENCE_FONT_SIZE

    def test_the_default_preference_changes_nothing(self, context):
        assert context.interfaceScale() == 1.0

    def test_a_context_with_no_definition_still_answers(self, context):
        """A bare context has no settings node to ask."""
        del context.contextDefinition
        assert context.interfaceScale() == 1.0

    def test_a_preference_of_zero_is_ignored_rather_than_collapsing_the_ui(
            self, context):
        context.contextDefinition.uiScale = 0.0
        assert context.overlayFontSize() == uimetrics.REFERENCE_FONT_SIZE


class TestTheSettingIsOffered:
    def test_the_definition_carries_an_interface_scale(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        assert ContextDefinition().uiScale == 1.0

    def test_the_settings_screen_offers_it(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        assert 'uiScale' in ContextDefinition.INTERFACE_FIELDS

    def test_it_is_presented_as_a_slider_with_a_sensible_range(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        hint = ContextDefinition.UI_HINTS['uiScale']
        assert hint['minimum'] >= 0.5 and hint['maximum'] <= 3.0


class TestEveryLayoutMeasurementScales:
    """One number left in raw pixels is one thing that is wrong at 4K."""

    @pytest.fixture
    def doubled(self):
        return FontMetrics(16, 32, 4, scale=2.0)

    def test_a_margin_grows(self, doubled):
        label = Label(text='a', left=10)
        label.arrange(Rect(0, 0, 500, 60), doubled)
        assert label.rect.x == 20

    def test_a_margin_is_asked_for_when_measuring(self, doubled):
        assert Label(text='a', left=10, right=10).natural_size(doubled)[0] == (
            Label(text='a').natural_size(doubled)[0] + 40)

    def test_the_spacing_between_a_rows_children_grows(self, doubled):
        from OpenGLContext.ui.layout import Row
        one, two = Label(text='a', width=20), Label(text='b', width=20)
        Row(children=[one, two], spacing=5).arrange(
            Rect(0, 0, 500, 60), doubled)
        assert two.rect.x - one.rect.right == 10

    def test_a_boxs_padding_grows(self, doubled):
        from OpenGLContext.ui.layout import Row
        child = Label(text='a', width=20)
        Row(children=[child], padding=6).arrange(Rect(0, 0, 500, 60), doubled)
        assert child.rect.x == 12

    def test_the_margin_around_a_panel_grows(self, doubled):
        panel = Panel(fill=True, margin=10,
                      children=[Column(children=[Label(text='a')])])
        panel.layout((800, 600), doubled)
        assert panel.rect.x == 20

    def test_a_widget_is_measured_with_the_skin_it_will_be_painted_with(
            self, doubled):
        """A widget finds its skin through its parent, so the link must be set
        before it is asked how big it wants to be.

        Measuring against the unscaled default and then painting against the
        scaled one is a widget drawn to the wrong size at exactly the scale
        where being the wrong size matters.
        """
        from OpenGLContext.ui.layout import Grid
        from OpenGLContext.ui.scroll import ScrollViewport
        measured = []

        class Watched(Button):
            def content_size(self, metrics, available=None):
                measured.append(float(self.activeSkin().buttonPaddingY))
                return super(Watched, self).content_size(metrics, available)

        button = Watched(text='ok')
        panel = Panel(children=[Column(children=[
            ScrollViewport(children=[
                Grid(children=[Label(text='a'), button], columns=2)])])])
        panel.layout((900, 600), doubled)
        expected = float(panel.activeSkin().buttonPaddingY)
        assert measured and set(measured) == {expected}

    def test_a_scroll_viewport_steps_by_lines_not_by_pixels(self, doubled):
        from OpenGLContext.ui.scroll import ScrollViewport
        def viewport(metrics):
            view = ScrollViewport(children=[Label(text='x', height=4000)])
            view.arrange(Rect(0, 0, 300, 200), metrics)
            view.wheel(-1, 10, 10)
            return view.scroll
        assert viewport(doubled) == viewport(FontMetrics(8, 16, 2)) * 2


class TestAWidgetCanCapAndAlignItself:
    def test_a_stretched_widget_takes_the_whole_rectangle(self, metrics):
        label = Label(text='a')
        label.arrange(Rect(0, 0, 500, 20), metrics)
        assert label.rect.width == 500

    def test_a_maximum_width_caps_it(self, metrics):
        label = Label(text='a', maximumWidth=120)
        label.arrange(Rect(0, 0, 500, 20), metrics)
        assert label.rect.width == 120

    def test_the_maximum_grows_with_the_interface_scale(self):
        label = Label(text='a', maximumWidth=120)
        label.arrange(Rect(0, 0, 500, 20), FontMetrics(16, 32, 4, scale=2.0))
        assert label.rect.width == 240

    def test_aligning_to_the_end_shrinks_it_to_its_content(self, metrics):
        label = Label(text='ab', alignSelf='end')
        label.arrange(Rect(0, 0, 500, 20), metrics)
        assert label.rect.width == 16

    def test_aligning_to_the_end_puts_it_against_the_right_edge(self, metrics):
        label = Label(text='ab', alignSelf='end')
        label.arrange(Rect(0, 0, 500, 20), metrics)
        assert label.rect.right == 500

    def test_aligning_to_the_centre_puts_it_in_the_middle(self, metrics):
        label = Label(text='ab', alignSelf='center')
        label.arrange(Rect(0, 0, 500, 20), metrics)
        assert label.rect.x == (500 - 16) // 2

    def test_a_capped_widget_is_never_widened(self, metrics):
        label = Label(text='a', maximumWidth=900)
        label.arrange(Rect(0, 0, 100, 20), metrics)
        assert label.rect.width == 100
