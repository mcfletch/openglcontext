#! /usr/bin/env python
'''=Spatial Audio (KHR_audio_emitter)=

[audio_spatial.py-screen-0001.png Screenshot]

Three sounds in a room, and a camera you can walk around them with.
Nothing is loaded from a file: the clips are made in code by
`OpenGLContext.audio.sounds`, so the demo carries no assets and no
licences.  Everything the script does with sound goes through
`self.audio`, the context's sound service.

What you should hear, and what each thing is showing:

 * the *red* sphere orbits you and pans between your ears as it passes.
   That is `equal_power_pan` following the listener's azimuth.
 * the *green* sphere sits well back and fades as you walk towards and
   away from it.  That is the `inverse` distance model.
 * the *blue* cone faces you to begin with and goes quiet as you walk
   round behind it.  That is a `cone` emitter.

Keys:

 * `m` -- muffle everything, as though you had gone underwater.  Again
   to clear it.
 * space -- fire a one-shot impact.  That is a voice that is not looped,
   which is how a weapon or a footstep reaches the pool.
 * `+` / `-` -- the player's volume, which is the same number the F10
   settings screen shows.
 * `v` -- print what the audio system is doing: `audio.describe()`.

**If you hear nothing**, read the line the demo prints at startup: it
names the backend that opened, or says the run is silent and why.  A
level meter is printed once a second while anything is playing, so a
silent run can be told apart from a run that is producing samples nobody
can hear.  Silence is a supported outcome -- with no `miniaudio` and no
sound card the demo still runs -- which is what lets it be part of an
automated test.

    pip install "OpenGLContext[audio]"      # turn sound on
'''
import math

from OpenGLContext.audio import sounds
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import (
    AudioEmitter, AudioSource, Appearance, Cone, Material, Shape, Sphere,
    Transform,
)

#: How far the orbiting emitter is from the origin, in metres.  Close, because
#: the point is to hear it move rather than to hear it fade.
ORBIT_RADIUS = 3.0
#: Seconds for one full orbit.
ORBIT_PERIOD = 6.0
#: Where the distant emitter sits, and the radius inside which it is at full
#: volume.  An `inverse` curve with the default one-metre reference distance is
#: *correct* and nearly inaudible across a room; a sound meant to carry has to
#: say so, and this is what saying so looks like.
DISTANT_POSITION = (0.0, 1.0, -22.0)
DISTANT_REFERENCE = 20.0
#: How sharply it falls beyond that.  Below 1.0 is a sound that carries.
DISTANT_ROLLOFF = 0.5
#: Where the directional emitter sits, and how wide its cone is.
CONE_POSITION = (-4.0, 1.0, -3.0)
CONE_INNER = math.radians(70)
CONE_OUTER = math.radians(150)
#: Seconds between level reports.
METER_INTERVAL = 1.0
#: How loud the whole demo plays.  A demonstration is not a game: it is run at
#: whatever volume the machine happens to be at, so it wants to sit comfortably
#: below full scale rather than compete for it.  This puts the loudest moment --
#: three sources summing as the orbiting one passes the listener -- around
#: -12 dBFS, which is audible without being startling and leaves the mixer's
#: limiter far away.  It is `audio.mix`, the application's level; `+` and `-`
#: move the player's volume over it.
MASTER_GAIN = 0.2


def marker(colour, geometry):
    """Something to look at, so a sound has a visible source."""
    return Shape(
        appearance=Appearance(material=Material(diffuseColor=colour,
                                                emissiveColor=colour)),
        geometry=geometry,
    )


