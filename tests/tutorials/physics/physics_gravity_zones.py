#! /usr/bin/env python
'''=Physics: gravity zones (OMI_physics_gravity)=

[physics_gravity_zones.py-screen-0001.png Screenshot]

A central "planet" carries a **point** gravity zone: loose debris scattered
around it falls *inward* toward the centre instead of straight down, because
the zone replaces the world's gravity within its radius.  This is the
``OMI_physics_gravity`` zone resolved by priority and ``replace``, made with
``physics.add_gravity_zone``.
'''
import numpy as np

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.physics.zones import Sphere
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

#: The zone's radius, in metres, and the strength of the pull at any point of
#: it, in metres a second squared.
RADIUS = 30.0
PULL = 12.0


class TestContext(BaseContext):
    initialPosition = (0, 6, 22)

    def OnInit(self):
        self.rng = np.random.RandomState(3)
        self.debris = []
        '''The world has no gravity of its own here, so a body outside the
        zone floats.  ``toward`` is the point a zone pulls at; a ``priority``
        above another's wins, and ``replace`` drops the lower ones rather than
        adding to them.'''
        self.physics.gravity = (0, 0, 0)
        self.zone = self.physics.add_gravity_zone(
            Sphere((0, 0, 0), RADIUS), gravity=PULL, toward=(0, 0, 0),
            priority=5, replace=True)
        self.build()
        print(__doc__)
        self.addEventHandler('keypress', name='r', function=self.on_reset)

    def on_reset(self, event):
        self.build()

    def build(self):
        planet = surfaces.shape(
            surfaces.sphere(1.6, 32),
            surfaces.pbr_material(surfaces.marble(256, base=(0.5, 0.65, 0.85))))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.03, 0.03, 0.08)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.5),
            planet,
        ])
        for body in self.debris:
            body.remove()
        self.debris = []
        '''The planet is a shape of the scene, so it is static.  The debris is
        fourteen boxes scattered about it.'''
        crate = PhysicalMaterial(baseColor=(0.8, 0.6, 0.4), metallic=0.0, roughness=0.6)
        for _ in range(14):
            d = self.rng.normal(size=3)
            d /= np.linalg.norm(d)
            node = surfaces.shape(surfaces.block((0.7, 0.7, 0.7)), crate)
            self.sg.children.append(node)
            self.debris.append(self.physics.add_dynamic(
                node, translation=tuple(d * self.rng.uniform(6, 9))))
        self.physics.show_proxies(True)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
