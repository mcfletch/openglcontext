"""Capture runner for PBR render tests (invoked as a subprocess).

Renders a small PBR scene (a metallic gold sphere + a rough red sphere, both
PBRMaterial) under the PBR pass and saves the freshly-rendered back buffer.
Optionally loads a glTF/GLB instead (arg: 'gltf <path-or-url>').

Usage:  python tests/_pbr_capture.py OUTPUT.png [gltf SOURCE]
"""
import os
import sys


def main() -> int:
    out_path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else 'spheres'
    source = sys.argv[3] if len(sys.argv) > 3 else None

    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '0')
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')
    if mode == 'lightgrid':
        # The grid is the only thing meant to be lighting this scene. An
        # environment probe lights both spheres alike and would leave the
        # comparison measuring the probe.
        os.environ.setdefault('OPENGLCONTEXT_IBL', 'off')

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from OpenGLContext.capture import capture_to_png
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, Shape, Appearance, Sphere, Box, Teapot,
        DirectionalLight, PointLight,
    )
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture

    def blend_scene():
        # An opaque red sphere with a translucent (alphaMode=BLEND) unlit-blue
        # panel covering its left half. Where the panel overlaps the sphere the
        # framebuffer must show a red+blue blend, not pure blue (opaque) nor pure
        # red (panel dropped). Unlit blue makes the source colour deterministic.
        return sceneGraph(children=[
            Shape(
                geometry=Sphere(radius=1.1),
                appearance=Appearance(material=PBRMaterial(
                    baseColor=(0.9, 0.1, 0.08), metallic=0.0, roughness=0.6))),
            Transform(translation=(-0.7, 0, 2.5), children=[Shape(
                geometry=Box(size=(1.6, 3.0, 0.05)),
                appearance=Appearance(material=PBRMaterial(
                    baseColor=(0.1, 0.2, 0.95), unlit=True,
                    transparency=0.45, alphaMode='BLEND')))]),
            DirectionalLight(direction=(-0.3, -0.4, -1.0), color=(1, 1, 1), intensity=1.4),
            PointLight(location=(4, 4, 5), color=(1, 0.95, 0.9), intensity=1.0,
                       attenuation=(1, 0, 0)),
        ])

    def transmission_scene():
        # A red opaque sphere behind a near-clear glass panel (transmission=1)
        # covering its left half. With transmission the covered half shows the
        # red sphere through the glass; without it the panel is opaque and hides
        # the sphere. Pale-cyan glass tint keeps the two cases distinguishable.
        return sceneGraph(children=[
            Shape(
                geometry=Sphere(radius=1.1),
                appearance=Appearance(material=PBRMaterial(
                    baseColor=(0.9, 0.1, 0.08), metallic=0.0, roughness=0.6))),
            Transform(translation=(-0.7, 0, 2.5), children=[Shape(
                geometry=Box(size=(1.6, 3.0, 0.05)),
                appearance=Appearance(material=PBRMaterial(
                    baseColor=(0.6, 1.0, 0.9), metallic=0.0, roughness=0.05,
                    transmission=1.0, thickness=0.05, ior=1.5, alphaMode='OPAQUE')))]),
            DirectionalLight(direction=(-0.3, -0.4, -1.0), color=(1, 1, 1), intensity=1.4),
            PointLight(location=(4, 4, 5), color=(1, 0.95, 0.9), intensity=1.0,
                       attenuation=(1, 0, 0)),
        ])

    def spheres_scene():
        return sceneGraph(children=[
            Transform(translation=(-1.5, 0, 0), children=[Shape(
                geometry=Sphere(radius=1.1),
                appearance=Appearance(material=PBRMaterial(
                    baseColor=(1.0, 0.78, 0.34), metallic=1.0, roughness=0.25)))]),
            Transform(translation=(1.5, 0, 0), children=[Shape(
                geometry=Sphere(radius=1.1),
                appearance=Appearance(material=PBRMaterial(
                    baseColor=(0.85, 0.13, 0.1), metallic=0.0, roughness=0.7)))]),
            DirectionalLight(direction=(-0.3, -0.4, -1.0), color=(1, 1, 1), intensity=1.4),
            PointLight(location=(4, 4, 5), color=(1, 0.95, 0.9), intensity=1.0,
                       attenuation=(1, 0, 0)),
        ])

    state = {'pos': (0, 0, 6)}

    def teapot_scene():
        # A ceramic PBRMaterial on the non-glTF Teapot geometry: exercises the
        # full non-glTF PBR path (Shape -> PBRPass -> teapot VAO with texcoords +
        # tangents). Small texture size keeps the test fast.
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from _ceramic_textures import ceramic_textures
        tex = ceramic_textures(256)
        mat = PBRMaterial(
            baseColor=(1, 1, 1), metallic=0.0, roughness=1.0, normalScale=1.0,
            textures={
                'baseColor': PBRTexture(tex['baseColor'], srgb=True),
                'metallicRoughness': PBRTexture(tex['metallicRoughness'], srgb=False),
                'normal': PBRTexture(tex['normal'], srgb=False),
            })
        state['pos'] = (0, 1.0, 5.0)
        return sceneGraph(children=[
            Shape(geometry=Teapot(size=1.0, lid=True),
                  appearance=Appearance(material=mat)),
            DirectionalLight(direction=(-0.3, -0.5, -1.0), color=(1, 1, 1), intensity=2.0),
            PointLight(location=(4, 4, 5), color=(1, 0.95, 0.9), intensity=1.0,
                       attenuation=(1, 0, 0)),
        ])

    def lightmap_scene():
        # Two identical unlit-grey quads, no lights at all: the only illumination
        # is the baked lightmap on the left quad (a black->white horizontal ramp
        # on TEXCOORD_1). The right quad has none, so it stays at the flat ambient
        # level and gives the comparison baseline.
        import numpy as np
        from PIL import Image
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh

        ramp = np.tile(np.linspace(0, 255, 64, dtype='u1')[None, :, None], (64, 1, 3))
        lightmap = PBRTexture(Image.fromarray(ramp, 'RGB'), srgb=True)

        def quad(x, material):
            p = np.array([[x - 1, -1, 0], [x + 1, -1, 0],
                          [x + 1, 1, 0], [x - 1, 1, 0]], 'f')
            uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], 'f')
            return Shape(
                geometry=PBRMesh(
                    positions=p, normals=np.tile([0, 0, 1], (4, 1)).astype('f'),
                    texcoords=uv, texcoords1=uv,
                    indices=np.array([0, 1, 2, 0, 2, 3], 'I'), solid=False),
                appearance=Appearance(material=material))

        base = dict(baseColor=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.9)
        state['pos'] = (0, 0, 5.5)
        return sceneGraph(children=[
            quad(-1.2, PBRMaterial(texCoordMask=32, textures={'lightmap': lightmap},
                                   **base)),
            quad(1.2, PBRMaterial(**base)),
            # A near-dark light rather than none: a scene with no lights at all
            # gets a default headlight, which would wash both quads out and hide
            # what the lightmap contributes.
            DirectionalLight(direction=(0, 0, -1), color=(1, 1, 1), intensity=0.02),
        ])

    def lightgrid_scene():
        # Two identical spheres and no light worth the name: all the
        # illumination comes from a baked irradiance grid whose two samples sit
        # exactly where the spheres do -- bright on the left, black on the
        # right. Neither sphere carries a lightmap, which is the whole point:
        # the grid is what lights an object that has none.
        import numpy as np
        from OpenGLContext.scenegraph.lightgrid import LightGrid

        grey = dict(baseColor=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.9)

        def ball(x):
            return Transform(translation=(x, 0, 0), children=[Shape(
                geometry=Sphere(radius=1.1),
                appearance=Appearance(material=PBRMaterial(**grey)))])

        ambient = np.zeros((8, 3), dtype='f')
        directional = np.zeros((8, 3), dtype='f')
        # x varies fastest, so the even samples are the left-hand column.
        ambient[0::2] = 0.05
        directional[0::2] = 1.2
        state['pos'] = (0, 0, 5.5)
        return sceneGraph(children=[
            ball(-1.5), ball(1.5),
            LightGrid(counts=[2, 2, 2], origin=(-1.5, -3.0, -3.0),
                      spacing=(3.0, 6.0, 6.0), ambient=ambient,
                      directional=directional,
                      direction=np.tile((0.0, 1.0, 0.0), (8, 1)).astype('f')),
            # As in lightmap_scene: a near-dark light rather than none, since a
            # scene with no lights at all is given a headlight that would light
            # both spheres and hide what the grid contributes.
            DirectionalLight(direction=(0, 0, -1), color=(1, 1, 1), intensity=0.02),
        ])

    def gltf_scene():
        from OpenGLContext.loaders import gltf
        # sc.group is the model's root Transform (one child Transform per glTF
        # node); sc.getDEF(name) reaches an individual node.
        sc = gltf.load_gltf_url(source) if source.startswith('http') else gltf.load_gltf(source)
        cx, cy, cz = sc.center
        r = sc.radius or 1.0
        state['pos'] = (cx, cy, cz + r * 3.2)
        return sceneGraph(children=[
            sc.group,
            DirectionalLight(direction=(-0.3, -0.5, -1.0), color=(1, 1, 1), intensity=1.3),
            PointLight(location=(cx + r * 2, cy + r * 2, cz + r * 2),
                       color=(1, 0.95, 0.9), intensity=1.0, attenuation=(1, 0, 0)),
        ])

    class CaptureContext(BaseContext):
        def OnInit(self):
            if mode == 'gltf':
                self.sg = gltf_scene()
            elif mode == 'blend':
                self.sg = blend_scene()
            elif mode == 'transmission':
                self.sg = transmission_scene()
            elif mode == 'teapot':
                self.sg = teapot_scene()
            elif mode == 'lightmap':
                self.sg = lightmap_scene()
            elif mode == 'lightgrid':
                # No flat ambient fill either: it stands in for lights a scene
                # does not have, and this one is lit by the grid.
                self.gltf_scene_ambient = 0.0
                self.sg = lightgrid_scene()
            else:
                self.sg = spheres_scene()
            self.platform.setPosition(state['pos'])

        def SwapBuffers(self):
            capture_to_png(out_path)
            return super().SwapBuffers()

    CaptureContext.ContextMainLoop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
