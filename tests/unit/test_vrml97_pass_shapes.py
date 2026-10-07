"""Shapes in the VRML97 pass: per-vertex colours, and instanced groups' textures.

X3D (19775-1, 17.2.2.4): a Color node's colours replace the Material's
diffuseColor. ElevationGrid and X3D's triangle sets draw as meshes through the
pass's lit program, which reads the colours where the mesh carries them.
Repeated shapes drawn as one instanced group keep their appearance's texture.
"""
import pytest

GRID = (b"<X3D version='3.3'><Scene><Viewpoint position='4 6 4' orientation='1 0 0 -1.57'/>"
        b"<Shape><Appearance><Material/></Appearance>"
        b"<ElevationGrid xDimension='2' zDimension='2' xSpacing='8' zSpacing='8' height='0 0 0 0'>"
        b"<Color color='1 0 0 1 0 0 1 0 0 1 0 0'/></ElevationGrid></Shape>"
        b"%s</Scene></X3D>")
#: A grey box beside the grid, drawn after it with the same program.
BOX = (b"<Transform translation='6 0 6'><Shape><Appearance><Material diffuseColor='0.5 0.5 0.5'/>"
       b"</Appearance><Box size='2 0.5 2'/></Shape></Transform>")


def drawn(document, size=(32, 32)):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(document, 'a.x3d'), size=size, renderer='vrml97') as context:
        drawn_image(context)
        return drawn_image(context).astype(int)


def test_an_elevation_grids_colours(gl_context):
    centre = drawn(GRID % b'')[16, 16]
    assert centre[0] > centre[1] + 80 and centre[0] > centre[2] + 80, centre


def test_a_shape_after_it_has_its_own_material(gl_context):
    image = drawn(GRID % BOX)
    grey = image[28, 28]
    assert abs(int(grey[0]) - int(grey[1])) < 20 and grey[1] > 20, grey


def test_shapes_drawn_as_one_instanced_group_keep_their_texture(gl_context):
    """Four uses of one textured shape are drawn together, textured"""
    shape = (b"<Shape DEF='S'><Appearance><Material diffuseColor='1 1 1'/>"
             b"<PixelTexture image='1 1 3 0xFF0000'/></Appearance><Box size='1 1 1'/></Shape>")
    uses = b''.join(b"<Transform translation='%d 0 0'><Shape USE='S'/></Transform>" % (i * 2)
                    for i in range(1, 4))
    image = drawn(b"<X3D version='3.3'><Scene><Viewpoint position='3 0 12'/><Transform>"
                  + shape + b"</Transform>" + uses + b"</Scene></X3D>", size=(64, 32))
    for column in (22, 29, 35, 42):
        red = image[16, column]
        assert red[0] > red[1] + 100, (column, red)
