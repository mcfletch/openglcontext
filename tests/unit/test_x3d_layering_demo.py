"""``oglc-x3d-layering``: the X3D layers scene, with and without a window."""
import os

import pytest
from vrml import node as vrml_node
from vrml import protofunctions

from OpenGLContext.bin import x3d_layering
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph.scenegraph import X3DScene

COMPONENTS = {'LayerSet', 'Layer', 'LayoutLayer', 'Viewport', 'Layout', 'LayoutGroup',
              'ScreenFontStyle'}
SIZE = (320, 180)


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    found = x3d_layering.LayeringScene(str(tmp_path_factory.mktemp('layering')))
    assert background.wait_for_idle(20.0)
    return found


def _kinds(root):
    seen, kinds, todo = set(), set(), [root]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        kinds.add(getattr(type(current), 'PROTO', type(current).__name__))
        for declared in protofunctions.getFields(current):
            value = getattr(current, declared.name, None)
            if isinstance(declared, vrml_node.SFNode) and value:
                todo.append(value)
            elif isinstance(declared, vrml_node.MFNode):
                todo.extend(child for child in value or () if child)
    return kinds


def test_it_reads_without_errors(demo):
    assert isinstance(demo.scene, X3DScene)
    assert not [problem for problem in demo.scene.problems if problem.severity == 'error']


def test_the_maps_it_names_are_written_beside_it(demo):
    names = set(os.listdir(demo.directory))
    assert 'x3d_layering.x3d' in names
    for material in x3d_layering.MATERIALS:
        assert {'%s_base.png' % material, '%s_mr.png' % material} <= names


def test_it_uses_the_layering_and_layout_nodes(demo):
    assert COMPONENTS <= _kinds(demo.scene)


def test_the_keys_show_and_hide_the_inset_and_the_panel(demo):
    inset, frame, panel = (demo.scene.getDEF(name) for name in ('Inset', 'Frame', 'Panel'))
    assert demo.press('i') == 'inset hidden'
    assert (inset.visible, frame.visible) == (False, False)
    assert demo.press('i') == 'inset shown'
    assert (inset.visible, frame.visible) == (True, True)
    assert demo.press('p') == 'panel hidden'
    assert panel.visible is False
    assert demo.press('p') == 'panel shown'
    assert demo.press('x') == ''


def test_the_help_names_each_key():
    assert all(key in x3d_layering.LayeringScene.help() for key in x3d_layering.LayeringScene.KEYS)


def _pixel(image, x, y):
    return tuple(int(value) for value in image[image.shape[0] - 1 - y, x])


@pytest.mark.usefixtures('gl_context')
def test_the_inset_is_drawn_over_the_courtyard_and_the_panel_over_both(demo):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    width, height = SIZE
    middle = (int(width * 0.82), int(height * 0.77))
    with scene_context(demo.scene, size=SIZE) as context:
        context.OnDraw(force=1)
        background.wait_for_idle(20.0)
        shown = drawn_image(context)
        demo.press('i')
        hidden = drawn_image(context)
        demo.press('i')
    # The inset's plan view of the paving, and the brick wall behind it there
    # with the inset hidden
    assert sum(abs(a - b) for a, b in zip(_pixel(shown, *middle), _pixel(hidden, *middle))) > 60
    # The panel, 16 pixels in from the bottom left, is wood either way
    panel = _pixel(shown, 24, 24)
    assert panel == _pixel(hidden, 24, 24)
    assert panel[0] > panel[2] + 20


@pytest.mark.usefixtures('gl_context')
def test_the_panels_button_hides_the_inset(demo):
    from OpenGLContext.events import synthetic  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    inset = demo.scene.getDEF('Inset')
    inset_was = inset.visible
    # The button's centre: the panel is 268 by 84 at (16, 16), the button 140
    # by 26 at (-52, -20) from its centre
    x, y = 16 + 134 - 52, 16 + 42 - 20
    with scene_context(demo.scene, size=SIZE) as context:
        context.OnDraw(force=1)
        for record in (
            {'type': 'mousemove', 'buttons': [], 'x': x, 'y': y, 'pick': True},
            {'type': 'mousebutton', 'button': 0, 'state': 1, 'x': x, 'y': y, 'pick': True},
            {'type': 'mousebutton', 'button': 0, 'state': 0, 'x': x, 'y': y, 'pick': True},
        ):
            synthetic.dispatch(context, record)
            context.OnDraw(force=1)
        for _ in range(120):
            if inset.visible != inset_was:
                break
            context.OnDraw(force=1)
    assert inset.visible is (not inset_was)
    demo.press('i')
