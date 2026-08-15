"""The overlay actually reaches the framebuffer, against a real GL context.

Layout and input are arithmetic and are tested without GL; this is the other
half -- that the program compiles, that a panel and its text land where the
layout said, and that translucency, the focus glow and clipping do what they
claim.
"""

import os

import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.ui.geometry import Rect                       # noqa: E402
from OpenGLContext.ui.layout import Column, Row                  # noqa: E402
from OpenGLContext.ui.overlay import OverlayStack                # noqa: E402
from OpenGLContext.ui.panel import Panel                         # noqa: E402
from OpenGLContext.ui.widgets import (                           # noqa: E402
    Button, Label, Slider, TextField, Toggle, PRIMARY,
)

WIDTH = HEIGHT = 256


@pytest.fixture
def gl_context():
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        pytest.skip("glfw init failed")
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    window = glfw.create_window(WIDTH, HEIGHT, "overlay", None, None)
    if not window:
        pytest.skip("no GL window")
    glfw.make_context_current(window)
    yield window
    # The cached atlases hold GL objects in this context, and the driver hands
    # the next window the same identifier often enough that leaving them would
    # make one test's textures another test's problem.
    from OpenGLContext.scenegraph.text import shadertext
    shadertext.drop_text_renderers()
    glfw.destroy_window(window)


@pytest.fixture
def renderer(gl_context):
    """A renderer with its program and font atlas built, or a skip."""
    from OpenGL.GL import glViewport
    from OpenGLContext.ui.draw import OverlayRenderer
    glViewport(0, 0, WIDTH, HEIGHT)
    made = OverlayRenderer(16)
    if not made.initialize():
        pytest.skip("no font atlas / program on this driver")
    yield made
    made.close()


def clear(colour=(0.0, 0.0, 0.0, 1.0)):
    from OpenGL.GL import glClear, glClearColor, GL_COLOR_BUFFER_BIT
    glClearColor(*colour)
    glClear(GL_COLOR_BUFFER_BIT)


def frame():
    """The framebuffer as (height, width, 3) ints, bottom row first."""
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    raw = glReadPixels(0, 0, WIDTH, HEIGHT, GL_RGB, GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3).astype(int)


def draw(renderer, panel):
    stack = OverlayStack()
    stack.push(panel, viewport=(WIDTH, HEIGHT), metrics=renderer.metrics)
    clear()
    renderer.draw(stack, (WIDTH, HEIGHT))
    return frame()


def test_the_program_builds(renderer):
    assert renderer.metrics.char_width > 0


def test_a_panel_covers_its_own_rectangle(renderer):
    panel = Panel(children=[Column(children=[Label(text='hello')])])
    image = draw(renderer, panel)
    inside = image[panel.rect.centre[1], panel.rect.centre[0]]
    outside = image[2, 2]
    assert inside.sum() > outside.sum()
    assert outside.sum() == 0


def test_the_panel_is_translucent_over_the_world(renderer):
    """These sit over a live world and must read as a layer on it."""
    panel = Panel(children=[Column(children=[Label(text='hi')])])
    stack = OverlayStack()
    stack.push(panel, viewport=(WIDTH, HEIGHT), metrics=renderer.metrics)
    clear((0.0, 0.8, 0.0, 1.0))
    renderer.draw(stack, (WIDTH, HEIGHT))
    image = frame()
    x, y = panel.rect.x + 4, panel.rect.y + 4
    assert image[y, x][1] > 20, "the world behind is completely hidden"
    assert image[y, x][1] < 200, "the panel is not covering anything"


def test_text_is_drawn_inside_the_panel(renderer):
    label = Label(text='WWWWWWWW', name='label')
    panel = Panel(children=[Column(children=[label])])
    image = draw(renderer, panel)
    region = image[label.rect.y:label.rect.top, label.rect.x:label.rect.right]
    background = image[panel.rect.y + 2, panel.rect.x + 2]
    assert region.max() > background.max() + 30, "no glyphs rendered"


def test_a_button_lights_under_the_pointer(renderer):
    button = Button(text='Yes', role=PRIMARY, name='yes')
    panel = Panel(children=[Column(children=[button])])
    cold = draw(renderer, panel)
    panel.pointer_moved(*button.rect.centre)
    clear()
    renderer.draw(_stackOf(panel), (WIDTH, HEIGHT))
    warm = frame()
    box = (slice(button.rect.y + 2, button.rect.top - 2),
           slice(button.rect.x + 2, button.rect.right - 2))
    assert warm[box].mean() > cold[box].mean()


