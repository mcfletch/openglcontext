# Frame time headroom

The hill-runner demo (3840 x 2160, PBR with three shadow cascades, about 113 shapes and
75 draws a frame) ran at 33 to 55 frames a second on a Radeon 8060S, and slowest where the
ground cover was densest. The GPU took 7 to 11 ms a frame. The main thread's Python did the
rest, so the work was on the main thread's CPU time, not on drawing.

## Measuring

Four numbers decide a change, none of them a window's average frame rate:

- Main-thread CPU per frame (`time.thread_time` between frames): median and 99th percentile.
  It does not move with the display's 60 Hz rate, and moves less with what else is running.
- Frame interval percentiles and the count over 25 ms, with the stall tracer
  (`OPENGLCONTEXT_STALL_MS`, `OPENGLCONTEXT_STALL_TRACE`) for what the main thread was doing in
  a slow period.
- Wall time of each stage, by wrapping the stage's method and summing over a window.
- Calls a frame of the function being replaced, which does not drift with the machine.

Other work on the machine moves every timing. A 32-thread machine with 16 cores shares each core
between two threads, and another busy process on the sibling thread slows the main thread by
10 to 30 per cent. Comparisons were run one after the other on a quiet machine, and a change was
kept where its call counts and its CPU time agreed.

## Results

Same course, seed 1, 175 s, 4K, windows of 10 s after a 20 s start:

| Build | Mean fps | Worst window | CPU a frame (idle + submit) |
|---|---|---|---|
| Original | 43.4 | 33.5 | 21.9 ms |
| Disc cull on the processor | 46.5 | 39.6 | 20.2 ms |
| Culling on the GPU (grass, impostors, trees) | 50.4 | 45.4 | 18.6 ms |
| Ground cover scattered in processes | 58 to 60 | 58 | 16.6 ms |
| Game update, fog and display memo, own-program shapes | 59.3 to 60 | 59.3 | median 11 to 12 ms |

On the last build the median frame is the display's 16.7 ms, the 99th percentile 18 to 22 ms, and
no frame in 5,200 took more than 20 ms in the stall harness. Cutting the grass density by a fifth
added one frame a second: what is left costs the same for any number of instances.

## What landed

- `CulledRows` takes a disc: `GroundCover.select` sets the disc on each clump node, which
  stages the whole cache once per scatter (`viewcull.py`, `cover.py`).
- `GPUCulledRows` and `shaders/veg_cull.comp`: the set is uploaded once, a compute pass keeps the
  instances in the view and the disc and counts them in an indirect draw command. Clumps, cards
  and impostors use it; so do the near-mesh trees, with a command for each of the trunk and the
  crown (`gpucull.py`, `nearmesh.py`). `OPENGLCONTEXT_GPU_CULL=0` keeps the processor's culling.
- `CoverProcess` and `CoverScatterMaker`: the scatter runs in a child process
  (`coverprocess.py`). With the scatter off the game held 59 to 60 fps, which is how much the
  threads cost the render thread through the interpreter lock.
- `FrameState` holds the frame's tone curve and fog, each worked out once.
- A geometry that draws with its own program (`drawsOwnProgram`) is not given the pass's
  material state. About 50 of 85 `configure_appearance` calls a frame were for vegetation nodes
  that ignore it.
- `GLLayer.ensure_gl` makes a node's objects again in a context other than the one it made them
  in.
- hill-runner: coins placed once, the camera floor looked up once per 2 m, and the course's
  arithmetic on plain numbers (5.1 ms to 2.8 ms for the update); the runner's scatter processes
  (`--no-scatter-process` turns them off).

## Open

- Restarting a run takes 3.8 s against 2.5 s before: 0.55 s of that is closing and starting the
  scatter processes. The rest is the rebuild of the course and the first scatter, in line.
- A fullscreen window that the compositor stops presenting blocks in the swap. That is the
  display's frame callback and not the game.
- A glisteel frame captured under load can come out with the road dark and lit in another run of
  the same scene, with either culling. Image-based lighting that adapts to the frame rate is the
  likely cause and has not been confirmed.
- Remaining main-thread cost by stage: the opaque pass 5.7 ms (the PBR shapes, 1.0 ms of it the
  material setup for each), shadow maps 2.0 ms, view preparation 2.3 ms, the update 2.3 ms. Candidates
  from a read of the pass code, with estimates that were not measured: the same-material early-out
  in `configure_appearance` also wants the same `Appearance`; `appearance_alpha` runs 240 times a
  frame; `x3d_lit` 336 times; instance grouping runs twice a frame and rebuilds its depth groups
  whenever a caster moves; the gather refills every row each frame; far shadow cascades redrawn when
  nothing in them changed.
