"""The HUD and the developer overlay reach the framebuffer, on a real driver.

Their layout is arithmetic and is tested without GL; this is the other half --
that a reticule lands in the middle of the window, that a meter's fill is the
colour its value asked for, and that a panel opened over a HUD is drawn on top
of it rather than under it.
"""


import numpy as np
import pytest


from OpenGLContext.ui.debugoverlay import DebugOverlay              # noqa: E402
from OpenGLContext.ui.hudwidgets import (                           # noqa: E402
    BarMeter, Crosshair, DamageIndicator, HUDLayer, MessageQueue,
)
from OpenGLContext.ui.panel import Panel                            # noqa: E402

WIDTH = HEIGHT = 256


@pytest.fixture
def gl_context(gl_window):
    window = gl_window('hud', size=(WIDTH, HEIGHT))
    yield window
    # The cached atlases hold GL objects in this context, and the driver hands
    # the next window the same identifier often enough that leaving them would
    # make one test's textures another test's problem.
    from OpenGLContext.scenegraph.text import shadertext
    shadertext.drop_text_renderers()


@pytest.fixture
def renderer(gl_context):
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


def draw(renderer, *trees):
    for tree in trees:
        tree.layout((WIDTH, HEIGHT), renderer.metrics)
    clear()
    renderer.drawTrees(trees, (WIDTH, HEIGHT))
    return frame()


def test_a_reticule_is_drawn_in_the_middle(renderer):
    layer = HUDLayer(children=[Crosshair(gap=4, length=8, thickness=2)])
    pixels = draw(renderer, layer)
    middle = pixels[HEIGHT // 2, WIDTH // 2 - 10:WIDTH // 2 + 10]
    assert middle.max() > 100, "no reticule around the centre of the window"
    corner = pixels[4:12, 4:12]
    assert corner.max() < 10, "something was drawn where nothing was placed"


def test_the_gap_in_the_middle_is_left_clear(renderer):
    layer = HUDLayer(children=[Crosshair(gap=6, length=8, thickness=2)])
    pixels = draw(renderer, layer)
    assert pixels[HEIGHT // 2, WIDTH // 2].max() < 10


def test_a_meter_fills_with_the_colour_its_value_asks_for(renderer):
    """A meter at a tenth of its maximum reads critical, and that is red."""
    layer = HUDLayer(margin=0, children=[
        BarMeter(value=10, maximum=100, barWidth=200, barHeight=40,
                 showValue=False, anchor='bottom-left'),
    ])
    pixels = draw(renderer, layer)
    fill = pixels[20, 4]
    assert fill[0] > fill[1] and fill[0] > fill[2]


def test_a_message_is_drawn_and_then_is_not(renderer):
    queue = MessageQueue(duration=1.0, fade=0.0)
    layer = HUDLayer(children=[queue])
    queue.post('PICKED UP A SHOTGUN', now=0.0)
    layer.tick(0.5)
    lit = draw(renderer, layer).sum()
    layer.tick(2.0)
    assert draw(renderer, layer).sum() < lit


def test_the_debug_overlay_draws_what_a_provider_gave_it(renderer):
    overlay = DebugOverlay(margin=8)
    overlay.register('Frame', lambda: [('fps', 60.0)])
    overlay.tick(0.0)
    pixels = draw(renderer, overlay)
    top_left = pixels[HEIGHT - 60:HEIGHT - 8, 8:120]
    assert top_left.max() > 60, "the overlay plate did not reach the frame"


def test_a_hidden_debug_overlay_draws_nothing(renderer):
    overlay = DebugOverlay(margin=8)
    overlay.register('Frame', lambda: [('fps', 60.0)])
    overlay.tick(0.0)
    overlay.visible = False
    assert draw(renderer, overlay).max() == 0


def test_a_panel_is_drawn_over_the_hud(renderer):
    """Order is the whole point of drawing them in one batch."""
    layer = HUDLayer(margin=0, children=[
        BarMeter(value=100, maximum=100, barWidth=WIDTH, barHeight=HEIGHT,
                 showValue=False, anchor='center'),
    ])
    panel = Panel(title='Settings', width=120, height=120)
    hud_only = draw(renderer, layer)
    with_panel = draw(renderer, layer, panel)
    middle = (HEIGHT // 2, WIDTH // 2)
    assert not np.array_equal(hud_only[middle], with_panel[middle])


def test_a_damage_indicator_washes_the_edge_it_came_from(renderer):
    """The whole of what it is for: a player looks where the screen is lit."""
    import math

    indicator = DamageIndicator(duration=1.0, thickness=40)
    layer = HUDLayer(margin=0, children=[indicator])
    indicator.hurt(bearing=-math.pi / 2, intensity=1.0, now=0.0)
    indicator.tick(0.0)
    pixels = draw(renderer, layer)
    left = pixels[HEIGHT // 2, 2:10].max()
    right = pixels[HEIGHT // 2, WIDTH - 10:WIDTH - 2].max()
    assert left > 20, "nothing was drawn at the edge the hit came from"
    assert left > right


def test_a_damage_indicator_at_rest_draws_nothing(renderer):
    layer = HUDLayer(margin=0, children=[DamageIndicator()])
    assert draw(renderer, layer).max() == 0


def test_a_damage_indicator_fades_out_of_the_frame(renderer):
    import math

    indicator = DamageIndicator(duration=0.5, thickness=40)
    layer = HUDLayer(margin=0, children=[indicator])
    indicator.hurt(bearing=math.pi, intensity=1.0, now=0.0)
    indicator.tick(0.1)
    lit = draw(renderer, layer).sum()
    indicator.tick(0.4)
    assert 0 < draw(renderer, layer).sum() < lit
    indicator.tick(0.9)
    assert draw(renderer, layer).max() == 0


def test_a_meter_flash_brightens_it(renderer):
    """A number that changed silently in the corner is not feedback."""
    meter = BarMeter(value=40, maximum=100, barWidth=200, barHeight=40,
                     showValue=False, anchor='bottom-left',
                     flashDuration=0.4)
    layer = HUDLayer(margin=0, children=[meter])
    meter.tick(0.0)
    calm = draw(renderer, layer).sum()
    meter.flash(now=1.0)
    meter.tick(1.0)
    assert draw(renderer, layer).sum() > calm
