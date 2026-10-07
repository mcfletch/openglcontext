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
