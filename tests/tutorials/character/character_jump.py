#! /usr/bin/env python
'''=A character jumps, slides and lands=

[character_jump.py-screen-0001.png Screenshot]

The fox of :doc:`character_run` already jumps on the space bar and slides on
``c``, because the follow mode's keys do. This tutorial changes how long the
slide lasts and makes a sound where the fox lands, harder for a longer fall.

Keys:
    space   jump
    c       slide
'''
from omi_audio import synth

from character_run import TestContext as Running

THUD = synth.impact(0.25, decay=18.0, seed=7)


class TestContext(Running):
    def OnInit(self):
        super().OnInit()
        '''``slide_time`` is how long a slide lasts in seconds. The character
        stays low and keeps the speed it had, loses it to friction, and rises
        over the last 0.3 s. ``hero.state`` says which of standing, crouching,
        sliding, airborne, down, swimming and flying the character is in, and
        ``hero.slide(duration, rise)`` starts a slide from code.'''
        self.follow(self.hero, slide_time=1.2)
        '''``'landed'`` is raised in the frame the character comes down onto
        the ground, whether it jumped or walked off a ledge.'''
        self.hero.addEventHandler('landed', function=self.OnLanded)

    def OnLanded(self, landing):
        '''``landing.speed`` is the speed it came down at, in metres a second:
        about 4.9 for a jump from the ground, and more for a fall. 6 m/s is a
        hard landing and the full gain of the sound. A model with a landing
        clip names it in the ``ClipMap`` as ``land=``, and the character plays
        it, longer for a harder landing.'''
        self.audio.play(THUD, at=landing.character.position, gain=min(1.0, landing.speed / 6))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
