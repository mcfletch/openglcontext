"""A menu reaches the framebuffer: its rows, its highlight and its shortcuts.

Where a menu opens and what it does are arithmetic and are tested without GL
(``test_ui_menu.py``); this is the other half -- that the rows are drawn where
the layout put them, that the row under the pointer lights, and that a
shortcut is legible on the right of the row it belongs to.
"""


import numpy as np
import pytest


from OpenGLContext.ui.menu import Menu, MenuBar, MenuItem      # noqa: E402
from OpenGLContext.ui.overlay import OverlayStack              # noqa: E402

WIDTH = HEIGHT = 256


@pytest.fixture
def gl_context(gl_window):
    window = gl_window('menu', size=(WIDTH, HEIGHT))
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


def _clear(colour=(0.0, 0.0, 0.0, 1.0)):
    from OpenGL.GL import glClear, glClearColor, GL_COLOR_BUFFER_BIT
    glClearColor(*colour)
    glClear(GL_COLOR_BUFFER_BIT)


def _frame():
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    raw = glReadPixels(0, 0, WIDTH, HEIGHT, GL_RGB, GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3).astype(int)


def _draw(renderer, panel):
    stack = OverlayStack()
    stack.push(panel, viewport=(WIDTH, HEIGHT), metrics=renderer.metrics)
    _clear()
    renderer.draw(stack, (WIDTH, HEIGHT))
    return _frame()


def _redraw(renderer, panel):
    stack = OverlayStack()
    stack.panels.append(panel)
    _clear()
    renderer.draw(stack, (WIDTH, HEIGHT))
    return _frame()


def _menu():
    return Menu(anchor=(20.0, 200.0), items=[
        MenuItem(text='Open', shortcut='<ctrl-o>'),
        MenuItem(text='Save'),
        MenuItem(text='Quit'),
    ])


def _rows(menu):
    return [w for w in menu.walk() if isinstance(w, MenuItem)]


def test_the_menu_covers_its_own_rectangle(renderer):
    menu = _menu()
    image = _draw(renderer, menu)
    inside = image[menu.rect.centre[1], menu.rect.centre[0]]
    assert inside.sum() > 0
    assert image[2, 2].sum() == 0, "the menu painted outside itself"


def test_every_row_has_its_text_drawn(renderer):
    menu = _menu()
    image = _draw(renderer, menu)
    background = image[menu.rect.y + 1, menu.rect.x + 1].max()
    for row in _rows(menu):
        band = image[row.rect.y:row.rect.top, row.rect.x:row.rect.right]
        assert band.max() > background + 30, "no glyphs on %r" % row.text


def test_the_row_under_the_pointer_lights(renderer):
    menu = _menu()
    row = _rows(menu)[1]
    cold = _draw(renderer, menu)
    menu.pointer_moved(*row.rect.centre)
    warm = _redraw(renderer, menu)
    box = (slice(row.rect.y + 1, row.rect.top - 1),
           slice(row.rect.x + 1, row.rect.right - 1))
    assert warm[box].mean() > cold[box].mean()


def test_only_that_row_lights(renderer):
    menu = _menu()
    rows = _rows(menu)
    cold = _draw(renderer, menu)
    menu.pointer_moved(*rows[1].rect.centre)
    warm = _redraw(renderer, menu)
    other = (slice(rows[2].rect.y + 1, rows[2].rect.top - 1),
             slice(rows[2].rect.x + 1, rows[2].rect.right - 1))
    assert warm[other].mean() == pytest.approx(cold[other].mean(), abs=1.0)


def test_the_shortcut_is_drawn_on_the_right_of_its_row(renderer):
    menu = _menu()
    image = _draw(renderer, menu)
    row = _rows(menu)[0]
    right = image[row.rect.y:row.rect.top,
                  row.rect.centre[0]:row.rect.right]
    background = image[menu.rect.y + 1, menu.rect.x + 1].max()
    assert right.max() > background + 30


def test_a_bar_draws_along_the_top(renderer):
    bar = MenuBar(menus=[('File', [MenuItem(text='Quit')])])
    image = _draw(renderer, bar)
    assert image[HEIGHT - 2, 4].sum() > 0
    assert image[HEIGHT // 2, 4].sum() == 0, "the bar covered the world"


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
