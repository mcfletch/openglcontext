#! /usr/bin/env python
'''=A character runs across a landscape=

[character_run.py-screen-0001.png Screenshot]

A character needs four things from an engine: ground to stand on, a body that
the ground stops, clips that play for what the body is doing, and a camera that
follows it. After the scene, each is one line.

Keys:
    w a s d   run; the camera turns with q and e
    shift     run faster
    space     jump
'''
import numpy as np

from OpenGLContext.character.locomotion import ClipMap
from OpenGLContext.context import Context
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import Appearance, Background, DirectionalLight, sceneGraph
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.basenodes import Shape
from OpenGLContext.scenegraph.terrain.heightfield import HeightField

'''The land is a function of ``(x, z)``: low hills 2 m high and 30 m apart. A
``HeightField`` samples it over a 160 m square into a grid of 1.25 m cells. The
same grid is what the ground collides with and what is drawn, so a foot meets
the surface the player sees.'''


def hills(x, z):
    return 1.2 * np.sin(x / 9.0) * np.cos(z / 11.0) + 0.5 * np.sin((x + z) / 4.0)


LAND = HeightField.from_function(hills, 129, 160.0)


def land_node(land):
    '''The land as a mesh wearing a mossy sandstone, one texture repeat to 3 m.
    A shape in the scene is scenery, and scenery is a static body. The ground
    is collided through its height field below, so the drawn mesh says
    ``collide = False`` and is not made a second body.'''
    vertices, indices = land.mesh()
    look = Appearance(material=surfaces.pbr_material(
        surfaces.sandstone(256, colour=(0.30, 0.45, 0.20)), roughness=0.95))
    node = Shape(
        geometry=PBRMesh(positions=vertices[:, :3], normals=vertices[:, 3:],
                         texcoords=vertices[:, [0, 2]] / 3.0, indices=indices,
                         appearance=look),
        appearance=look)
    node.collide = False
    return node


class LandContext(Context):
    '''The scene: a sky, a light and the land. It mentions no physics.'''

    def OnInit(self):
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.5, 0.65, 0.85)]),
            DirectionalLight(direction=(-0.4, -0.8, -0.3), intensity=3.0),
            land_node(LAND),
        ])


#: The fox's clips by role, each with the speed in metres a second it was
#: authored for where it loops.
FOX = ClipMap(idle='Survey', walk=('Walk', 1.5), run=('Run', 4.0))


class TestContext(LandContext):
    def OnInit(self):
        super().OnInit()
        '''``add_ground`` makes the land a static body. Any object with a
        ``sample(x, z)`` is ground, so land computed from a function with no
        edge works as well as a grid.'''
        self.physics.add_ground(LAND)
        '''``add_character`` makes a walker: a capsule the land and the
        scenery stop, stepped every frame by the engine. ``model`` is a path, a
        URL or a loaded scene; it is scaled to the capsule's height and
        stood on its base. ``animations`` names which of the model's clips is
        idle, which is a walk and which is a run. The character plays them for
        what the capsule is doing: blended by speed, each at the rate that
        keeps its feet on the ground. ``parent`` is where the model is put in
        the scene.'''
        self.hero = self.physics.add_character(
            model=sample_model_url('Fox'), animations=FOX,
            position=(0, 0.2, 0), parent=self.sg)
        '''``follow`` shows the character from behind and gives it the movement
        keys of the engine's follow mode: they move it relative to the camera,
        which turns round it with the turn keys, follows it and keeps out of
        the land and anything standing on it.'''
        self.follow(self.hero)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
