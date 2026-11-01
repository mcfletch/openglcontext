#! /usr/bin/env python
'''=Running along a trail=

[character_trail.py-screen-0001.png Screenshot]

A runner in a game with a course follows a line and hops between lanes beside
it. ``run_along`` gives a character a course to follow: each frame it runs at
a speed along the line and steers back onto its lane, and the land, slopes and
jumps stay the character's own. Here the fox runs a winding trail over the
hills of :doc:`character_run`, the camera swings round behind it, and three
keys hop it between three lanes.

Keys:
    1 2 3   the left, middle and right lane
    space   jump
'''
import math

import numpy as np

from character_run import FOX, LAND, LandContext
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.scenegraph.basenodes import Shape
from OpenGLContext.scenegraph.road import RoadProfile, road_mesh

'''The trail is a centreline: points a metre apart, winding from side to side
as it runs toward +Z, each at the height of the land under it. A game reads
its course from a road, a level file or a spline; anything that gives points
will do.'''
LENGTH = 120.0


def centreline(spacing=1.0):
    z = np.arange(0.0, LENGTH + spacing, spacing)
    x = 7.0 * np.sin(z / 14.0)
    y = np.array([float(LAND.sample(a, b)) for a, b in zip(x, z, strict=True)])
    return np.stack([x, y, z], axis=-1)


'''Each lane is 1.5 m wide, so the left and right lanes are 1.5 m either side
of the line. A lane is a distance to the right of the line in metres; right is
the runner's right as it runs the course.'''
LANES = {'1': -1.5, '2': 0.0, '3': 1.5}
#: Metres a second along the trail.
SPEED = 4.0
#: The drawn trail: three lanes and a narrow verge that meets the land.
PROFILE = RoadProfile(lane_width=1.5, lanes=3, shoulder_width=0.3, shoulder_drop=0.02,
                      verge_width=0.4, verge_drop=0.1, crossfall=0.0, texture_length=8.0)


def trail_node(points):
    '''The trail drawn as a road swept along the centreline, a few
    centimetres over the land. It is drawn and not collided with: the fox runs
    on the land, which ``collide = False`` leaves the trail's mesh out of.'''
    lifted = points + (0.0, 0.06, 0.0)
    mesh = road_mesh(lifted, PROFILE)
    node = Shape(geometry=mesh, appearance=mesh.appearance)
    node.collide = False
    return node


class TestContext(LandContext):
    def OnInit(self):
        super().OnInit()
        points = centreline()
        self.sg.children.append(trail_node(points))
        self.physics.add_ground(LAND)
        self.hero = self.physics.add_character(
            model=sample_model_url('Fox'), animations=FOX,
            position=tuple(points[0] + (0.0, 0.2, 0.0)), parent=self.sg)
        '''``run_along`` takes the points, or a ``RoadCourse`` made from them,
        and runs the course at ``speed`` metres a second. The fox's clip map
        shows the run at that speed. At the end of an open course the
        character stops and its ``'arrived'`` handlers are called; this one
        turns the fox round and runs the trail back.'''
        self.points = points
        self.hero.run_along(points, speed=SPEED)
        self.hero.addEventHandler('arrived', self.OnArrived)
        '''The camera follows from behind, and ``swing`` brings it round
        behind the way the fox runs in half a second, so it looks down the
        trail through every bend. ``yaw`` is the way it looks to begin with,
        in radians from -Z toward +X: the trail sets off toward +Z, which a
        new character faces.'''
        self.follow(self.hero, distance=6.0, height=2.0, swing=0.5, yaw=math.pi)
        for key in LANES:
            self.addEventHandler('keypress', name=key, function=self.OnLane)

    def OnLane(self, event):
        '''``hop_to`` moves the runner to a lane over ``over`` seconds, easing
        across, and it keeps running while it hops.'''
        self.hero.hop_to(LANES[event.name], over=0.25)

    def OnArrived(self, hero):
        self.points = self.points[::-1]
        hero.run_along(self.points, speed=SPEED)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
