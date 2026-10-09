#! /usr/bin/env python
'''=X3D: X_ITE's materials, modes and instances=

[x3d_materials.py-screen-0001.png Screenshot]

``oglc-x3d-materials`` opens ``x3d_materials.x3d``, an X3D 4.0 document that
names X_ITE's component and uses its nodes:

* a row of spheres whose ``PhysicalMaterial`` holds material extension
  nodes in its ``extensions``: clearcoat over red metal, sheen on velvet,
  iridescence on steel, glass with transmission, volume and an index of
  refraction, brushed brass with anisotropy, and a wax candle with diffuse
  transmission, volume and volume scatter; and a gold
  ``SpecularGlossinessMaterial`` at the end of the row;
* sandstone pillars, one ``InstancedShape`` placed by its ``translations``
  and ``rotations``;
* a safety sign whose ``RetroreflectionMaterialExtension`` sends the lamp
  beside the eye back to it, a pane whose ``BlendMode`` adds its colour to
  what is behind it, a marker whose ``DepthMode`` draws it over everything,
  and a banner whose ``FogCoordinate`` fades its right side into the fog;
* a crate wearing an ``ImageTextureAtlas``, a 3D texture cut from the tiles
  of one picture.
'''
import os
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_materials import Showcase
from OpenGLContext.loaders import background


class TestContext(BaseContext):

    def OnInit(self):
        '''The showcase writes the document and the maps it names, and reads
        it with ``Loader.load``.'''
        self.showcase = Showcase(tempfile.mkdtemp(prefix='x3d-materials-'))
        background.wait_for_idle(20.0)
        self.sg = self.showcase.scene
        '''``r`` switches the sign's retroreflection, ``x`` the candle's
        volume scatter, ``f`` the banner's fog depths, and ``w`` writes the
        scene back as X3D in each encoding.'''
        for key in Showcase.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(Showcase.help())

    def OnKey(self, event):
        said = self.showcase.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
