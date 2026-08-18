# Recording what the engine draws

**Status:** Landed for NVIDIA on Linux.
**Documentation:** [docs/recording.html](../docs/recording.html)

## What this is for

A game built on OpenGLContext needs recording as much as it needs screenshots: a
trailer, a bug report that shows the fault, a regression video, a replay. The
engine could already write a PNG of one settled frame; it could not write
motion.

The mechanism it now uses is the video encoder sitting on the same die as the
renderer. The frame the renderer has just drawn is blitted into a texture that
encoder reads in place, so nothing but the compressed result crosses the bus,
and a frame costs a GPU-side blit rather than a `glReadPixels` stall.

## Where the parts live

The encoder bindings are **not** in OpenGLContext. They are
[pyopengl-video](https://github.com/mcfletch/pyopengl-video), a separate
distribution over PyOpenGL, brought in by the `video` extra. That package knows
how to talk to encoders; this one knows *when* to. The split keeps a vendor SDK's
release schedule, and hardware OpenGLContext's CI does not have, out of the
engine.

| Part | Where | Why there |
| --- | --- | --- |
| Encoder bindings, MP4 muxer | `pyopengl-video` | Useful to any PyOpenGL application, with no scenegraph in sight |
| `VideoRecorder`, `RecordingMixin`, `copy_frame` | `OpenGLContext/video/recorder.py` | Recording policy: what a frame is, when to take it, when to stop |
| `FixedStepClock` | `OpenGLContext/video/clock.py` | Time, which is an engine concern |
| A settable engine clock | `OpenGLContext/events/systemtime.py` | The one source everything time-driven already read |

## The two decisions worth recording

**The clock.** A recording made against the wall clock plays back unevenly: a
frame that took 40 ms to draw is 40 ms of movement shown for 16 ms, and a world
that streams its content in stutters exactly where the streaming happened. So a
recorder replaces the engine's time source with one that advances a fixed step
per frame drawn.

That works because there was already exactly one source to replace.
`systemtime.systemTime()` is what `Timer` polls and what every `TimeSensor` is
advanced against, so the whole animated scene follows the recording without
knowing about it. `setTimeSource` is the only change the events package needed,
and it is useful beyond recording — a deterministic replay or a frame-stepping
debugger wants the same hook.

The cost is that a recorded run is no longer real time. That is right for a
recording and wrong for a game someone is playing, hence `fixed_step=False`.

An application with its own `time.time()` does not follow, and has to read
`systemTime()` instead. glisteel's did, and now does.

**The flip.** OpenGL's framebuffer starts at the bottom left; a video encoder
reads a texture from its first row and calls that the top of the picture. The
capture blit therefore reverses its destination Y coordinates and turns the
frame over as it copies, at no cost. `copy_frame()` is public because an
application encoding through some other path needs exactly the same copy, and
`tests/unit/test_video_recorder_gl.py` checks it by comparing the texture against
the framebuffer it came from — an orientation test that needs no decoder.

## A distinction that cost a debugging round

`capture()` answers *did I keep this frame*, and `recording` answers *do I want
more*. Collapsing them made the mixin treat the wait for a streaming world as
the recording having finished, and the demo quit on its first frame. Two
questions, two answers.

## What is not here

- **Audio.** The file has a video track. The engine has a spatial audio mixer,
  and recording its output alongside the picture is the obvious next thing.
- **Intel and AMD**, which is
  [pyopengl-video's phase 3](https://github.com/mcfletch/pyopengl-video). The
  recorder needs no change for it: it asks for an encoder and gets whichever one
  the machine has.
- **Recording an offscreen render at a size other than the window's.** The
  recorder takes the viewport, and a caller wanting 4K out of a 720p window
  renders to its own framebuffer and records that.
