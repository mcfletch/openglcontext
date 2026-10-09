#! /usr/bin/env python
'''=X3D: volume rendering, three ways=

[x3d_volume.py-screen-0001.png Screenshot]

``oglc-x3d-volume`` opens ``x3d_volume.x3d``, an X3D 4 document using the
VolumeRendering component. The data is a generated CT scan of an ammonite:
the shell wall, the septa between its chambers, the siphuncle threading
them and the sediment in its last chambers, blurred over a voxel and given a
scanner's noise. Each specimen sits on a steel rod that passes through it,
and the rod is hidden where the volume is in front of it:

* on the left a ``VolumeData`` drawn through an ``OpacityMapVolumeStyle``
  whose transfer function hides the sediment and colours the shell, composed
  with a ``SilhouetteEnhancementVolumeStyle``; keys 1 to 9 and 0 give it
  each of the ten render styles in turn;
* in the centre a ``SegmentedVolumeData``, turning: the shell wall shaded by
  a ``ShadedVolumeStyle``, the septa tone-mapped, the siphuncle's edges
  darkened and the sediment's boundaries kept; s shows or hides the sediment;
* on the right an ``IsoSurfaceVolumeData``: the sediment's surface,
  translucent, and the shell's in cartoon shading; i steps the inner
  surface's value.
'''
import os
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_volume import VolumeScene
from OpenGLContext.loaders import background


class TestContext(BaseContext):

    def OnInit(self):
        '''The scene writes the scans, the transfer function and the surface
        maps beside a copy of the document, and reads it with ``Loader.load``.'''
        self.volumes = VolumeScene(tempfile.mkdtemp(prefix='x3d-volume-'))
        background.wait_for_idle(20.0)
        self.sg = self.volumes.scene
        for key in VolumeScene.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(VolumeScene.help())

    def OnKey(self, event):
        said = self.volumes.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
