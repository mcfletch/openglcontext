"""A viewport that clips and scrolls, and the bar that drives it."""

import pytest

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.layout import Column
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.scroll import ScrollViewport
from OpenGLContext.ui.widgets import Button, Label


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


@pytest.fixture
def viewport(metrics):
    """A tall block of text in a short window."""
    body = Label(text='line\n' * 60, name='text')
    view = ScrollViewport(children=[body], name='view')
    view.arrange(Rect(0, 0, 200, 100), metrics)
    return view


class TestScrolling:
    def test_it_starts_at_the_top(self, viewport):
        """The content's top is at the viewport's, less the glow margin kept
        clear so a focused first row is not clipped."""
        margin = int(viewport.activeSkin().focusMargin)
        assert viewport.scroll == 0
        assert viewport.find('text').rect.top == viewport.rect.top - margin

    def test_the_content_is_taller_than_the_viewport(self, viewport):
        assert viewport.contentHeight > viewport.rect.height
        assert viewport.maximumScroll > 0

    def test_scrolling_moves_the_content_up(self, viewport):
        before = viewport.find('text').rect.top
        viewport.scrollTo(50)
        assert viewport.find('text').rect.top == before + 50

    def test_it_will_not_scroll_past_the_end(self, viewport):
        viewport.scrollTo(100000)
        assert viewport.scroll == viewport.maximumScroll

    def test_it_will_not_scroll_above_the_top(self, viewport):
        viewport.scrollTo(-50)
        assert viewport.scroll == 0

    def test_the_wheel_scrolls_it(self, viewport):
        assert viewport.wheel(-1, 10, 10)
        assert viewport.scroll > 0

    def test_the_wheel_at_the_top_does_not_claim_the_notch(self, viewport):
        """So a wheel over a page that cannot scroll reaches whatever can."""
        assert not viewport.wheel(1, 10, 10)

    def test_page_down_moves_by_about_a_screen(self, viewport):
        viewport.key('<pagedown>', (0, 0, 0))
        assert viewport.scroll >= viewport.rect.height - 20

    def test_end_goes_to_the_bottom(self, viewport):
        viewport.key('<end>', (0, 0, 0))
        assert viewport.scroll == viewport.maximumScroll

    def test_home_comes_back_to_the_top(self, viewport):
        viewport.key('<end>', (0, 0, 0))
        viewport.key('<home>', (0, 0, 0))
        assert viewport.scroll == 0

    def test_page_up_comes_back_by_about_a_screen(self, viewport):
        viewport.key('<end>', (0, 0, 0))
        bottom = viewport.scroll
        viewport.key('<pageup>', (0, 0, 0))
        assert viewport.scroll < bottom

    def test_the_arrows_move_it_a_little(self, viewport):
        viewport.key('<down>', (0, 0, 0))
        assert viewport.scroll > 0
        viewport.key('<up>', (0, 0, 0))
        assert viewport.scroll == 0

    def test_a_key_it_does_not_use_is_left_alone(self, viewport):
        assert not viewport.key('z', (0, 0, 0))

    def test_it_is_only_a_tab_stop_when_there_is_something_to_scroll(
            self, viewport, metrics):
        assert viewport.focusable
        short = ScrollViewport(children=[Label(text='one line')])
        short.arrange(Rect(0, 0, 200, 100), metrics)
        assert not short.focusable

    def test_content_that_fits_does_not_scroll(self, metrics):
        view = ScrollViewport(children=[Label(text='one line')])
        view.arrange(Rect(0, 0, 200, 100), metrics)
        assert view.maximumScroll == 0
        assert not view.wheel(-1, 10, 10)

    def test_an_empty_viewport_survives_layout(self, metrics):
        view = ScrollViewport()
        view.arrange(Rect(0, 0, 200, 100), metrics)
        assert view.maximumScroll == 0


