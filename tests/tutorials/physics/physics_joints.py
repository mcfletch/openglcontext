#! /usr/bin/env python
'''=Physics: joints (OMI_physics_joint)=

[physics_joints.py-screen-0001.png Screenshot]

A pendulum and a hanging chain, each built from ``DistanceConstraint`` links to a
fixed anchor, plus a motorised spinner driven by an ``AngularMotor``.  Joints
are solved as velocity constraints alongside contacts.

The physics service has no call for joints.  ``physics.world`` is the live
``PhysicsWorld`` of a service that steps in the frame, and a joint is added to
it by the row its body has, which ``physics.slot_of`` answers.  Declaring
``mode='inline'`` is what makes the world reachable from the script.

Keys:
    r   put everything back where it started
'''
import numpy as np

from omi_physics.joints import AngularMotor, DistanceConstraint

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
)


class TestContext(BaseContext):
    initialPosition = (0, 3, 16)
    '''The world is stepped in the frame, so the script may use it directly
    between frames.'''
    contextDefinition = ContextDefinition(physics=PhysicsDefinition(mode='inline'))

    def OnInit(self):
        self.homes = []
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
        ])
        self.build()
        print(__doc__)
        self.addEventHandler('keypress', name='r', function=self.on_reset)

    def add(self, geometry, material, at):
        '''A drawn body of one kilogram, remembered with where it started.'''
        node = surfaces.shape(geometry, material)
        self.sg.children.append(node)
        body = self.physics.add_dynamic(node, translation=at, mass=1.0)
        self.homes.append((body, at))
        return body

    def build(self):
        world = self.physics.world
        steel = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.STEEL))
        copper = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.COPPER))
        gold = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.GOLD))

        '''A pendulum: a bob on a 2 m arm from a fixed pivot.  Body ``-1`` is
        the world itself, and each anchor is in the frame of its body.'''
        pivot = (-5.0, 6.0, 0.0)
        bob = self.add(surfaces.sphere(0.5), copper, (-3.0, 6.0, 0.0))
        world.add_joint_constraint(DistanceConstraint(
            -1, self.physics.slot_of(bob), anchor_a=pivot, anchor_b=(0, 0, 0), length=2.0))

        '''A chain: a column of links, each held a fixed distance below the
        previous.'''
        previous, previous_at = -1, np.array([2.0, 7.0, 0.0])
        for _ in range(5):
            at = previous_at - (0, 1.0, 0)
            link = self.add(surfaces.block((0.6, 0.6, 0.6)), steel, tuple(at))
            anchor = (0, 0, 0) if previous >= 0 else tuple(previous_at)
            row = self.physics.slot_of(link)
            world.add_joint_constraint(DistanceConstraint(
                previous, row, anchor_a=anchor, anchor_b=(0, 0, 0), length=1.0))
            previous, previous_at = row, at

        '''A spinner: a motor that turns a bar about the Y axis at 4 radians a
        second, with up to 30 N*m of torque.'''
        spinner = self.add(surfaces.block((3, 0.3, 0.3)), gold, (6, 4, 0))
        world.add_joint_constraint(AngularMotor(
            self.physics.slot_of(spinner), axis=(0, 1, 0), target=4.0, max_force=30.0))
        self.physics.show_proxies(True)

    def on_reset(self, event):
        for body, at in self.homes:
            body.set_transform(translation=at, rotation=(0, 0, 1, 0))
            body.set_velocity((0, 0, 0))
            body.set_angular_velocity((0, 0, 0))
            body.wake()


if __name__ == '__main__':
    TestContext.ContextMainLoop()
