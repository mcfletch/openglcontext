#! /usr/bin/env python
'''=Physics: a sound on every hit=

[physics_stairs_sound.py-screen-0001.png Screenshot]

``self.audio`` is the context's sound service, made on the first call like
``self.physics``. ``audio.play`` starts a sound and returns at once, from any
thread, so a handler may call it wherever it runs. The ball of
:doc:`physics_stairs_colour` thuds where it strikes, louder the harder it hits.
'''
from omi_audio import synth

from physics_stairs_colour import TestContext as Colouring

'''A sound is a file, a URL, a name given to ``audio.load`` or a decoded clip.
This one is made on the spot so that the script needs no file: a 0.25 s burst of
noise that dies away quickly. A game plays ``'thud.ogg'``.'''
THUD = synth.impact(0.25, decay=18.0, seed=7)


class TestContext(Colouring):
    def OnBallHit(self, hit):
        '''The handler of the colour tutorial, with one line added. ``at`` is
        a world point, so the sound comes from where the ball struck and pans
        with the camera. ``gain`` is 1.0 for the sound as recorded, here
        reached at 6 m/s. ``hit.speed`` is the closing speed in metres a
        second.'''
        super().OnBallHit(hit)
        self.audio.play(THUD, at=hit.point, gain=min(1.0, hit.speed / 6))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