class TestScrollbar:
    def test_a_bar_appears_only_when_it_is_needed(self, viewport, metrics):
        assert viewport.needsBar
        short = ScrollViewport(children=[Label(text='one line')])
        short.arrange(Rect(0, 0, 200, 100), metrics)
        assert not short.needsBar

    def test_the_bar_takes_width_from_the_content(self, viewport):
        assert viewport.find('text').rect.right <= viewport.barRect().x

    def test_the_thumb_is_shorter_than_the_track_when_there_is_more_to_see(self, viewport):
        assert viewport.thumbRect().height < viewport.barRect().height

    def test_the_thumb_starts_at_the_top(self, viewport):
        assert viewport.thumbRect().top == viewport.barRect().top

    def test_the_thumb_reaches_the_bottom_at_full_scroll(self, viewport):
        viewport.scrollTo(viewport.maximumScroll)
        assert viewport.thumbRect().y == viewport.barRect().y

    def test_dragging_the_thumb_scrolls(self, viewport):
        thumb = viewport.thumbRect()
        viewport.press(*thumb.centre)
        viewport.drag(thumb.centre[0], viewport.barRect().y)
        assert viewport.scroll == viewport.maximumScroll

    def test_clicking_the_track_below_the_thumb_pages_down(self, viewport):
        bar = viewport.barRect()
        viewport.press(bar.centre[0], bar.y + 2)
        assert viewport.scroll > 0

    def test_a_click_in_the_content_does_not_scroll(self, viewport):
        viewport.press(10, 10)
        assert viewport.scroll == 0


class TestFocusReveal:
    def test_a_focused_widget_below_the_fold_is_scrolled_into_view(self, metrics):
        buttons = [Button(text='b%d' % index, name='b%d' % index)
                   for index in range(20)]
        panel = Panel(fill=True, children=[
            ScrollViewport(name='view', flex=1,
                           children=[Column(children=buttons, spacing=4)])])
        panel.layout((300, 160), metrics)
        view = panel.find('view')
        assert view.maximumScroll > 0
        panel.focus(buttons[-1])
        assert view.scroll > 0
        assert buttons[-1].rect.y >= view.rect.y

    def test_revealing_something_already_visible_does_nothing(self, metrics):
        buttons = [Button(text='b%d' % index) for index in range(20)]
        panel = Panel(fill=True, children=[
            ScrollViewport(name='view', flex=1,
                           children=[Column(children=buttons, spacing=4)])])
        panel.layout((300, 160), metrics)
        view = panel.find('view')
        panel.focus(buttons[0])
        assert view.scroll == 0

    def test_the_glow_margin_is_kept_clear(self, metrics):
        """A ring clipped in half by the viewport's scissor reads as broken."""
        buttons = [Button(text='b%d' % index) for index in range(20)]
        panel = Panel(fill=True, children=[
            ScrollViewport(name='view', flex=1,
                           children=[Column(children=buttons, spacing=4)])])
        panel.layout((300, 160), metrics)
        view = panel.find('view')
        panel.focus(buttons[-1])
        margin = int(panel.activeSkin().focusMargin)
        assert buttons[-1].rect.y - margin >= view.rect.y


class TestHitTesting:
    def test_a_widget_scrolled_out_of_sight_cannot_be_clicked(self, metrics):
        buttons = [Button(text='b%d' % index, name='b%d' % index)
                   for index in range(20)]
        view = ScrollViewport(children=[Column(children=buttons, spacing=4)])
        view.arrange(Rect(0, 0, 300, 100), metrics)
        hidden = buttons[-1]
        assert not view.rect.intersects(hidden.rect)
        assert view.widget_at(*hidden.rect.centre) is not hidden

    def test_a_visible_widget_can_still_be_clicked(self, metrics):
        buttons = [Button(text='b%d' % index, name='b%d' % index)
                   for index in range(20)]
        view = ScrollViewport(children=[Column(children=buttons, spacing=4)])
        view.arrange(Rect(0, 0, 300, 100), metrics)
        assert view.widget_at(*buttons[0].rect.centre) is buttons[0]
