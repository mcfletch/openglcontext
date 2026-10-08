"""X3D's fog in the VRML97 pass, which shades a Material by X3D's own equation.

X3D (19775-1, 17.2.2.3): the displayed colour is lerp(f, fogColor, colour),
f the object's share: (range - d) / range for LINEAR, exp(-d / (range - d))
for EXPONENTIAL.
"""
import numpy as np
import pytest

WALL = b'''<X3D version="3.3"><Scene>
  <NavigationInfo headlight="false"/>
  <Viewpoint position="0 0 0"/>
  <Fog color="1 1 1" visibilityRange="20" fogType="%s"/>
  <Shape><Appearance>%s</Appearance>
    <IndexedFaceSet coordIndex="0 1 2 3">
      <Coordinate point="-50 -50 -10 50 -50 -10 50 50 -10 -50 50 -10"/></IndexedFaceSet></Shape>
</Scene></X3D>'''

MATERIALS = {
    'lit': b'<Material diffuseColor="0 0 0" specularColor="0 0 0"/>',
    'unlit': b'<PixelTexture image="1 1 3 0x000000"/>',
}


@pytest.mark.parametrize('fog_type', [b'LINEAR', b'EXPONENTIAL'])
@pytest.mark.parametrize('appearance', sorted(MATERIALS))
def test_x3ds_fog_in_the_vrml97_pass(gl_context, fog_type, appearance):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(WALL % (fog_type, MATERIALS[appearance]), 'a.x3d')
    with scene_context(scene, size=(32, 32), renderer='vrml97') as context:
        drawn_image(context)
        centre = drawn_image(context)[16, 16].astype(int)
    share = 0.5 if fog_type == b'LINEAR' else np.exp(-10.0 / 10.0)
    assert tuple(centre) == pytest.approx([255 * (1 - share)] * 3, abs=8)


def _grid(kind):
    """Black lines or points close enough to fill the view, at 10 units"""
    steps = np.linspace(-6.0, 6.0, 121)
    if kind == 'lines':
        points = ' '.join('-6 %g -10 6 %g -10' % (y, y) for y in steps)
        index = ' '.join('%d %d -1' % (2 * n, 2 * n + 1) for n in range(len(steps)))
        geometry = ('<IndexedLineSet coordIndex="%s"><Coordinate point="%s"/></IndexedLineSet>'
                    % (index, points))
    else:
        points = ' '.join('%g %g -10' % (x, y) for x in steps for y in steps)
        geometry = '<PointSet><Coordinate point="%s"/></PointSet>' % points
    return ('<Shape><Appearance><Material emissiveColor="0 0 0"/></Appearance>%s</Shape>'
            % geometry).encode()


@pytest.mark.parametrize('kind', ['lines', 'points'])
@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_points_and_lines_are_fogged(gl_context, kind, renderer):
    """Points and lines are drawn by programs of their own, which take the
    frame's fog as the shapes' program does"""
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    document = WALL.replace(b'%s</Appearance>', b'</Appearance>').split(b'<Shape>')[0]
    scene = Loader.loads(document % b'LINEAR' + _grid(kind) + b'</Scene></X3D>', 'a.x3d')
    with scene_context(scene, size=(32, 32), renderer=renderer) as context:
        drawn_image(context)
        centre = drawn_image(context)[8:24, 8:24].astype(int)
    assert centre.max() == pytest.approx(255 * 0.5, abs=8)


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
@pytest.mark.parametrize('fogged', [False, True])
def test_a_shape_with_no_material_is_unlit_white(gl_context, renderer, fogged):
    """X3D (17.2.2.4): no Material, no lighting, a white surface; fogged at
    half the range under black fog, half of it is left"""
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    fog = b'black' if fogged else None
    document = WALL.replace(b'<Fog color="1 1 1"', b'<Fog color="0 0 0"') if fog else \
        WALL.replace(b'<Fog color="1 1 1" visibilityRange="20" fogType="%s"/>', b'')
    if fog:
        document = document.replace(b'fogType="%s"', b'fogType="LINEAR"')
    scene = Loader.loads(document % b'', 'a.x3d')
    with scene_context(scene, size=(32, 32), renderer=renderer) as context:
        drawn_image(context)
        centre = drawn_image(context)[16, 16].astype(int)
    assert tuple(centre) == pytest.approx([127.5 if fogged else 255] * 3, abs=8)