class TestContext(BaseContext):
    """Three emitters, one listener, and a camera you can walk with."""

    initialPosition = (0, 1.6, 6)

    def OnInit(self):
        BaseContext.OnInit(self)
        self.orbit = Transform(children=[
            marker((1.0, 0.2, 0.2), Sphere(radius=0.3)),
            AudioEmitter(
                gain=1.0, refDistance=4.0, rolloffFactor=1.0,
                sources=[AudioSource(url=['orbit'], loop=True)]),
        ])
        distant = Transform(translation=DISTANT_POSITION, children=[
            marker((0.2, 1.0, 0.2), Sphere(radius=1.2)),
            AudioEmitter(
                gain=1.0, distanceModel='inverse',
                refDistance=DISTANT_REFERENCE,
                rolloffFactor=DISTANT_ROLLOFF,
                sources=[AudioSource(url=['distant'], loop=True)]),
        ])
        # A glTF emitter faces its own -Z, as glTF cameras and
        # KHR_lights_punctual do, so this one is turned to face the camera's
        # starting position.  A Cone's own axis is +Y, so the marker is tipped
        # over to show which way that is.
        directional = Transform(
            translation=CONE_POSITION, rotation=(0, 1, 0, math.pi),
            children=[
                Transform(rotation=(1, 0, 0, -math.pi / 2),
                          children=[marker((0.3, 0.4, 1.0),
                                           Cone(bottomRadius=0.6, height=1.4))]),
                AudioEmitter(
                    gain=1.0, shapeType='cone', coneInnerAngle=CONE_INNER,
                    coneOuterAngle=CONE_OUTER, coneOuterGain=0.05,
                    refDistance=6.0,
                    sources=[AudioSource(url=['cone'], loop=True)]),
            ])
        self.sg = Transform(children=[self.orbit, distant, directional])
        for key, handler in (('m', self.OnMuffle), (' ', self.OnPing),
                             ('v', self.OnReport), ('+', self.OnLouder),
                             ('=', self.OnLouder), ('-', self.OnQuieter)):
            self.addEventHandler('keypress', name=key, function=handler)
        self.registerClips()
        self.orbitTimer = Timer(duration=ORBIT_PERIOD, repeating=1)
        self.orbitTimer.addEventHandler('fraction', self.OnOrbit)
        self.orbitTimer.register(self)
        self.orbitTimer.start()
        self.meterTimer = Timer(duration=METER_INTERVAL, repeating=1)
        self.meterTimer.addEventHandler('cycle', self.OnMeter)
        self.meterTimer.register(self)
        self.meterTimer.start()
        print(__doc__, flush=True)
        self.OnReport(None)

    def registerClips(self):
        """Give each made clip the name its `AudioSource` url asks for.

        `audio.add` makes a clip playable by name, by `audio.play` and by a
        scene's sources alike, so a made sound is played by the same path as
        a decoded file.  The frequencies sit where a laptop speaker reproduces
        sound: a 60 Hz drone is a silent demo on most hardware.  The
        amplitudes leave room for three of them to sum without reaching the
        mixer's limiter, which would be heard as distortion rather than as
        loudness.
        """
        audio = self.audio
        audio.mix = MASTER_GAIN
        # Harmonics, not bare sines: the muffle is a low-pass, and a sine has
        # nothing above its fundamental for a low-pass to take away, so it
        # only gets quieter.  Partials also make a sound easy to place by ear.
        audio.add('orbit', sounds.tone(660.0, 2.0, amplitude=0.45, harmonics=8))
        audio.add('distant', sounds.tone(330.0, 2.0, amplitude=0.6, harmonics=10))
        audio.add('cone', sounds.chirp(700.0, 1100.0, 1.5, amplitude=0.45))
        audio.add('ping', sounds.impact(0.4, amplitude=0.7, seed=1))

    def OnReport(self, event):
        """Say what the audio system decided, which is the first thing to check."""
        print(self.audio.describe(), flush=True)
        if self.audio.silent:
            print('  Nothing will be heard.  Turn sound on with:  '
                  'pip install "OpenGLContext[audio]"', flush=True)

    def OnMeter(self, event):
        """Print the level, so a silent run can be told from an inaudible one.

        `audio.level` is the loudest voice as it reaches the output, after
        distance, direction, the mix and the volume.
        """
        peak = self.audio.level
        if peak:
            print('level %-40s %6.1f dBFS' % (
                '#' * int(round(peak * 40)), 20 * math.log10(peak)), flush=True)

    def OnMuffle(self, event):
        """Toggle the underwater low-pass on the whole mix."""
        self.audio.muffle = 0.0 if self.audio.muffle else 1.0
        print('muffle %s' % ('on' if self.audio.muffle else 'off',), flush=True)

    def OnPing(self, event):
        """Fire a one-shot at the listener, to hear a voice that is not looped."""
        self.audio.play('ping', priority=1.0)

    def _setVolume(self, delta):
        """Move the player's volume.

        `audio.volume` is the setting the F10 settings screen shows, saved with
        the rest.  `audio.mix`, set once in `registerClips`, is the
        application's level under it.
        """
        self.audio.volume = min(1.0, max(0.0, self.audio.volume + delta))
        print('volume %.2f' % (self.audio.volume,), flush=True)

    def OnLouder(self, event):
        self._setVolume(0.1)

    def OnQuieter(self, event):
        self._setVolume(-0.1)

    def OnOrbit(self, event):
        """Move the orbiting emitter around the origin.

        Nothing here touches the audio: the emitter is a node under a
        Transform, and moving the Transform moves the sound.  The render pass
        re-aims it as part of drawing the frame.
        """
        angle = 2.0 * math.pi * event.fraction()
        self.orbit.translation = (ORBIT_RADIUS * math.sin(angle), 1.2,
                                  ORBIT_RADIUS * math.cos(angle))
        self.triggerRedraw(1)


if __name__ == "__main__":
    TestContext.ContextMainLoop(definition={
        'renderer':'vrml97',
    })
