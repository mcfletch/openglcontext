#! /usr/bin/env python
'''=A camera that stays out of walls=

[character_camera.py-screen-0001.png Screenshot]

A camera behind a character inside a room meets the walls: at every corner,
the place behind the character is on the far side of one. The follow camera
of :doc:`character_run` sweeps a sphere along its arm, from the point it looks
at out to the arm's full length, and stands where the sphere first meets
something. Here the fox walks a loop round a brick room's pillar, and the
camera comes round behind it at each corner, closing in on the wall and
easing back out once the way is clear.
'''
from OpenGLContext.character.locomotion import ClipMap
from OpenGLContext.context import Context
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.physics import CharacterCapabilities
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import Background, DirectionalLight, PointLight, sceneGraph
from OpenGLContext.scenegraph.roadcourse import RoadCourse

#: The room: walls at this many metres either side of the centre, this high
#: and this thick, and a square pillar in the middle this wide.
HALF = 7.0
HEIGHT = 3.0
THICK = 0.4
PILLAR = 3.0
#: The loop the fox walks: a square this many metres either side of the
#: centre, between the pillar and the walls, anticlockwise from above.
LOOP = 4.5
LAP = RoadCourse([(LOOP, 0, LOOP), (-LOOP, 0, LOOP), (-LOOP, 0, -LOOP), (LOOP, 0, -LOOP)],
                 closed=True)
#: The fox's capsule, a metre high, and the speeds its walk and run carry a fox
#: of that height.
BODY = CharacterCapabilities(standHeight=1.0, crouchHeight=0.7, radius=0.3)
FOX = ClipMap(idle='Survey', walk=('Walk', 1.3), run=('Run', 2.2))
#: How far behind the fox the camera stands when nothing is in the way, in metres.
DISTANCE = 5.0


def room():
    '''A floor, four brick walls and a pillar: shapes in the scene, so static
    bodies the fox walks on and the camera's sweep meets.'''
    bricks = surfaces.pbr_material(surfaces.brick(256), roughness=0.85)
    stone = surfaces.pbr_material(surfaces.sandstone(256), roughness=0.9)
    span = 2 * HALF + THICK
    parts = [surfaces.shape(surfaces.block((span + 6, 0.2, span + 6), repeat=3.0), stone,
                            translation=(0, -0.1, 0))]
    for x, z, size in ((HALF, 0, (THICK, HEIGHT, span)), (-HALF, 0, (THICK, HEIGHT, span)),
                       (0, HALF, (span, HEIGHT, THICK)), (0, -HALF, (span, HEIGHT, THICK))):
        parts.append(surfaces.shape(surfaces.block(size, repeat=2.0), bricks,
                                    translation=(x, HEIGHT / 2, z)))
    parts.append(surfaces.shape(surfaces.block((PILLAR, HEIGHT, PILLAR), repeat=2.0), bricks,
                                translation=(0, HEIGHT / 2, 0)))
    return parts


class TestContext(Context):
    def OnInit(self):
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.5, 0.62, 0.8)]),
            DirectionalLight(direction=(-0.3, -0.9, -0.4), intensity=2.5),
            PointLight(location=(0, HEIGHT - 0.3, 0), intensity=0.6, radius=20.0),
            *room(),
        ])
        self.hero = self.physics.add_character(
            capabilities=BODY, model=sample_model_url('Fox'), animations=FOX,
            position=(LOOP, 0.05, LOOP), parent=self.sg)
        self.hero.run_along(LAP, speed=1.8, mode='walk')
        '''``follow`` stands the camera ``distance`` metres behind the fox and
        ``height`` metres up, and ``swing`` brings it round behind the way the
        fox walks in about that many seconds. The arm is kept out of the
        walls by a sphere of ``avoid_radius`` metres swept along it through the
        physics world; it is never shorter than ``min_arm`` metres, and once
        the way is clear it eases back out at ``arm_ease`` per second. The
        sweep goes through the fox's own body.'''
        self.follower = self.follow(
            self.hero, distance=DISTANCE, height=1.2, swing=0.8,
            avoid_radius=0.3, min_arm=0.8, arm_ease=3.0)
        '''``constrain`` adds a rule of the game's own, applied before the
        sweep: ``rule(eye, look)`` returns the eye and the point to look at.
        This one keeps the eye under the tops of the walls, so the camera
        never looks down into the room from over a wall.'''
        self.follower.platform.camera.constrain(self.under_the_roofline)

    def under_the_roofline(self, eye, look):
        eye = eye.copy()
        eye[1] = min(eye[1], HEIGHT - 0.4)
        return eye, look


if __name__ == '__main__':
    TestContext.ContextMainLoop()
