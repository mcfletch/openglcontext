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

    class Context(OverlayMixin, World):
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

    class Context(OverlayMixin):
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
