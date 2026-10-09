"""GeneratedCubeMapTexture and RenderedTexture: the scene drawn into textures

The schedule (no GL) says which are drawn each frame; the drawings are
checked by what a square wearing one shows.
"""
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.passes.generatedtextures import GeneratedSchedule

RENDERERS = ['pbr', 'vrml97']


class Node:
    def __init__(self, update='NONE'):
        self.update = update


def test_a_texture_asked_for_is_drawn_the_next_frame_and_none_once():
    schedule = GeneratedSchedule()
    node, path = Node('NONE'), object()
    assert schedule.request(node, path) is True       # new: ask for a frame
    assert schedule.take() == [(node, [path])]
    schedule.finished(node)
    schedule.request(node, path)
    assert schedule.take() == []


def test_always_is_drawn_every_frame_it_is_asked_for():
    schedule = GeneratedSchedule()
    node = Node('ALWAYS')
    for _frame in range(3):
        schedule.request(node)
        assert [found for found, _paths in schedule.take()] == [node]
        schedule.finished(node)
    assert schedule.take() == []
    assert schedule.drawn(node) == 3


def test_next_frame_only_is_drawn_once_more_then_is_none():
    schedule = GeneratedSchedule()
    node = Node('NONE')
    schedule.request(node)
    schedule.take()
    schedule.finished(node)
    node.update = 'NEXT_FRAME_ONLY'
    assert schedule.request(node) is False            # drawn before: no frame asked
    assert [found for found, _paths in schedule.take()] == [node]
    schedule.finished(node)
    assert node.update == 'NONE'


def test_each_shape_asking_is_kept_once():
    schedule = GeneratedSchedule()
    node, first, second = Node(), object(), object()
    schedule.request(node, first)
    schedule.request(node, second)
    schedule.request(node, first)
    assert schedule.take() == [(node, [first, second])]


def drawn(body, renderer, frames=3, size=32, edit=None):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene><Background skyColor="0 0 0"/>'
                         b'<Viewpoint position="0 0 2.4"/>' + body + b'</Scene></X3D>',
                         'scene.x3d')
    with scene_context(scene, size=(size, size), renderer=renderer) as context:
        for _frame in range(frames):
            context.OnDraw(force=1)
        image = drawn_image(context).astype(int)
        if edit is None:
            return image
        edit(scene)
        for _frame in range(frames):
            context.OnDraw(force=1)
        return image, drawn_image(context).astype(int)


def centre(image):
    height, width = image.shape[:2]
    return tuple(image[height // 2, width // 2])


def close(found, expected, tolerance=8):
    return all(abs(a - b) <= tolerance for a, b in zip(found, expected))


SQUARE = (b'<IndexedTriangleSet index="0 1 2 0 2 3" solid="false">'
          b'<Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/>'
          b'<TextureCoordinate point="0 0 1 0 1 1 0 1"/></IndexedTriangleSet>')


def wall(colour, z, name=b'Wall'):
    return (b'<Transform translation="0 0 %s"><Shape><Appearance>'
            b'<UnlitMaterial DEF="%s" emissiveColor="%s"/></Appearance>'
            b'<Box size="40 40 0.1"/></Shape></Transform>' % (z, name, colour))


def mirror(update=b'ALWAYS'):
    return (b'<Shape><Appearance><UnlitMaterial emissiveColor="1 1 1"/>'
            b'<GeneratedCubeMapTexture DEF="Cube" size="16" update="%s"/></Appearance>'
            % update + SQUARE + b'</Shape>')


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_generated_cube_map_reflects_the_scene_around_the_shape(gl_context, renderer):
    # The wall behind the camera is what the square reflects toward it.
    found = centre(drawn(mirror() + wall(b'0 1 0', b'6'), renderer))
    assert close(found, (0, 255, 0)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_generated_cube_map_left_at_none_keeps_its_first_drawing(gl_context, renderer):
    def recolour(scene):
        scene.getDEF('Wall').emissiveColor = (1, 0, 0)
    before, after = drawn(mirror(b'NONE') + wall(b'0 1 0', b'6'), renderer, edit=recolour)
    assert close(centre(before), (0, 255, 0)), centre(before)
    assert close(centre(after), (0, 255, 0)), centre(after)


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_generated_cube_map_set_to_next_frame_only_draws_again(gl_context, renderer):
    def recolour(scene):
        scene.getDEF('Wall').emissiveColor = (1, 0, 0)
        scene.getDEF('Cube').update = 'NEXT_FRAME_ONLY'
    before, after = drawn(mirror(b'NONE') + wall(b'0 1 0', b'6'), renderer, edit=recolour)
    assert close(centre(after), (255, 0, 0)), centre(after)


def picture(fields=b'', children=b''):
    return (b'<Shape><Appearance><UnlitMaterial emissiveColor="1 1 1"/>'
            b'<RenderedTexture width="16" height="16" update="ALWAYS" %s>%s</RenderedTexture>'
            b'</Appearance>' % (fields, children) + SQUARE + b'</Shape>')


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_rendered_texture_shows_its_viewpoints_view(gl_context, renderer):
    # Looking along +Z from the origin's far side at the blue wall behind the
    # camera, whatever the main camera sees.
    body = (picture(children=b'<Viewpoint containerField="viewpoint" position="0 0 1" '
                             b'orientation="0 1 0 3.14159"/>')
            + wall(b'0 0 1', b'6') + wall(b'1 0 0', b'-6', b'Back'))
    found = centre(drawn(body, renderer))
    assert close(found, (0, 0, 255)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_rendered_texture_draws_its_own_scene(gl_context, renderer):
    scene = (b'<Group containerField="scene"><Transform translation="0 0 -3"><Shape>'
             b'<Appearance><UnlitMaterial emissiveColor="1 1 0"/></Appearance>'
             b'<Box size="40 40 0.1"/></Shape></Transform></Group>')
    found = centre(drawn(picture(children=scene) + wall(b'1 0 0', b'-6'), renderer))
    assert close(found, (255, 255, 0)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_rendered_texture_draws_its_own_background(gl_context, renderer):
    background = b'<Background containerField="background" skyColor="0 0 1"/>'
    found = centre(drawn(picture(children=background), renderer))
    assert close(found, (0, 0, 255)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_depth_map_is_the_depth_drawn_in_grey(gl_context, renderer):
    # A wall half a metre in front of a viewpoint behind the square, whose
    # near plane is at 0.3: 0.4 of the depth buffer's range. Nothing is 1.
    viewpoint = (b'<Viewpoint containerField="viewpoint" position="0 0 -3" '
                 b'orientation="0 1 0 3.14159"/>')
    near = centre(drawn(picture(b'depthMap="true"', viewpoint) + wall(b'1 0 0', b'-2.45'),
                        renderer))
    empty = centre(drawn(picture(b'depthMap="true"', viewpoint), renderer))
    assert near[0] == near[1] == near[2]
    assert 60 < near[0] < 200, near
    assert empty[0] > 250, empty


def test_a_rendered_textures_engine_fields_are_carried_as_metadata():
    from OpenGLContext.scenegraph.renderedtexture import RenderedTexture  # noqa: PLC0415 kept with its use
    from vrml.x3d import extension  # noqa: PLC0415 kept with its use
    texture = RenderedTexture(update='ALWAYS', viewpoint=x3d.Viewpoint())
    names = {field.name for field in extension.added_fields(texture)}
    assert {'update', 'viewpoint', 'scene', 'background', 'fog'} <= names
