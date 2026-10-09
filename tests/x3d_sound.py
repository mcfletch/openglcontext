#! /usr/bin/env python
'''=X3D: sound sources, a processing graph and where they are heard from=

[x3d_sound.py-screen-0001.png Screenshot]

``oglc-x3d-sound`` opens ``x3d_sound.x3d``, an X3D 4 document using the
Sound component, played through omi_audio's processing graph:

* the bronze bell is X3D's (and VRML97's) ``Sound`` playing an
  ``AudioClip``: full within two metres of it and fading to nothing at
  twenty-five, panned by its bearing from the camera;
* the copper pipe circles the centre on a ``SpatialSound`` with Doppler on,
  so its note rises as it comes toward the camera and falls as it goes away.
  Its tone is an ``OscillatorSource`` playing a sawtooth ``PeriodicWave``,
  through a ``WaveShaper`` and a ``BiquadFilter``;
* the steel drum is heard everywhere through an ``AudioDestination``: a
  ``BufferAudioSource`` reading a clip, its echo a ``Delay``, its room a
  ``Convolver``, the mix held by a ``DynamicsCompressor`` and watched by an
  ``Analyser`` whose levels raise the bars;
* two pings, one to each ear, go through a ``ChannelSplitter`` and come back
  through two ``ChannelSelector`` nodes into a ``ChannelMerger``;
* a ``MicrophoneSource`` is heard only where the application allows audio
  capture, and a ``ListenerPointSource`` moves where everything is heard from.
'''
import os
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_sound import SoundScene
from OpenGLContext.events import systemtime
from OpenGLContext.events.renderqueue import DEFER
from OpenGLContext.loaders import background


class TestContext(BaseContext):

    def OnInit(self):
        '''The scene copies the document beside the clips and maps it names,
        reads it with ``Loader.load``, and sets the two buffers a document
        does not hold compactly: the pings and the room.'''
        self.sound = SoundScene(tempfile.mkdtemp(prefix='x3d-sound-'))
        background.wait_for_idle(20.0)
        self.sg = self.sound.scene
        '''Each frame the meter's bars are raised to the Analyser's levels.'''
        self.renderQueue.call(self.meter)
        for key in SoundScene.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(SoundScene.help())

    def meter(self):
        self.sound.showLevels()
        return DEFER

    def OnKey(self, event):
        said = self.sound.press(event.name, systemtime.systemTime())
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
