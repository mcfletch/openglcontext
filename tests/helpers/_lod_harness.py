"""Render an LOD node from two distances and report what was drawn.

The levels are told apart by colour rather than by shape, so what is read back
says which one the pass chose without depending on where its silhouette falls.
Reports ``key=value`` lines on stdout: ``near`` and ``far``, each ``r,g,b`` from
the middle of the frame.
"""
import os


def main():
    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
    os.environ['OPENGLCONTEXT_IBL'] = 'off'
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
    os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = '24'

    import numpy as np
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        Appearance, Box, DirectionalLight, Material, Shape, Transform,
        sceneGraph,
    )
    from OpenGLContext.scenegraph.lod import LOD

    #: Where the fine level gives way to the coarse one.
    EDGE = 20.0
    report = {}

    def level(colour):
        return Transform(children=[Shape(
            geometry=Box(size=(4, 4, 4)),
            appearance=Appearance(material=Material(
                diffuseColor=colour, emissiveColor=colour,
                ambientIntensity=1.0)))])

    class LODContext(BaseContext):
        def OnInit(self):
            self.lod = LOD(level=[level((1, 0, 0)), level((0, 0, 1))],
                           range=[EDGE])
            self.sg = sceneGraph(children=[
                self.lod,
                DirectionalLight(direction=(0, 0, -1), color=(1, 1, 1),
                                 intensity=1.0),
            ])
            self._frame = 0
            self.platform.setPosition((0, 0, 10))

        def OnIdle(self, *a):
            self.triggerRedraw(1)
            return 1

        def OnDraw(self, *a, **k):
            result = BaseContext.OnDraw(self, *a, **k)
            self._frame += 1
            if self._frame == 8:
                report['near'] = self._middle()
                report['near_level'] = self.lod.whichLevel
                self.platform.setPosition((0, 0, EDGE * 3))
            elif self._frame == 18:
                report['far'] = self._middle()
                report['far_level'] = self.lod.whichLevel
            return result

        def _middle(self):
            width, height = self.getViewPort()
            raw = glReadPixels(width // 2, height // 2, 1, 1, GL_RGB,
                               GL_UNSIGNED_BYTE)
            pixel = np.frombuffer(raw, dtype=np.uint8)
            return ','.join(str(int(v)) for v in pixel[:3])

        def OnQuit(self, *a, **k):
            for key, value in report.items():
                print('%s=%s' % (key, value), flush=True)
            return BaseContext.OnQuit(self, *a, **k)

    LODContext.ContextMainLoop()
    for key, value in report.items():
        print('%s=%s' % (key, value), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
