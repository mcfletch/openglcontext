#! /usr/bin/env python
'''=Physics: objects falling into a room=

[physics_room_drop.py-screen-0001.png Screenshot]

Boxes and spheres fall into a walled room and settle: the world integrates
their motion, collides them, solves the contacts so they stack, and puts them to
sleep once they are still.  The room is only drawn: the floor and the walls are
shapes in the scene, so each is a static body without a call.  The green
wireframes are the collision proxies, drawn by ``physics.show_proxies``.

Keys:
    space  drop another body
    r      reset the scene
    d      draw the collision proxies, or stop drawing them
'''
import numpy as np

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
)

#: The room's half width, in metres, the thickness of its walls and their height.
SIZE = 6.0
WALL = 0.4
HEIGHT = 4.0


def make_room():
    '''A floor and four walls, as shapes of the scene: the world makes a static
    body of each.'''
    floor = surfaces.pbr_material(surfaces.checkered_marble(512, tiles=6))
    plaster = surfaces.pbr_material(surfaces.plaster(256))
    parts = [surfaces.shape(surfaces.block((2 * SIZE, 1, 2 * SIZE), repeat=2 * SIZE), floor,
                            translation=(0, -0.5, 0))]
    for side in (-1, 1):
        parts.append(surfaces.shape(
            surfaces.block((WALL, HEIGHT, 2 * SIZE)), plaster,
            translation=(side * SIZE, HEIGHT / 2, 0)))
        parts.append(surfaces.shape(
            surfaces.block((2 * SIZE, HEIGHT, WALL)), plaster,
            translation=(0, HEIGHT / 2, side * SIZE)))
    return parts


class TestContext(BaseContext):
    initialPosition = (0, 7, 18)

    def OnInit(self):
        self.rng = np.random.RandomState(1234)
        self.wood = surfaces.pbr_material(surfaces.wood(256))
        self.metal = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.COPPER))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
            *make_room(),
        ])
        self.bodies = []
        self.proxies = True
        self.physics.show_proxies(True)
        for k in range(8):
            self.drop_one(k)
        print(__doc__)
        self.addEventHandler('keypress', name='r', function=self.on_reset)
        self.addEventHandler('keypress', name=' ', function=self.on_add)
        self.addEventHandler('keypress', name='d', function=self.on_debug)

    def drop_one(self, k):
        '''A body is a node and a call.  The node is added to the scene, and
        ``add_dynamic`` makes the world move it: a box of wood or a sphere of
        copper, which the world fits to the mesh.  ``material`` names the
        grip and bounce of ``wood`` or ``rubber``, two of the four presets.'''
        x, z = self.rng.uniform(-2.5, 2.5, 2)
        at = (x, 6.0 + 1.3 * k, z)
        if k % 2:
            node = surfaces.shape(surfaces.block((1, 1, 1)), self.wood)
            material = 'wood'
        else:
            node = surfaces.shape(surfaces.sphere(0.6), self.metal)
            material = 'rubber'
        self.sg.children.append(node)
        self.bodies.append(self.physics.add_dynamic(node, translation=at, material=material))

    def clear(self):
        for body in self.bodies:
            body.remove()
            self.sg.children.remove(body.node)
        self.bodies = []

    def on_reset(self, event):
        self.clear()
        for k in range(8):
            self.drop_one(k)

    def on_add(self, event):
        self.drop_one(self.rng.randint(0, 100))

    def on_debug(self, event):
        self.proxies = not self.proxies
        self.physics.show_proxies(self.proxies)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
