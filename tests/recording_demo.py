#! /usr/bin/env python
'''=Recording video (frames straight to an H.264 file)=

[recording_demo.py-screen-0001.png Screenshot]

A carousel of eight coloured blocks turns around a central sphere and bobs
as it goes, which is a scene worth recording: every frame differs from the
last, so an uneven clock shows up as a stutter in the file.

`OpenGLContext.video.recorder.RecordingMixin` is what does the recording.
The frame the renderer has just drawn is blitted into a texture the GPU's
video encoder reads in place, so nothing but the compressed result crosses
the bus, and the recorder advances the engine's clock one frame per frame
written -- the carousel turns by exactly a frame's worth however long the
frame took to draw.

 * `r` -- start recording, or stop and close the file. The lamp above the
   carousel burns red while a recording is running.
 * `c` -- choose the clock the *next* recording runs on: a fixed step per
   frame, or the wall clock, which is what a recording of an interactive
   session wants.
 * the usual keys walk around.

Stopping prints where the file went, how many frames it holds, the rate the
clock ran at and how big the file is:

    recorded 90 frames to recording_demo.mp4
      picture     300x300
      frame rate  30/1 fps (3.000 seconds of video)
      clock       fixed step
      file size   81983 bytes

Run `python tests/recording_demo.py --record 90` to record without anyone
pressing a key: the demo records that many frames, prints the report and
exits. `--output PATH` chooses the file, which is `recording_demo.mp4` in
the current directory otherwise, and the environment variables
`OPENGLCONTEXT_RECORD_FRAMES` and `OPENGLCONTEXT_RECORD_PATH` say the same
two things.

A machine without the `video` extra has no encoder. The demo prints what is
missing at the first frame it would have kept and carries on drawing, so
everything but the recording works as it does anywhere else.
'''
import math
import os
import sys

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from OpenGLContext import testingcontext
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Sphere,
    Transform, sceneGraph,
)
from OpenGLContext.video.recorder import RecordingMixin, RecordingUnavailable

BaseContext = testingcontext.getInteractive('glfw')

#: Frames a second the recording is written at, and so the step the engine's
#: clock takes per frame while one is running.
FPS = 30

#: Frames `--record` writes when it is given no count of its own.
DEFAULT_FRAMES = 90

#: Where a recording goes when nothing says otherwise.
DEFAULT_PATH = 'recording_demo.mp4'

#: Seconds the carousel takes to come back round to where it started.
ORBIT_SECONDS = 8.0

#: Times a block rises and falls in one turn of the carousel. A whole number,
#: so the bob meets itself where the turn wraps and the motion has no seam.
BOB_CYCLES = 3

#: How far out the blocks ride, and how far they rise and fall.
ORBIT_RADIUS = 3.2
BOB_HEIGHT = 0.55

#: The blocks, as the colour each one is made in.
COLOURS = [
    (0.90, 0.28, 0.22), (0.93, 0.60, 0.16), (0.92, 0.85, 0.25),
    (0.44, 0.78, 0.32), (0.25, 0.72, 0.68), (0.28, 0.51, 0.87),
    (0.55, 0.38, 0.83), (0.86, 0.38, 0.63),
]


def recordingRequest(arguments, environment):
    """What the command line and the environment ask to be recorded.

    Answers ``(frames, path)``, with frames None for a run that records only
    when a key asks it to.

    Parsed by hand rather than with argparse because a demo is also loaded by
    the screenshot tool, which runs it with a command line of its own.
    """
    frames = environment.get('OPENGLCONTEXT_RECORD_FRAMES')
    path = environment.get('OPENGLCONTEXT_RECORD_PATH', DEFAULT_PATH)
    remaining = list(arguments)
    while remaining:
        argument = remaining.pop(0)
        if argument == '--record':
            frames = DEFAULT_FRAMES
            if remaining and remaining[0].isdigit():
                frames = remaining.pop(0)
        elif argument == '--output' and remaining:
            path = remaining.pop(0)
    return (int(frames) if frames is not None else None, path)


AUTO_FRAMES, RECORD_PATH = recordingRequest(sys.argv[1:], os.environ)


