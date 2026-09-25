"""Bake a zone's light offscreen and report it (invoked as a subprocess).

A grey sphere stands in a box of walls whose roof is open to a black sky, and a
zone covering it captures its environment. An offscreen context that asks for
the PBR pass and the full probe through its own class and definition -- not
through the environment -- bakes the zone with
:func:`OpenGLContext.passes.zonebake.bake_zone_lights`. What was baked is
printed as one line of JSON.

Usage:  python tests/helpers/_zone_bake.py
"""
import json
import os
import sys

from OpenGLContext.eglcontext import EGLContext
from OpenGLContext.passes.zonebake import bake_zone_lights
from OpenGLContext.scenegraph.basenodes import (
    Appearance,
    Box,
    DirectionalLight,
    sceneGraph,
    Shape,
    Sphere,
    Transform,
    Zone,
    ZoneEnvironment,
)
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


def main() -> int:
    for name in ('OPENGLCONTEXT_RENDERER', 'OPENGLCONTEXT_IBL', 'OPENGLCONTEXT_PROFILE'):
        os.environ.pop(name, None)

    def grey():
        return Appearance(material=PBRMaterial(
            baseColor=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.7))

    wall, side = Box(size=(0.2, 3.0, 4.0)), Box(size=(4.0, 3.0, 0.2))
    zone = Zone(size=(6.0, 4.0, 6.0), blend=0.0,
                settings=[ZoneEnvironment(capture=True)])
    children = [
        Transform(translation=(0, -1.2, 0), children=[
            Shape(geometry=Box(size=(12.0, 0.2, 6.0)), appearance=grey())]),
        Shape(geometry=Sphere(radius=1.0), appearance=grey()),
        DirectionalLight(direction=(0, -1, 0), color=(1, 1, 1), intensity=1.0),
        *(Transform(translation=where, children=[Shape(geometry=box, appearance=grey())])
          for where, box in (((-2.1, 0.3, 0), wall), ((2.1, 0.3, 0), wall),
                             ((0, 0.3, -2.1), side), ((0, 0.3, 2.1), side))),
        zone,
    ]

    class Baker(EGLContext):
        renderer = 'pbr'
        profile = 'core'

        def OnInit(self):
            self.sg = sceneGraph(children=children)

    seen = []
    with Baker(size=(64, 64), ibl='full') as context:
        baked = bake_zone_lights(context, progress=lambda done, total: seen.append((done, total)))
    report = {
        'baked': len(baked),
        'is_zone': [one.zone is zone for one in baked],
        'irradiance_faces': [len(one.irradiance) for one in baked],
        'mip_levels': [len(one.mips) for one in baked],
        'finite': [bool(all(float(abs(face).max()) < 1e30 for face in one.irradiance))
                   for one in baked],
        'progress': seen,
        'environment': sorted(name for name in ('OPENGLCONTEXT_RENDERER',
                                                'OPENGLCONTEXT_IBL',
                                                'OPENGLCONTEXT_PROFILE')
                              if name in os.environ),
    }
    print('BAKED ' + json.dumps(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
