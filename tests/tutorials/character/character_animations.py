#! /usr/bin/env python
'''=A different model and a different animation set=

[character_animations.py-screen-0001.png Screenshot]

``animations=`` says which of a model's clips plays for what the character is
doing. :doc:`character_run` names the fox's three clips by hand. A model from
somewhere else carries other clips under other names, and this tutorial maps
two of them: the fox again, with its roles guessed from its clip names, and
`CesiumMan` from the Khronos sample catalogue (CC-BY 4.0, Cesium), whose one
clip is a walk. Both walk circles on the land of :doc:`character_run`.
'''
import math

from character_run import LAND, LandContext
from OpenGLContext.character.locomotion import ClipMap
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.physics import CharacterCapabilities
from OpenGLContext.scenegraph.roadcourse import RoadCourse

'''A role is a job a clip does: ``idle``, ``walk``, ``run``, ``jump_up``,
``land`` and the others of ``locomotion.ROLES``. A ``ClipMap`` says which clip
does each, and for a looping one the speed in metres a second it was authored
for.

CesiumMan's file has one animation and no name for it, so the model calls it
``animation0``. It is a walk, and naming it ``walk`` is the whole map. With no
speed given, the character measures it: :func:`measure_stride` watches the
feet of the model's skeleton as the clip plays, and the speed is how fast they
travel backwards under the hips. With no idle the man stands in his rest pose,
and with no run the walk plays faster for a faster pace, up to the map's
``rate_range``.'''
MAN = ClipMap(walk='animation0')

#: The fox's capsule: a metre high, so the fox is scaled to a fox's size.
FOX_BODY = CharacterCapabilities(standHeight=1.0, crouchHeight=0.7, radius=0.3)
#: Metres a second each walker goes round its circle.
FOX_SPEED = 2.0
MAN_SPEED = 1.3


def circle(radius, clockwise=False, points=48):
    '''A closed course round the origin: a ring of points whose last joins its first.'''
    turn = -1.0 if clockwise else 1.0
    return RoadCourse([(radius * math.cos(turn * 2 * math.pi * step / points), 0.0,
                        radius * math.sin(turn * 2 * math.pi * step / points))
                       for step in range(points)], closed=True)


class TestContext(LandContext):
    initialPosition = (5.5, 3, 8)
    initialOrientation = (-1, 0, 0, 0.28)

    def OnInit(self):
        super().OnInit()
        self.physics.add_ground(LAND)
        '''``ClipMap.guess`` splits each of the model's clip names into words
        and gives each role the clip whose name says it, so ``Walk_Loop``,
        ``walk`` and ``WalkFwd`` are all walks. For the fox it finds the walk
        and the run. ``unmatched`` lists the roles it found no clip for, and
        ``leftover`` the clips no role took: the fox's ``Survey``.'''
        fox = CharacterModel.load(sample_model_url('Fox'))
        guessed = ClipMap.guess(fox)
        print('guessed %r; no clip for %s; not used: %s' % (
            guessed, ', '.join(guessed.unmatched), ', '.join(guessed.leftover)))
        '''Filling a gap is naming the role in the same call: a role given by
        hand takes that clip in place of a guess. The fox's clips plant no
        humanoid feet to measure, so the walk and the run take the default
        speeds of 1.4 and 3.8 metres a second; ``walk=('Walk', 1.3)``, the
        speed the walk carries a fox a metre high, would give one.'''
        self.fox_clips = ClipMap.guess(fox, idle='Survey')
        self.fox = self.physics.add_character(
            capabilities=FOX_BODY, model=fox, animations=self.fox_clips, position=(4, 0.5, 0), parent=self.sg)
        self.man = self.physics.add_character(
            model=sample_model_url('CesiumMan'), animations=MAN,
            position=(7, 0.5, 0), parent=self.sg)
        '''Each walks a circle for as long as the program runs. ``run_along``
        is the subject of :doc:`character_trail`.'''
        self.fox.run_along(circle(4.0), speed=FOX_SPEED)
        self.man.run_along(circle(7.0, clockwise=True), speed=MAN_SPEED, mode='walk')
        print('CesiumMan walks at %.2f m/s at rate 1' % (self.man.locomotion.speeds['walk'],))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
