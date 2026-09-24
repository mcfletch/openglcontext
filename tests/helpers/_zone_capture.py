"""Capture runner for zone render tests (invoked as a subprocess).

A grey floor runs under two grey spheres, and a zone covers the left half of
the floor and the left sphere. The camera looks down at all of it, so one
image shows an object wholly inside a zone, one wholly outside and a floor
that crosses the zone's edge.

Modes:

``none``      no zone: the baseline.
``dim``       the zone scales the environment to a tenth.
``capture``   the zone captures its own probe, from inside a box of walls
              around the left sphere whose roof is open to a black sky.
``lights``    a red point light over the left sphere is named by the zone, so
              it lights nothing outside it.
``nolights``  the same light and no zone, so it lights both halves.

Usage:  python tests/helpers/_zone_capture.py OUTPUT.png MODE
"""
import os
import sys


def main() -> int:
    out_path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else 'none'

    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '0')
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    os.environ['OPENGLCONTEXT_IBL'] = 'full'
    os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '10')

    from OpenGLContext.capture import capture_to_png
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        Appearance, Box, DirectionalLight, PointLight, Shape, Sphere,
        Transform, Zone, ZoneEnvironment, ZoneLights, sceneGraph,
    )
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

    def grey():
        return Appearance(material=PBRMaterial(
            baseColor=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.7))

    def scene():
        children = [
            Transform(translation=(0, -1.2, 0), children=[
                Shape(geometry=Box(size=(12.0, 0.2, 6.0)), appearance=grey())]),
            Transform(translation=(-2.5, 0, 0), children=[
                Shape(geometry=Sphere(radius=1.0), appearance=grey())]),
            Transform(translation=(2.5, 0, 0), children=[
                Shape(geometry=Sphere(radius=1.0), appearance=grey())]),
            # Barely a light: the environment is what these tests measure,
            # and a scene with no light at all is given a headlight.
            DirectionalLight(direction=(0, -1, 0), color=(1, 1, 1), intensity=0.02),
        ]
        settings = []
        if mode == 'dim':
            settings = [ZoneEnvironment(intensity=0.1)]
        elif mode == 'capture':
            settings = [ZoneEnvironment(capture=True)]
            wall = Box(size=(0.2, 3.0, 4.0))
            side = Box(size=(4.0, 3.0, 0.2))
            children.extend(
                Transform(translation=where, children=[Shape(geometry=box, appearance=grey())])
                for where, box in (((-4.6, 0.3, 0), wall), ((-0.4, 0.3, 0), wall),
                                   ((-2.5, 0.3, -2.1), side), ((-2.5, 0.3, 2.1), side)))
        if mode in ('lights', 'nolights'):
            light = PointLight(location=(-2.5, 2.5, 0), color=(1.0, 0.1, 0.1),
                               intensity=4.0, attenuation=(1, 0, 0))
            children.append(light)
            if mode == 'lights':
                settings = [ZoneLights(lights=[light])]
        if settings:
            children.append(Transform(translation=(-3.0, 0.0, 0.0), children=[
                Zone(size=(6.0, 4.0, 6.0), blend=0.0, settings=settings)]))
        return sceneGraph(children=children)

    class CaptureContext(BaseContext):
        def OnInit(self):
            self.gltf_scene_ambient = 0.0
            self.sg = scene()
            self.platform.setPosition((0.0, 7.0, 7.0))
            self.platform.setOrientation((1.0, 0.0, 0.0, -0.78))

        def SwapBuffers(self):
            capture_to_png(out_path)
            return super().SwapBuffers()

    CaptureContext.ContextMainLoop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
