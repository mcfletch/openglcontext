#! /usr/bin/env python
'''=Physics: choosing the collision shape=

[physics_stairs_shapes.py-screen-0001.png Screenshot]

The world does not collide with the triangles a body draws. It collides with a
shape that stands for them, a *proxy*, and the proxy decides what the body costs
and how it behaves. Left alone, a body's proxy is cooked from its mesh: a sphere
or box where the mesh is exactly one, otherwise a convex hull. ``proxy=`` says
which to use, and ``physics.show_proxies(True)`` draws the proxies over the scene
so the choice can be seen.

This tutorial gives four things a shape: the ball, a stack of crates, a barrel
and a bollard.
'''
import math

from physics_stairs import START, StairsContext
from OpenGLContext.scenegraph import surfaces


def ring(radius, sides):
    '''The outline of a regular polygon, for ``surfaces.prism``.'''
    return [(radius * math.cos(2 * math.pi * k / sides),
             radius * math.sin(2 * math.pi * k / sides)) for k in range(sides)]


class TestContext(StairsContext):
    '''The camera backs away to see the foot of the stairs as well.'''
    initialPosition = (-10.5, 1.6, 3.4)

    def OnInit(self):
        super().OnInit()
        wood = surfaces.pbr_material(surfaces.wood(256), roughness=0.7)
        '''The proxies are drawn as wireframes over the scene, for as long as
        the call stays on. ``show_proxies(False)`` takes them out.'''
        self.physics.show_proxies(True)
        '''``'sphere'`` fits a sphere to the bounds of the mesh. For a mesh
        that is already a sphere it changes nothing, and for any other it is the
        cheapest shape the world has.'''
        self.body = self.physics.add_dynamic(
            self.ball, proxy='sphere', translation=START, mass=2.0, restitution=0.4)
        self.body.apply_impulse((0, 0, 8))
        '''``physics.cook`` makes a proxy once, from a node, and every body made
        with it shares the shape: the world holds one box for all six crates.
        ``'box'`` fits a box to the bounds of the mesh.'''
        crate = surfaces.shape(surfaces.block((0.5, 0.5, 0.5)), wood)
        self.crate_shape = self.physics.cook(crate, 'box')
        self.crates = []
        for x, y in ((-0.6, 0.25), (0.0, 0.25), (0.6, 0.25), (-0.3, 0.75), (0.3, 0.75),
                     (0.0, 1.25)):
            node = surfaces.shape(surfaces.block((0.5, 0.5, 0.5)), wood)
            self.sg.children.append(node)
            self.crates.append(self.physics.add_dynamic(
                node, proxy=self.crate_shape, translation=(x, y, 7.2), mass=4.0))
        '''A proxy can be another node. The barrel is drawn with 64 sides, and
        the world collides with the 10 sided barrel in ``hull``, which is not in
        the scene: a body is as costly as its proxy, however fine its mesh.'''
        barrel = surfaces.shape(surfaces.prism(ring(0.3, 64), 0.9), wood)
        hull = surfaces.shape(surfaces.prism(ring(0.3, 10), 0.9), wood)
        self.sg.children.append(barrel)
        self.barrel = self.physics.add_dynamic(
            barrel, proxy=hull, translation=(1.2, 0.45, 5.6), mass=20.0)
        '''``'convex'`` takes the convex hull of the mesh, which is exact for
        any convex solid such as this hexagonal bollard.'''
        bollard = surfaces.shape(surfaces.prism(ring(0.2, 6), 0.8), wood)
        self.sg.children.append(bollard)
        self.bollard = self.physics.add_dynamic(
            bollard, proxy='convex', translation=(-1.2, 0.4, 5.6), mass=10.0)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
