"""The viewer's caption, drawn by the UI library
(:mod:`OpenGLContext.viewer.caption`).

What is loaded, which camera, which animation and how you move used to be drawn
by a private routine that measured its own text and reached for the flat pass's
shader.  It is a HUD layer now, like every other piece of screen furniture here,
so it takes the skin, the interface scale and the one batched draw call with
everything else -- and a viewer embedded in an application can restyle it
without knowing anything about how text is drawn.

The multi-line block itself is :class:`OpenGLContext.ui.hudwidgets.TextBlock`,
checked here through the caption because that is what asks for it.
"""
import pytest

from OpenGLContext.ui.hudwidgets import HUDLayer, TextBlock
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.viewer import caption as caption_module
from OpenGLContext.viewer.caption import CaptionLayer, CaptionMixin


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


class _Host(CaptionMixin):
    """The little of a context the caption needs."""

    def __init__(self):
        self.redrawn = 0
        self._hudLayers = []

    @property
    def hudLayers(self):
        return self._hudLayers

    def addHUDLayer(self, layer):
        self._hudLayers.append(layer)
        return layer

    def removeHUDLayer(self, layer):
        self._hudLayers.remove(layer)

    def triggerRedraw(self, force=0):
        self.redrawn += 1


class TestTheTextBlock:
    """A HUD element for several lines of text, which the library lacked."""

    def test_it_is_a_hud_widget_and_takes_no_input(self):
        assert TextBlock.interactive is False
        assert TextBlock.focusable is False

    def test_it_asks_for_room_for_its_longest_line(self, metrics):
        block = TextBlock(lines=['ab', 'abcdef', 'abc'])
        width, height = block.content_size(metrics)
        assert width == metrics.text_width('abcdef')

    def test_it_asks_for_room_for_every_line(self, metrics):
        one = TextBlock(lines=['a']).content_size(metrics)[1]
        three = TextBlock(lines=['a', 'b', 'c']).content_size(metrics)[1]
        assert three > one
        assert three == 3 * metrics.line_height - metrics.line_gap

    def test_nothing_to_say_takes_no_room(self, metrics):
        assert TextBlock().content_size(metrics) == (0, 0)

    def test_it_is_placed_by_its_anchor_like_any_hud_element(self, metrics):
        block = TextBlock(lines=['hello'], anchor='top-left')
        HUDLayer(children=[block], margin=10).layout((800, 600), metrics)
        assert block.rect.x == 10
        assert block.rect.top == 590

    def test_each_line_gets_its_own_rectangle_top_down(self, metrics):
        """A caption reads downwards; the coordinate system counts upwards."""
        block = TextBlock(lines=['one', 'two'], anchor='top-left')
        HUDLayer(children=[block], margin=0).layout((800, 600), metrics)
        first, second = block.lineRects(metrics)
        assert first.y > second.y
        assert first.top == block.rect.top


class TestWhereItSits:
    """Clear of the developer overlay, which every context shows by default.

    That one is anchored top-left and grows down the left edge as sections are
    registered, so a caption anywhere down that side is a caption written over
    it -- and the two were, in the corner, unreadably.
    """

    def test_it_is_not_in_the_developer_overlays_corner(self):
        from OpenGLContext.ui.debugoverlay import DebugPanel
        assert caption_module.CAPTION_ANCHOR != str(DebugPanel().anchor)

    def test_it_is_along_the_bottom(self, metrics):
        host = _Host()
        host.setupCaption()
        host.overlayText = 'model.glb'
        host.captionLayer.layout((800, 600), metrics)
        block = host.captionLayer.block
        assert block.rect.y < 300, 'in the lower half'

    def test_it_reads_from_the_edge_it_is_anchored_to(self):
        assert str(CaptionLayer().block.align) == 'right'


class TestTheCaption:
    def test_a_viewer_gets_one_layer_for_it(self):
        host = _Host()
        host.setupCaption()
        assert len(host.hudLayers) == 1
        assert isinstance(host.hudLayers[0], CaptionLayer)

    def test_setting_it_up_twice_does_not_stack_captions(self):
        host = _Host()
        host.setupCaption()
        host.setupCaption()
        assert len(host.hudLayers) == 1

    def test_the_text_is_read_back_as_it_was_written(self):
        host = _Host()
        host.setupCaption()
        host.overlayText = 'Duck.glb\n[1/2] front'
        assert host.overlayText == 'Duck.glb\n[1/2] front'

    def test_the_lines_reach_the_widget(self):
        host = _Host()
        host.setupCaption()
        host.overlayText = 'Duck.glb\n[1/2] front'
        assert list(host.captionLayer.block.lines) == ['Duck.glb', '[1/2] front']

    def test_a_caption_works_before_anyone_set_one_up(self):
        """A viewer built by ``__new__`` in a test, or a host that forgot."""
        host = _Host()
        host.overlayText = 'Duck.glb'
        assert host.overlayText == 'Duck.glb'

    def test_a_failure_is_marked_as_one_rather_than_coloured_here(self):
        """What 'wrong' looks like is the skin's business, not the viewer's."""
        host = _Host()
        host.setupCaption()
        host.overlayError = True
        assert host.overlayError is True
        assert bool(host.captionLayer.block.critical) is True

    def test_a_new_caption_asks_for_a_frame(self):
        host = _Host()
        host.setupCaption()
        before = host.redrawn
        host.overlayText = 'something else'
        assert host.redrawn > before

    def test_the_same_caption_again_asks_for_nothing(self):
        """It is recomposed on every camera change; only changes matter."""
        host = _Host()
        host.setupCaption()
        host.overlayText = 'Duck.glb'
        before = host.redrawn
        host.overlayText = 'Duck.glb'
        assert host.redrawn == before

    def test_it_can_be_hidden_for_a_clean_frame(self):
        """A ``--capture`` frame carries no caption."""
        host = _Host()
        host.setupCaption()
        host.showCaption(False)
        assert not host.captionLayer.visible
        host.showCaption(True)
        assert host.captionLayer.visible
