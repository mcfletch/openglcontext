#! /usr/bin/env python
'''=Physics: joints=

[physics_joints.py-screen-0001.png Screenshot]

A joint holds a body to another body, or to the world, so that it can only move
the way the joint lets it. The service makes four kinds, each with one call that
returns a ``Joint``:

* ``add_hinge`` turns about an axis through a point, like a door or a wheel.
* ``add_ball`` turns any way about a point, like a shoulder or a chain link.
* ``add_slider`` moves along an axis and does not turn, like a drawer.
* ``add_distance`` keeps two points a fixed distance apart, like a rod.

This scene has a pendulum on a hinge, a chain of ball joints, a spinner driven by
a hinge's motor and a block on a slider.

Keys:
    m   run the spinner the other way
    r   put everything back where it started
'''
from OpenGLContext.context import Context
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import Background, DirectionalLight, sceneGraph


class TestContext(Context):
    initialPosition = (0, 3, 16)

    def OnInit(self):
        self.homes = []
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
        ])
        steel = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.STEEL))
        copper = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.COPPER))
        gold = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.GOLD))

        '''A pendulum: a copper bob on an arm, hinged to the world at a pivot.
        Anchors and axes are world coordinates where the bodies stand when the
        joint is made, and each body carries them from then on. ``to`` is the
        other body; left out, it is the world.'''
        arm = self.add(surfaces.block((2.0, 0.15, 0.15)), copper, (-4.0, 6.0, 0.0))
        self.physics.add_hinge(arm, anchor=(-5.0, 6.0, 0.0), axis=(0, 0, 1))

        '''A chain: five steel links, the first held to the world and each of
        the others to the one above it, at the point where they meet.'''
        above = None
        for number in range(5):
            top = 7.0 - number
            link = self.add(surfaces.block((0.3, 0.8, 0.3)), steel, (1.0, top - 0.5, 0.0))
            self.physics.add_ball(link, above, anchor=(1.0, top, 0.0))
            above = link
        '''A push on the last link sets the chain swinging.'''
        above.apply_impulse((3.0, 0.0, 1.0))

        '''A spinner: a gold bar on a hinge about the vertical, with a motor.
        ``motor`` is the speed in radians a second and the most torque, in
        newton-metres, the motor gives to reach it. ``drive`` changes both.'''
        spinner = self.add(surfaces.block((3, 0.3, 0.3)), gold, (5.5, 4.0, 0.0))
        self.spinner = self.physics.add_hinge(
            spinner, anchor=(5.5, 4.0, 0.0), axis=(0, 1, 0), motor=(4.0, 30.0))

        '''A drawer: a block that slides along X between stops 1.5 m either
        side of where it starts, pushed by a slider's motor at 1 m/s with at
        most 40 N.'''
        drawer = self.add(surfaces.block((0.8, 0.8, 0.8)), steel, (5.5, 1.0, 0.0))
        self.physics.add_slider(drawer, axis=(1, 0, 0), limits=(-1.5, 1.5), motor=(1.0, 40.0))
        self.physics.show_proxies(True)
        print(__doc__)
        self.addEventHandler('keypress', name='m', function=self.on_reverse)
        self.addEventHandler('keypress', name='r', function=self.on_reset)

    def add(self, geometry, material, at):
        '''A drawn body of one kilogram, remembered with where it started.'''
        node = surfaces.shape(geometry, material)
        self.sg.children.append(node)
        body = self.physics.add_dynamic(node, translation=at, mass=1.0)
        self.homes.append((body, at))
        return body

    def on_reverse(self, event):
        '''``motor`` is the speed and torque the joint was last given.'''
        speed, torque = self.spinner.motor
        self.spinner.drive(-speed, torque)

    def on_reset(self, event):
        for body, at in self.homes:
            body.set_transform(translation=at, rotation=(0, 0, 1, 0))
            body.set_velocity((0, 0, 0))
            body.set_angular_velocity((0, 0, 0))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
