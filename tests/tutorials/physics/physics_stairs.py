#! /usr/bin/env python
'''=Physics: a ball rolls down the stairs=

[physics_stairs.py-screen-0001.png Screenshot]

A context has a physics world, ``self.physics``, made the first time the
script mentions it. Putting a body in the world takes one call, and the world
steps itself: the script has no clock, no tick and no redraw request. Geometry
that is in the scene is a static body, so the stairs hold the ball up without
being mentioned.

The tutorials after this one start from this scene and add a few lines each.
'''
from OpenGLContext.context import Context
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
)

'''A game loads its stairs and its ball from files with
``self.sceneLoader.load_now('stairs.glb').result.group``. This script builds
them from the engine's procedural surfaces so that it needs no file:
``surfaces.block`` and ``surfaces.sphere`` make geometry, ``pbr_material``
wears a stone or a metal on it, and ``surfaces.shape`` puts the two in a node.
The stairs go down toward +Z from a landing, in steps of 0.6 m run and 0.25 m
rise.'''
STEPS = 8
RISE = 0.25
RUN = 0.6
RADIUS = 0.25
#: Where the ball starts: on the landing, a hair above it.
START = (0, STEPS * RISE + RADIUS + 0.01, -1.0)


def make_stairs():
    '''Eight sandstone steps and a landing on a floor. Each step is a block
    standing on the floor, so the stairs are solid.'''
    stone = surfaces.pbr_material(surfaces.sandstone(256), roughness=0.9)
    top = STEPS * RISE
    parts = [
        surfaces.shape(surfaces.block((12, 0.2, 14)), stone, translation=(0, -0.1, 2)),
        surfaces.shape(surfaces.block((3, top, 2)), stone, translation=(0, top / 2, -1)),
    ]
    for step in range(STEPS):
        height = (STEPS - step) * RISE
        parts.append(surfaces.shape(
            surfaces.block((3, height, RUN)), stone,
            translation=(0, height / 2, step * RUN + RUN / 2)))
    return Transform(children=parts)


def make_ball():
    '''A ball of brushed steel.'''
    steel = surfaces.pbr_material(
        surfaces.brushed_metal(256, surfaces.STEEL), roughness=0.4)
    return surfaces.shape(surfaces.sphere(RADIUS, 32), steel)


def material_of(node):
    '''The material a node made by ``surfaces.shape`` wears. A model file names
    its materials, and a script reads one as ``loaded.materials['Ball']``.'''
    return node.children[0].appearance.material


class StairsContext(Context):
    '''The scene of every tutorial in this series: a sky, a light, the stairs
    and the ball. The camera looks along +X from the side, so the steps show
    in profile. This class mentions no physics.'''
    initialPosition = (-8, 1.5, 1.6)
    initialOrientation = (0, 1, 0, -1.5708)

    def OnInit(self):
        self.stairs = make_stairs()
        self.ball = make_ball()
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.65, 0.8)]),
            DirectionalLight(direction=(0.5, -0.7, -0.2), intensity=3.0),
            self.stairs,
            self.ball,
        ])


class TestContext(StairsContext):
    def OnInit(self):
        super().OnInit()
        '''``add_dynamic`` makes the ball a body the world moves. ``translation``
        places the ball and adds it in one call. ``mass`` is in kilograms and
        ``restitution`` is the fraction of its speed the ball keeps from a
        bounce.'''
        self.body = self.physics.add_dynamic(
            self.ball, translation=START, mass=2.0, restitution=0.4)
        '''An impulse is in newton-seconds, so 8 N*s on a 2 kg ball is 4 m/s,
        along +Z and down the stairs.'''
        self.body.apply_impulse((0, 0, 8))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
