#! /usr/bin/env python
'''=Session telemetry (record a session, read it back, run it again)=

[telemetry_demo.py-screen-0001.png Screenshot]

Four bodies circle a lamp, each on its own ring at its own period, and
each one passes a pale gate post once a lap.  Every pass is a mark in the
session journal -- `context.telemetry.mark('lap', body='amber', lap=3)` --
so the file holds what the *application* did as well as what the engine
measured.

The demo records itself.  With no `OPENGLCONTEXT_TELEMETRY` in the
environment it calls `startTelemetry()`, which writes a dated file under
`~/.config/OpenGLContext/telemetry/`; with one, it records to the file
that names.  The path is printed as the demo starts, and on exit the demo
closes the journal, reads it back and prints what
`python -m OpenGLContext.telemetry <file>` prints for it:

    449 frames in 6.1s, 74.0 fps
      median 12.2ms, worst 85.6ms, 0 stalls
      where the time went: render 5940ms, idle 47ms, draw 46ms, cascade 5ms, poll 4ms, wait 1ms, repeats 1ms

    14 mark(s):
      lap 13, scene-ready 1
       0:00.026  frame 0  scene-ready bodies=4
       0:00.933  frame 61  lap body=amber lap=1
       0:01.439  frame 98  lap body=jade lap=1
       0:01.831  frame 130  lap body=amber lap=2
       0:02.233  frame 162  lap body=azure lap=1
      ... and 4 more
       0:04.236  frame 303  lap body=jade lap=3
       0:04.428  frame 319  lap body=azure lap=2
       0:04.536  frame 328  lap body=amber lap=5
       0:05.431  frame 401  lap body=amber lap=6
       0:05.630  frame 418  lap body=jade lap=4

Point a second run at that file and the session runs again from it:

    OPENGLCONTEXT_TELEMETRY_REPLAY=/tmp/orrery.jsonl python tests/telemetry_demo.py

The bodies take their positions from the engine's clock, which a replay
drives from the recorded frame times, so every lap falls on the frame it
fell on the first time and the marks answer one another one for one.  The
verdict is the last thing the replay prints:

    replayed /tmp/orrery.jsonl
      14 marks, all as recorded

Keys:

 * *space* -- flare the lamp, and mark `flare`.
 * *p* -- pause and resume the orbits, and mark `paused`.
 * *m* -- mark `checkpoint` with the laps run so far, for a line to look
   for in the journal afterwards.

The usual keys walk around, and Escape quits.
'''
import os
import sys

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

import math

from OpenGLContext import testingcontext
from OpenGLContext.events import systemtime
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, Cylinder, DirectionalLight, Material, Shape, Sphere,
    Transform, sceneGraph,
)

BaseContext = testingcontext.getInteractive('glfw')

#: How long the lamp stays flared after the space bar, in seconds.
FLARE_SECONDS = 0.5

#: How much bigger the lamp is while it is flared.
FLARE_SCALE = 1.7