def test_the_focus_glow_falls_outside_the_widget(renderer):
    button = Button(text='Yes', name='yes')
    panel = Panel(children=[Column(children=[button])])
    dark = draw(renderer, panel)
    panel.focus(button)
    clear()
    renderer.draw(_stackOf(panel), (WIDTH, HEIGHT))
    lit = frame()
    just_outside = (button.rect.y - 2, button.rect.centre[0])
    assert lit[just_outside].sum() > dark[just_outside].sum()


def test_a_scissor_clips_what_is_drawn_outside_it(renderer):
    from OpenGL.GL import glViewport
    glViewport(0, 0, WIDTH, HEIGHT)
    clear()
    assert renderer.begin((WIDTH, HEIGHT))
    previous = renderer.pushScissor(Rect(0, 0, WIDTH // 2, HEIGHT))
    renderer.quad(Rect(0, 0, WIDTH, HEIGHT), (1, 1, 1, 1))
    renderer.popScissor(previous)
    renderer.end()
    image = frame()
    assert image[HEIGHT // 2, WIDTH // 4].sum() > 600
    assert image[HEIGHT // 2, WIDTH * 3 // 4].sum() == 0


def test_every_widget_paints_without_error(renderer):
    """A smoke test over the whole widget set, since each paints itself.

    Every state that is drawn differently is here: hovered, armed, disabled,
    focused, checked and unchecked, and a viewport that has to clip.
    """
    from OpenGLContext.ui.console import ConsoleView
    from OpenGLContext.ui.scroll import ScrollViewport
    from OpenGLContext.ui.widgets import KeyCapture, Select, Separator, Spacer

    view = ConsoleView(name='log')
    view.write('an informational line')
    view.write('a warning', level=30)
    view.write('an error', level=40)
    hovered = Button(text='Hover', name='hovered')
    armed = Button(text='Armed', name='armed')
    disabled = Button(text='Off', name='disabled', enabled=False)
    entry = TextField(value='name', name='entry')
    panel = Panel(title='Settings', scrim=True, fill=True, children=[Column(
        children=[
            ScrollViewport(name='body', flex=1, children=[Column(spacing=4, children=[
                Label(text='A wrapped paragraph of text that goes on for a '
                           'while and has to be broken across lines.', wrap=True),
                Toggle(text='Shadows', value=True),
                Toggle(text='Soft shadows', value=False),
                Slider(text='Lights', minimum=0, maximum=8, value=4, suffix=' max'),
                Select(options=['low', 'high'], optionLabels=['Low', 'High'],
                       value='high'),
                KeyCapture(keys=['w', '<up>']),
                KeyCapture(name='captured'),
                entry,
                TextField(placeholder='empty'),
                Separator(),
                view,
            ])]),
            Row(children=[disabled, Spacer(), hovered, armed,
                          Button(text='Ok', role=PRIMARY),
                          Button(text='Reset', role='danger')], spacing=8),
        ], spacing=6)])
    panel.layout((WIDTH, HEIGHT), renderer.metrics)
    panel.find('captured').key('j', (0, 0, 0))
    panel.pointer_moved(*hovered.rect.centre)
    armed.press(*armed.rect.centre)
    panel.focus(entry)
    image = draw(renderer, panel)
    assert image.max() > 0
    assert panel.find('body').needsBar, "the viewport should have to clip"


def test_a_stack_draws_the_parent_behind_the_child(renderer):
    first = Panel(children=[Column(children=[Label(text='under')])], fill=True)
    second = Panel(children=[Column(children=[Label(text='over')])])
    stack = OverlayStack()
    stack.push(first, viewport=(WIDTH, HEIGHT), metrics=renderer.metrics)
    stack.push(second, viewport=(WIDTH, HEIGHT), metrics=renderer.metrics)
    clear()
    renderer.draw(stack, (WIDTH, HEIGHT))
    image = frame()
    # The child is drawn over the parent, so its centre is brighter than the
    # parent's fill alone.
    assert image[second.rect.centre[1], second.rect.centre[0]].sum() > \
        image[first.rect.y + 2, first.rect.x + 2].sum()


def _stackOf(panel):
    stack = OverlayStack()
    stack.panels.append(panel)
    return stack


def _ninepatch_image(path, size=32, border=8):
    """A frame whose corners are distinct, so stretching them would show."""
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, size - 1, size - 1], fill=(40, 60, 90, 255))
    draw.rectangle([border, border, size - 1 - border, size - 1 - border],
                   fill=(20, 30, 45, 255))
    # A white square in each corner: if the corners were stretched they would
    # no longer be square in the result.
    for x, y in ((0, 0), (size - border, 0), (0, size - border),
                 (size - border, size - border)):
        draw.rectangle([x, y, x + border - 1, y + border - 1],
                       fill=(255, 255, 255, 255))
    image.save(path)
    return path


def test_a_nine_slice_keeps_its_corners_square(renderer, tmp_path):
    """One button image has to serve two button widths without distorting."""
    from OpenGLContext.ui.geometry import Rect
    from OpenGLContext.ui.skin import NineSlice
    path = _ninepatch_image(str(tmp_path / 'frame.png'))
    art = NineSlice(url=[path], border=(8, 8, 8, 8))
    clear()
    assert renderer.begin((WIDTH, HEIGHT))
    target = Rect(20, 20, 200, 60)
    assert renderer.ninepatch(target, art)
    renderer.end()
    image = frame()
    # The bottom-left corner is 8x8 of white; 8 pixels in it is still white,
    # and 16 pixels along the (stretched) bottom edge is not.
    assert image[target.y + 4, target.x + 4].min() > 200
    assert image[target.y + 4, target.x + 40].min() < 200


def test_a_missing_skin_image_falls_back_to_the_flat_fill(renderer, tmp_path):
    from OpenGLContext.ui.geometry import Rect
    from OpenGLContext.ui.skin import NineSlice
    art = NineSlice(url=[str(tmp_path / 'absent.png')], border=(4, 4, 4, 4))
    clear()
    assert renderer.begin((WIDTH, HEIGHT))
    assert not renderer.ninepatch(Rect(10, 10, 60, 30), art)
    renderer.frame(Rect(10, 10, 60, 30), (1, 1, 1, 1), art)
    renderer.end()
    assert frame()[20, 20].min() > 200


def test_a_skinned_button_draws_its_artwork(renderer, tmp_path):
    from OpenGLContext.ui.skin import NineSlice, Skin
    path = _ninepatch_image(str(tmp_path / 'button.png'))
    skin = Skin(buttonImage=NineSlice(url=[path], border=(8, 8, 8, 8)))
    button = Button(text='Play', name='play')
    panel = Panel(skin=skin, children=[Column(children=[button])])
    image = draw(renderer, panel)
    corner = image[button.rect.y + 2, button.rect.x + 2]
    assert corner.min() > 150, "the button's artwork did not draw"


def test_the_context_hook_lays_out_and_draws(gl_context):
    """The path a real context takes: renderShaderOverlay with a live atlas."""
    from OpenGL.GL import glViewport
    from OpenGLContext.events.inputstate import InputState
    from OpenGLContext.ui.overlay import OverlayMixin
    from OpenGLContext.ui.screen import ScreenMixin

    class World:
        def __init__(self):
            self.inputState = InputState()
            self.redraws = 0

        def getViewPort(self):
            return (WIDTH, HEIGHT)

        def getInputState(self):
            return self.inputState

        def triggerRedraw(self, force=0):
            self.redraws += 1

        def suspendPointerCapture(self, suspend):
            pass

        def hasMouseMoveHandlers(self):
            return False

    class Context(OverlayMixin, ScreenMixin, World):
        pass

    glViewport(0, 0, WIDTH, HEIGHT)
    context = Context()
    panel = Panel(children=[Column(children=[Label(text='hello'),
                                             Button(text='Ok')])])
    context.pushOverlay(panel)
    clear()
    context.renderShaderOverlay(None)
    assert panel.rect.width > 0, "the hook did not lay the panel out"
    assert frame()[panel.rect.centre[1], panel.rect.centre[0]].sum() > 0
    renderer = getattr(context, '_overlayRenderer', None)
    if renderer is not None:
        renderer.close()


def test_the_hook_does_nothing_with_no_overlay(gl_context):
    from OpenGLContext.ui.overlay import OverlayMixin
    from OpenGLContext.ui.screen import ScreenMixin

    class Context(OverlayMixin, ScreenMixin):
        def getViewPort(self):
            return (WIDTH, HEIGHT)

    clear()
    Context().renderShaderOverlay(None)
    assert frame().max() == 0


# -- text renderers belong to one GL context ---------------------------------

def test_two_windows_get_their_own_text_renderer(gl_context):
    """A texture id means nothing in another context.

    The atlas is cached so that nine sizes do not become nine per frame, but
    the cache cannot be per process: a second window binding the first
    window's texture id is at best drawing the wrong thing and at worst a GL
    error.
    """
    from OpenGLContext.scenegraph.text.shadertext import get_text_renderer
    first = get_text_renderer(16)
    assert first.initialize()
    second_window = glfw.create_window(WIDTH, HEIGHT, "second", None, None)
    if not second_window:
        pytest.skip("no second GL window")
    try:
        glfw.make_context_current(second_window)
        second = get_text_renderer(16)
        assert second is not first
        assert second.initialize()
    finally:
        glfw.destroy_window(second_window)
        glfw.make_context_current(gl_context)


def test_the_same_window_keeps_the_one_atlas(gl_context):
    from OpenGLContext.scenegraph.text.shadertext import get_text_renderer
    assert get_text_renderer(16) is get_text_renderer(16)


def test_a_context_can_let_its_text_renderers_go(gl_context):
    """What a window calls as it is destroyed, so nothing outlives its objects."""
    from OpenGLContext.scenegraph.text import shadertext
    made = shadertext.get_text_renderer(16)
    made.initialize()
    shadertext.drop_text_renderers()
    assert shadertext.get_text_renderer(16) is not made


class TestTheContextDrawsItsOwnOverlay:
    """``renderShaderOverlay`` is the seam the whole system hangs from.

    It is what ties the stack, the window size, the font atlas and the renderer
    together, and it is the only place that guarantees a panel is laid out for
    the current window before it is drawn.  There is a real GL context here, so
    there is no reason for it to be the one part nothing exercises.
    """

    @pytest.fixture
    def context(self, gl_context):
        from OpenGL.GL import glViewport
        from OpenGLContext.ui.overlay import OverlayMixin
        from OpenGLContext.ui.screen import ScreenMixin
        glViewport(0, 0, WIDTH, HEIGHT)

        class Context(OverlayMixin, ScreenMixin):
            contextDefinition = None
            captured = False

            def getViewPort(self):
                return (WIDTH, HEIGHT)

            def getInputState(self):
                return _Sampler()

            def triggerRedraw(self, flag):
                pass

            def suspendPointerCapture(self, suspend):
                self.captured = suspend

        made = Context()
        yield made
        renderer = getattr(made, '_overlayRenderer', None)
        if renderer is not None:
            renderer.close()

    def test_an_empty_stack_draws_nothing_and_does_not_fail(self, context):
        clear()
        context.renderShaderOverlay(None)
        assert frame().max() == 0

    def test_a_pushed_panel_reaches_the_framebuffer(self, context):
        context.pushOverlay(Panel(children=[Label(text='hello')], title='T'))
        clear()
        context.renderShaderOverlay(None)
        assert frame().max() > 0, "the panel drew nothing at all"

    def test_it_lays_out_for_the_window_before_drawing(self, context):
        panel = context.pushOverlay(Panel(children=[Label(text='hello')]))
        context.overlays.invalidate()
        panel.rect = Rect(0, 0, 0, 0)
        clear()
        context.renderShaderOverlay(None)
        assert not panel.rect.empty, "drawn without being laid out"

    def test_it_draws_every_panel_in_the_stack(self, context):
        """A parent screen keeps showing behind the dialog raised over it."""
        under = context.pushOverlay(Panel(children=[Label(text='under')],
                                          scrim=False, fill=True))
        over = context.pushOverlay(Panel(children=[Label(text='over')],
                                         scrim=False, preferredColumns=8))
        clear()
        context.renderShaderOverlay(None)
        pixels = frame()
        assert not over.rect.empty and not under.rect.empty
        # A row of the lower panel that the upper one does not cover.
        row = max(0, under.rect.y + 2)
        outside = [x for x in range(under.rect.x + 2, under.rect.right - 2)
                   if not over.rect.contains(x, row)]
        assert outside, "the dialog covered the whole screen"
        assert max(pixels[row][x].sum() for x in outside) > 0, \
            "the panel underneath was not drawn"
        assert pixels[over.rect.centre[1]][over.rect.centre[0]].sum() > 0, \
            "the panel on top was not drawn"


class _Sampler:
    def clear(self):
        pass


class TestTheBatchDoesNotFlushForNothing:
    """A quad with nothing to show must not disturb the batch.

    A transparent colour is ordinary here -- a Label's default colour means
    "use the skin", a Grid guards its hairline on the rule's alpha, and a skin
    turns a fill off by zeroing it.  Changing the texture and then deciding
    there is nothing to draw costs the batch two draw calls: one to flush what
    came before, and one to get back to it.
    """

    def test_a_transparent_quad_leaves_the_batch_alone(self, renderer):
        renderer.begin((WIDTH, HEIGHT))
        try:
            renderer.rect(Rect(0, 0, 8, 8), (1, 1, 1, 1))
            before = (renderer._texture, renderer._mode, len(renderer._vertices))
            renderer.quad(Rect(0, 0, 8, 8), (1, 1, 1, 0), texture=renderer._disc)
            assert (renderer._texture, renderer._mode,
                    len(renderer._vertices)) == before
        finally:
            renderer.end()

    def test_an_empty_rectangle_leaves_the_batch_alone(self, renderer):
        renderer.begin((WIDTH, HEIGHT))
        try:
            renderer.rect(Rect(0, 0, 8, 8), (1, 1, 1, 1))
            before = (renderer._texture, len(renderer._vertices))
            renderer.quad(Rect(0, 0, 0, 8), (1, 1, 1, 1), texture=renderer._disc)
            assert (renderer._texture, len(renderer._vertices)) == before
        finally:
            renderer.end()

    def test_a_visible_quad_still_switches_texture(self, renderer):
        renderer.begin((WIDTH, HEIGHT))
        try:
            renderer.rect(Rect(0, 0, 8, 8), (1, 1, 1, 1))
            renderer.quad(Rect(0, 0, 8, 8), (1, 1, 1, 1), texture=renderer._disc)
            assert renderer._texture is renderer._disc
        finally:
            renderer.end()


class TestClosingReleasesTheProgram:
    def test_close_deletes_the_program(self, gl_context):
        from OpenGL.GL import glIsProgram
        from OpenGLContext.ui.draw import OverlayRenderer
        made = OverlayRenderer(16)
        if not made.initialize():
            pytest.skip("no font atlas / program on this driver")
        program = made._program
        assert glIsProgram(program)
        made.close()
        assert not glIsProgram(program), "the GL program was leaked"

    def test_closing_twice_is_harmless(self, gl_context):
        from OpenGLContext.ui.draw import OverlayRenderer
        made = OverlayRenderer(16)
        if not made.initialize():
            pytest.skip("no font atlas / program on this driver")
        made.close()
        made.close()


class TestSkinArtworkUrls:
    """A skin's ``url`` behaves the way an MFString url does everywhere else."""

    @pytest.fixture
    def artwork(self, tmp_path):
        from PIL import Image
        path = tmp_path / 'frame.png'
        Image.new('RGBA', (12, 12), (200, 40, 40, 255)).save(str(path))
        return path

    def test_a_plain_path_loads(self, renderer, artwork):
        assert renderer.imageTexture(str(artwork)) is not None

    def test_a_file_url_loads(self, renderer, artwork):
        assert renderer.imageTexture(artwork.as_uri()) is not None

    def test_the_first_url_that_loads_is_used(self, renderer, artwork):
        from OpenGLContext.ui.skin import NineSlice
        image = NineSlice(url=[str(artwork.parent / 'missing.png'),
                               str(artwork)], border=(4, 4, 4, 4))
        renderer.begin((WIDTH, HEIGHT))
        try:
            assert renderer.ninepatch(Rect(0, 0, 32, 32), image)
        finally:
            renderer.end()

    def test_artwork_that_cannot_be_read_falls_back_to_the_fill(self, renderer,
                                                                tmp_path):
        from OpenGLContext.ui.skin import NineSlice
        image = NineSlice(url=[str(tmp_path / 'nope.png')])
        renderer.begin((WIDTH, HEIGHT))
        try:
            assert not renderer.ninepatch(Rect(0, 0, 32, 32), image)
        finally:
            renderer.end()


class _Redrawable:
    """The little of a context the renderer asks anything of."""

    def __init__(self):
        self.asked = []

    def triggerRedraw(self, force=0):
        self.asked.append(force)


def test_a_picture_arriving_asks_the_context_for_a_frame(renderer):
    """Otherwise it is drawn whenever something unrelated next causes one.

    ``force=0`` because the decode finishes on a worker thread: it sets the
    redraw flag and wakes the loop rather than drawing from the wrong thread.
    """
    from OpenGLContext.ui.draw import OverlayRenderer
    context = _Redrawable()
    made = OverlayRenderer.forContext(context, 16)
    if made is None:
        pytest.skip('no font atlas / program on this driver')
    try:
        assert made.pictures.onReady is not None
        made.pictures.onReady()
        assert context.asked == [0]
    finally:
        made.close()