class TestContext(RecordingMixin, BaseContext):
    """A carousel, and the keys that record it."""

    initialPosition = (0, 3.4, 10)
    initialOrientation = (1, 0, 0, -0.28)   # pitch down onto the carousel

    #: The demo owns quitting: a recording that ends on the `r` key leaves the
    #: demo running, and only one asked for on the command line ends the run.
    quitWhenRecorded = False

    def OnInit(self):
        BaseContext.OnInit(self)
        #: Whether the next recording steps the clock a frame at a time.
        self.fixedStep = True
        self.arms = []
        children = [
            Background(skyColor=[(0.10, 0.13, 0.20), (0.22, 0.27, 0.36),
                                 (0.46, 0.50, 0.56)],
                       skyAngle=[1.15, 1.5708]),
            # A key light over the viewer's shoulder and a cool fill from the
            # far side, so a block reads as a block rather than a silhouette.
            DirectionalLight(direction=(-0.4, -0.7, -0.6), intensity=1.4),
            DirectionalLight(direction=(0.6, -0.2, 0.6), intensity=0.45,
                             color=(0.6, 0.7, 1.0)),
        ]
        # One Transform per block: the carousel turns them all, and each one
        # carries its own block up and down as it goes round.
        for index, colour in enumerate(COLOURS):
            angle = 2 * math.pi * index / len(COLOURS)
            arm = Transform(
                translation=(ORBIT_RADIUS * math.cos(angle), 0.0,
                             ORBIT_RADIUS * math.sin(angle)),
                children=[Shape(
                    geometry=Box(size=(0.7, 1.1, 0.7)),
                    appearance=Appearance(material=Material(
                        diffuseColor=colour, shininess=0.4)))])
            self.arms.append(arm)
        self.carousel = Transform(children=self.arms)
        children.append(self.carousel)
        children.append(Shape(
            geometry=Sphere(radius=1.1),
            appearance=Appearance(material=Material(
                diffuseColor=(0.75, 0.76, 0.8), shininess=0.7))))
        # A floor, so the bob is read against something that stays still.
        children.append(Transform(translation=(0.0, -2.0, 0.0), children=[
            Shape(geometry=Box(size=(16.0, 0.4, 16.0)),
                  appearance=Appearance(material=Material(
                      diffuseColor=(0.30, 0.31, 0.35))))]))
        # The lamp: an emissive material is the whole of it, so it reads as
        # lit rather than as a sphere someone is shining a light at.
        self.lamp = Material(diffuseColor=(0.2, 0.05, 0.05),
                             emissiveColor=(0.12, 0.02, 0.02))
        children.append(Transform(translation=(-3.6, 3.4, 1.5), children=[
            Shape(geometry=Sphere(radius=0.28),
                  appearance=Appearance(material=self.lamp))]))
        self.sg = sceneGraph(children=children)

        self.addEventHandler('keypress', name='r', function=self.OnRecord)
        self.addEventHandler('keypress', name='c', function=self.OnClock)
        self.timer = Timer(duration=ORBIT_SECONDS, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.timer.register(self)
        self.timer.start()
        print(__doc__)
        if AUTO_FRAMES:
            self.startRecording(AUTO_FRAMES)

    def OnFraction(self, event):
        """Turn the carousel, and ride each block up and down as it goes."""
        fraction = event.fraction()
        self.carousel.rotation = (0, 1, 0, 2 * math.pi * fraction)
        for index, arm in enumerate(self.arms):
            phase = fraction * BOB_CYCLES + index / len(self.arms)
            x, _y, z = arm.translation
            arm.translation = (x, BOB_HEIGHT * math.sin(2 * math.pi * phase), z)

    def startRecording(self, frames=None):
        """Begin a recording of `frames` frames, or until the `r` key ends it."""
        self.setupRecording(RECORD_PATH, fps=FPS, frames=frames,
                            fixed_step=self.fixedStep)
        self.showLamp(True)
        print('recording to %s at %s fps%s' % (
            RECORD_PATH, FPS,
            '' if frames is None else ', %d frames' % (frames,)))
        self.triggerRedraw(1)

    def showLamp(self, lit):
        """Burn the lamp while a recording is running."""
        self.lamp.emissiveColor = (0.95, 0.12, 0.1) if lit else (0.12, 0.02, 0.02)
        self.lamp.diffuseColor = (0.6, 0.1, 0.1) if lit else (0.2, 0.05, 0.05)

    def OnRecord(self, event):
        """Start a recording, or stop the one that is running."""
        if self.recording:
            self.finishRecording()
        else:
            self.startRecording()

    def OnClock(self, event):
        """Choose the clock the next recording runs on."""
        self.fixedStep = not self.fixedStep
        print('next recording runs on the %s' % (self.clockName(),))

    def clockName(self):
        return 'fixed step' if self.fixedStep else 'wall clock'

    def finishRecording(self):
        """Close the file, report what is in it, and end an asked-for run."""
        recorder = self.recorder
        super(TestContext, self).finishRecording()
        self.showLamp(False)
        if recorder is not None:
            self.report(recorder)
        if AUTO_FRAMES:
            self.OnQuit()
        else:
            self.triggerRedraw(1)

    def report(self, recorder):
        """Detail the mixin's own line does not carry: rate, clock and size."""
        # The rate comes from the recording's own clock where it installed one,
        # and from what it was asked for where it left the wall clock alone.
        if not recorder.frames_written:
            print('  no frames were kept, so there is no file')
            return
        clock = recorder.clock
        numerator, denominator = (clock.frame_rate if clock is not None
                                  else (FPS, 1))
        seconds = recorder.frames_written * denominator / numerator
        size = recorder.path.stat().st_size if recorder.path.exists() else 0
        print('  picture     %dx%d' % recorder.size)
        print('  frame rate  %d/%d fps (%.3f seconds of video)' % (
            numerator, denominator, seconds))
        print('  clock       %s' % ('fixed step' if clock is not None
                                    else 'wall clock',))
        print('  file size   %d bytes' % (size,))

    def SwapBuffers(self):
        # Before the swap: the back buffer holds the frame just drawn only
        # until it is swapped away.
        try:
            self.tickRecording()
        except RecordingUnavailable as error:
            # Nothing here can encode; say so and go on drawing, which is what
            # a machine without the encoder is left with.
            self.recorder = None
            self.showLamp(False)
            print('recording unavailable: %s' % (error,))
        return super(TestContext, self).SwapBuffers()

    def OnIdle(self, event=None):
        # A recording wants a frame every time round the loop, whether or not
        # the last one changed anything the renderer noticed.
        self.triggerRedraw(1)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