class Orbit:
    """One body's circular path, and the laps it has finished.

    Plain arithmetic on a time in seconds: nothing here touches GL or the
    window, so the laps a session marks are decided by the clock alone --
    which is what makes a replay mark the same laps on the same frames.
    """

    def __init__(self, name, radius, period, phase, size, colour):
        self.name = name
        self.radius = radius
        self.period = period
        self.phase = phase
        self.size = size
        self.colour = colour
        #: Laps marked so far, so a crossing is marked once.
        self.laps = 0

    def at(self, turns):
        """A point on the path, ``turns`` of a lap around from the gate."""
        angle = 2.0 * math.pi * (turns + self.phase)
        return (self.radius * math.cos(angle), 0.0,
                -self.radius * math.sin(angle))

    def position(self, seconds):
        """Where the body is at ``seconds``."""
        return self.at(seconds / self.period)

    def gate(self):
        """Where the lap is counted, which is where the body starts."""
        return self.at(0.0)

    def completed(self, seconds):
        """Laps finished by ``seconds``: each one ends at the gate."""
        return int(seconds // self.period)


#: The bodies, innermost first, as Orbit takes them: name, orbit radius,
#: seconds a lap takes, where on the ring the lap is counted, the body's
#: own radius, and its colour.  No period divides another, so the laps fall
#: at different moments and a run of the demo makes a legible sequence of
#: marks rather than four of them at once.
BODIES = [
    ('amber', 2.6, 0.9, 0.00, 0.30, (0.95, 0.65, 0.20)),
    ('jade', 4.0, 1.4, 0.31, 0.38, (0.30, 0.75, 0.45)),
    ('azure', 5.4, 2.2, 0.58, 0.34, (0.30, 0.50, 0.90)),
    ('rose', 6.8, 3.3, 0.83, 0.42, (0.85, 0.35, 0.50)),
]

#: Dots drawn around each ring, so a still picture shows the path a body is
#: on.  Every dot is the same Sphere node under the same Appearance, which
#: is one instanced draw for all of them however many rings there are.
RING_DOTS = 64


class TestContext(BaseContext):
    """An orrery that records itself, and says what it recorded."""

    initialPosition = (0, 8.2, 10.8)
    initialOrientation = (1, 0, 0, -0.66)

    def OnInit(self):
        BaseContext.OnInit(self)
        print(__doc__)
        #: The paths, and the lap counts that go into the marks.
        self.bodies = [Orbit(*body) for body in BODIES]
        self.buildScene()
        #: World time the orbits are measured from, and the seconds spent
        #: paused, which motion time leaves out.
        self._started = systemtime.systemTime()
        self._paused_at = None
        self._paused_for = 0.0
        self._flare_until = None
        self.addEventHandler('keypress', name=' ', function=self.OnFlare)
        self.addEventHandler('keypress', name='p', function=self.OnPause)
        self.addEventHandler('keypress', name='m', function=self.OnCheckpoint)
        self.startRecording()
        self.mark('scene-ready', bodies=len(self.bodies))

    # -- the scene --------------------------------------------------------
    def buildScene(self):
        """A lamp, a body per orbit, and a gate post where each lap ends."""
        #: One geometry and one appearance for every ring dot, which is what
        #: lets the render pass draw all of them in a single instanced call.
        self.dot = Sphere(radius=0.05)
        self.dotSkin = Appearance(material=Material(
            diffuseColor=(0.30, 0.32, 0.38),
            emissiveColor=(0.10, 0.11, 0.14)))
        self.lamp = Transform(children=[Shape(
            geometry=Sphere(radius=0.85),
            appearance=Appearance(material=Material(
                diffuseColor=(0.95, 0.85, 0.55),
                emissiveColor=(0.55, 0.45, 0.15))))])
        children = [
            DirectionalLight(direction=(-0.3, -0.7, -0.6), intensity=1.0),
            DirectionalLight(direction=(0.6, -0.2, 0.5), intensity=0.4,
                             color=(0.55, 0.65, 1.0)),
            self.lamp,
        ]
        self.movers = []
        for body in self.bodies:
            mover = Transform(children=[Shape(
                geometry=Sphere(radius=body.size),
                appearance=Appearance(material=Material(
                    diffuseColor=body.colour, specularColor=(1, 1, 1),
                    shininess=0.5)))])
            self.movers.append(mover)
            children.append(mover)
            children.extend(self.ring(body))
            # The gate the lap is counted at, standing where the body
            # starts, so the marks in the journal have something on screen
            # to point at.
            children.append(Transform(
                translation=body.gate(),
                children=[Shape(
                    geometry=Cylinder(radius=0.05, height=1.2),
                    appearance=Appearance(material=Material(
                        diffuseColor=(0.75, 0.75, 0.8),
                        emissiveColor=(0.3, 0.3, 0.35))))]))
        # A dark plinth, so the orbit plane reads as a plane.
        children.append(Transform(translation=(0.0, -0.75, 0.0), children=[
            Shape(geometry=Box(size=(17.0, 0.3, 17.0)),
                  appearance=Appearance(material=Material(
                      diffuseColor=(0.12, 0.13, 0.17))))]))
        self.sg = sceneGraph(children=children)

    def ring(self, body):
        """One orbit as a ring of dots, so the path is visible standing still."""
        return [Transform(translation=body.at(step / float(RING_DOTS)),
                          children=[Shape(geometry=self.dot,
                                          appearance=self.dotSkin)])
                for step in range(RING_DOTS)]

    # -- the session ------------------------------------------------------
    def startRecording(self):
        """Record this session, unless the environment already asked for one.

        `OPENGLCONTEXT_TELEMETRY` and `OPENGLCONTEXT_TELEMETRY_REPLAY` are
        both installed before OnInit runs, so a demo that started its own
        recording regardless would write a second file nobody asked for and
        take a replay's input away from it.
        """
        if self.telemetry is None:
            self.startTelemetry()
        print('session: %s\n' % (self.describeSession(),))

    def describeSession(self):
        """What this session is doing with telemetry, in one line."""
        from OpenGLContext import telemetry

        session = self.telemetry
        if session is None:
            return 'nothing is being recorded'
        if isinstance(session, telemetry.ReplaySession):
            return 'replaying %s (%d frames, %d inputs, %d marks)' % (
                session.path, session.replay.recording.frames,
                len(session.replay.recording.inputs),
                len(session.marks.expected))
        return 'recording to %s' % (session.path,)

    def OnQuit(self, event=None):
        """Close the journal, then say where it went and what is in it."""
        session = self.telemetry
        self.stopTelemetry('quit')
        if session is not None:
            self.reportSession(session)
        return BaseContext.OnQuit(self, event)

    def reportSession(self, session):
        """The journal this session wrote, read back through the report."""
        from OpenGLContext import telemetry
        from OpenGLContext.telemetry import report

        if isinstance(session, telemetry.ReplaySession):
            print('\nreplayed %s\n  %s'
                  % (session.path, session.marks.verdict()))
            return
        path = session.path
        print('\nrecorded to %s:\n' % (path,))
        print(report.describe(telemetry.Recording.read(path)))
        print('\nread it back:  python -m OpenGLContext.telemetry %s' % (path,))
        print('run it again:  OPENGLCONTEXT_TELEMETRY_REPLAY=%s python %s'
              % (path, sys.argv[0]))

    # -- what the keys do -------------------------------------------------
    def OnFlare(self, event):
        self._flare_until = self.motionTime() + FLARE_SECONDS
        self.mark('flare')
        self.triggerRedraw(1)

    def OnPause(self, event):
        now = systemtime.systemTime()
        if self._paused_at is None:
            self._paused_at = now
        else:
            self._paused_for += now - self._paused_at
            self._paused_at = None
        self.mark('paused', running=self._paused_at is None)
        self.triggerRedraw(1)

    def OnCheckpoint(self, event):
        laps = {body.name: body.laps for body in self.bodies}
        self.mark('checkpoint', **laps)
        print('checkpoint: ' + ', '.join('%s %d' % pair
                                         for pair in laps.items()))

    # -- the frame --------------------------------------------------------
    def motionTime(self):
        """Seconds of orbiting so far: the world's clock, less any pause.

        The engine's clock rather than the wall clock, so a replay reads
        the instants the recording read and the bodies stand where they
        stood; see OpenGLContext.events.systemtime.
        """
        now = self._paused_at if self._paused_at is not None \
            else systemtime.systemTime()
        return now - self._started - self._paused_for

    def OnIdle(self, event=None):
        seconds = self.motionTime()
        for body, mover in zip(self.bodies, self.movers, strict=True):
            mover.translation = body.position(seconds)
            laps = body.completed(seconds)
            if laps > body.laps:
                body.laps = laps
                self.mark('lap', body=body.name, lap=laps)
        scale = (FLARE_SCALE if self._flare_until is not None
                 and seconds < self._flare_until else 1.0)
        self.lamp.scale = (scale, scale, scale)
        self.triggerRedraw(1)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
