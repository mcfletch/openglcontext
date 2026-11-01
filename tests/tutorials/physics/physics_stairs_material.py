#! /usr/bin/env python
'''=Physics: a new material=

[physics_stairs_material.py-screen-0001.png Screenshot]

A material says how a surface grips and bounces. Four are defined from the
start: ``wood``, ``metal``, ``rubber`` and ``ice``. ``physics.materials.define``
adds others, and a body takes one by name.

The stairs of :doc:`physics_stairs` are split into two lanes. The left lane is
wet stone, a material defined here: slippery, and dead to a bounce. The right
lane is rubber matting, the preset. Each lane has a wooden crate on its landing
and a steel ball dropped onto it, and the two lanes' crates and balls get the
same push down the stairs. The crate on the wet stone skids off the landing and
slides down to the floor; the crate on the rubber stops on its landing, 1.4 m
from where it started. The ball dropped on the rubber bounces 0.6 m back up;
the ball dropped on the wet stone rises 6 cm.
'''
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
)

from physics_stairs import RADIUS, RISE, RUN, STEPS, StairsContext, make_ball

'''Each lane is 2.4 m wide, centred 1.3 m either side of the middle, with a
0.2 m gap between them. The crates are 0.5 m cubes. Each ball starts 2 m above
its landing, and each crate stands on the landing 1.6 m behind the first step.'''
WIDTH = 2.4
LANES = {'wet-stone': -1.3, 'rubber': 1.3}
CRATE = 0.5
TOP = STEPS * RISE
DROP = 2.0
BACK = -1.6


def make_flight(maps, x, roughness):
    '''A landing and eight steps, ``WIDTH`` wide and centred on ``x``, of the
    stone or matting ``maps`` describes.'''
    wearing = surfaces.pbr_material(maps, roughness=roughness)
    parts = [surfaces.shape(surfaces.block((WIDTH, TOP, 2)), wearing,
                            translation=(x, TOP / 2, -1))]
    for step in range(STEPS):
        height = (STEPS - step) * RISE
        parts.append(surfaces.shape(
            surfaces.block((WIDTH, height, RUN)), wearing,
            translation=(x, height / 2, step * RUN + RUN / 2)))
    return Transform(children=parts)


def make_crate():
    '''A crate of planed oak.'''
    oak = surfaces.pbr_material(surfaces.wood(256), roughness=0.8)
    return surfaces.shape(surfaces.block((CRATE, CRATE, CRATE)), oak)


class TestContext(StairsContext):
    '''The camera stands below the stairs and to the right, so that both lanes
    and the drop of each step show.'''
    initialPosition = (6.0, 3.8, 7.6)
    initialOrientation = (-0.3413, 0.9302, 0.1349, 0.8039)

    def OnInit(self):
        '''The wet stone is a black marble with a polish on it, and the
        matting is black rubber tiles. The floor is the sandstone of the series.'''
        self.flights = {
            'wet-stone': make_flight(
                surfaces.marble(256, base=(0.08, 0.09, 0.11), vein=(0.42, 0.44, 0.47),
                                polish=0.1), LANES['wet-stone'], 1.0),
            'rubber': make_flight(
                surfaces.tiles(256, count=6, colour=(0.05, 0.05, 0.055),
                               grout=(0.16, 0.16, 0.16), glaze=0.9),
                LANES['rubber'], 1.0),
        }
        sandstone = surfaces.pbr_material(surfaces.sandstone(256), roughness=0.9)
        floor = surfaces.shape(surfaces.block((12, 0.2, 14)), sandstone,
                               translation=(0, -0.1, 2))
        self.balls = {name: make_ball() for name in LANES}
        self.crates = {name: make_crate() for name in LANES}
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.65, 0.8)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.5), intensity=3.0),
            floor, *self.flights.values(), *self.balls.values(), *self.crates.values(),
        ])
        '''``friction`` is the coefficient of friction, as a pair of surfaces
        slides and as they hold; 0.05 is nearly ice and 1.0 is rubber on
        concrete. ``restitution`` is the fraction of the closing speed a bounce
        returns, from 0 for clay to 1 for a bounce that loses nothing.'''
        self.physics.materials.define('wet-stone', friction=0.05, restitution=0.0)
        '''The flights are in the scene, so they are already static. Adding one
        again with a material replaces the body the scene made for it. Doing it
        before the first frame, as here, means the scene's body is never made.'''
        self.lanes = {name: self.physics.add_static(flight, material=name)
                      for name, flight in self.flights.items()}
        '''Where two bodies meet, each coefficient is the average of the two
        materials'. The crates are ``wood``, which has a friction of 0.4 and a
        restitution of 0.2, so a crate grips the wet stone at 0.225 and the
        rubber at 0.65. The ball has a restitution of 0.4, so it keeps 20% of
        its speed from a bounce on the wet stone and 60% on the rubber.

        The pushes are the same in both lanes: 45 N*s on a 10 kg crate is
        4.5 m/s, and 4 N*s on a 2 kg ball is 2 m/s.'''
        self.bodies = {}
        for name, x in LANES.items():
            crate = self.physics.add_dynamic(
                self.crates[name], proxy='box', material='wood', mass=10.0,
                translation=(x + 0.6, TOP + CRATE / 2 + 0.01, BACK))
            ball = self.physics.add_dynamic(
                self.balls[name], mass=2.0, restitution=0.4,
                translation=(x - 0.6, TOP + RADIUS + DROP, BACK))
            crate.apply_impulse((0, 0, 45))
            ball.apply_impulse((0, 0, 4))
            self.bodies[name] = crate, ball


if __name__ == '__main__':
    TestContext.ContextMainLoop()
