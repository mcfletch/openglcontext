# A settle capture runs on the wall clock

**Status:** 📋 Planned — the defect is measured and one symptom is fixed; the
remedy below is not applied, because it re-poses every animated capture in the
reference corpus and that re-blessing is a decision for whoever owns those
baselines.

## What happens

`OpenGLContext.video.clock.capture_clock()` says what a capture is for:

> A capture renders a fixed number of frames and reads the last one back, so
> what it catches should follow from the scene rather than from how quickly the
> machine reached that frame.

It installs a `FixedStepClock` when `OPENGLCONTEXT_AUTO_EXIT_FRAMES` is set —
and only then. The viewer's own capture (`oglc-view --capture`, which is what
`oglc-gltf-regression` and `OpenGLContext.bin.gltf_regression` drive) does not
set that variable. It uses `SettleCapture` (`OpenGLContext/capture.py`), whose
`tick()` waits for two floors:

```python
if self._frames < self.min_frames:      # --frames
    return False
if perf_counter() - self._start < self.delay:   # --capture-delay
    return False
```

So the scene keeps running on the **wall clock** until `delay` seconds have
passed. Everything reading `events.systemtime` — every `Timer`, every
`TimeSensor`, every glTF animation — is therefore at `delay` seconds plus
whatever jitter the machine contributed, rather than at a stated instant.

## What it costs

An animated model is captured mid-motion at a pose nothing chose, and the pose
moves with the machine and with the load on it:

| Capture of `CommercialRefrigerator` | Difference |
|---|---|
| Two runs, same machine, quiet | 0.24% of pixels |
| Two runs, same machine, one under load | 0.30% |
| NVIDIA RTX 3060 Ti baseline vs AMD Radeon 8060S | **3.44%** — over the 2% tolerance |
| Two runs with the animation pinned (`anim_time=4.0`) | **0** |

The door of that model swings open over the first second and shuts again by
3.3s, so half a frame's worth of drift moves it visibly. The scene read as a
cross-vendor rendering regression; it is a clock.

Nine further scenes in the roster are animated and pin no `anim_time`, so each
is captured at an arbitrary pose today:

| Scene | Animation span | Channels |
|---|---|---|
| `IridescentDishWithOlives` | 6.67s | rotation |
| `AnimatedColorsCube` | 3.0s | pointer, rotation, translation |
| `ChronographWatch` | 60.0s | rotation |
| `CubeVisibility` | 5.0s | pointer (visibility) |
| `DiffuseTransmissionPlant` | 16.67s | rotation, scale, translation |
| `MorphStressTest` | 9.37s | weights |
| `RiggedSimple` | 2.08s | rotation, scale, translation |
| `VirtualCity` | 30.0s | rotation, scale, translation |
| `MeshoptCubeTest` | 2.0s | rotation |

`RiggedSimple` already differs from its baseline by 1.65% of pixels, against a
2% tolerance.

## The remedy

Two changes, and they only work together:

1. **Install the capture clock for a settle capture.** `capture_clock()` turns
   on for a bounded run; a `--capture` run is one. A viewer that has been asked
   for a picture is not being watched, which is the condition the fixed-step
   clock exists for.

2. **Stop the clock at the frame the capture is of.** With (1) alone the scene
   time becomes `frames_drawn / fps`, and `frames_drawn` still follows the
   wall-clock delay — a 2000 fps machine draws twice as many frames in the same
   0.5s as a 1000 fps one. The delay is there so asynchronous work (texture
   decodes, the adaptive analytic-sky IBL) can finish, and none of that needs
   the world to move: past `min_frames` the capture should keep drawing the
   *same instant* until the delay is satisfied.

The result is that `--frames N` names the instant — frame N — and
`--capture-delay` goes back to being what it says it is, a floor on waiting.

## Why it is not applied here

Every animated capture in `tests/reference_images/` — the glTF baselines and
the script reference frames alike — was blessed at whatever pose the wall clock
had reached, so the change re-poses all of them and each needs re-blessing after
review. The corpus was blessed on an NVIDIA RTX 3060 Ti; re-blessing it from a
different GPU narrows what the 2% cross-vendor tolerance is absorbing. That is
worth doing on the machine the corpus belongs to, deliberately, rather than as a
side effect.

## What has landed

`CommercialRefrigerator` pins `anim_time=4.0`, inside the stretch where the door
is shut, so the capture looks through the glass and no drift can move the pose.
Its baseline is re-blessed and the two renders are byte-identical run to run.
`gltf_demos.SceneSpec.anim_time` is the same mechanism `RecursiveSkeletons` and
sixteen other scenes already use; it poses a capture deliberately, which stays
worth doing whatever the clock does underneath.

Separately, `gltf_regression._gl_renderer` now probes through
`OpenGLContext.testing.glcontext.hidden_window` at the core profile
`render_view` pins, so the GL identity stamped into a baseline is the context
the render was actually made in. It previously hand-rolled GLFW with no profile
hint and recorded a compatibility context on any driver that names the profile
in `GL_VERSION`.
