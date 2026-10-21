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
- Remaining main-thread cost by stage: the opaque pass 3.4 ms (the PBR shapes, 0.7 ms of it the
  material setup for each), shadow maps 2.0 ms, view preparation 2.3 ms, the update 2.3 ms.

## Pass work, measured one change at a time

Each change was measured on identical frames (a fixed clock, so every run plays the same course),
by main-thread CPU per frame over 2,400 frames, alternating the builds for three rounds. The
benchmark's own repeat of the same code differs by 1.5 per cent, so a change under about 0.3 ms
was kept only where a call count, or a stage's time with the work it replaced, shows it.

Kept:

- An instance grouping works a shape out once: the key's answer serves the flag, so the
  grouping's 288 shape lookups a frame are 185. 0.83 ms to 0.57 ms in the grouping's own timer;
  about 0.1 ms of the frame.
- The opaque pass sets up no draw for a shape whose geometry draws with its own program: matrix
  uploads a frame 146 to 95, zone setups 83 to 32, 0.4 ms of that pass's timer.
- `shadowFarInterval`, off by default: the cascades beyond the nearest drawn every second or third
  frame. Depth draws a frame 3 to 2 (interval 2) and 1.7 (3); the main thread 11.8 ms to 11.1
  (2) and 10.8 (3). At 3 the hill runner's frame differs from every-frame shadows in 0.017 per
  cent of its pixels, none by more than 12 of 255.

All kept together, the main thread's CPU per frame on the same frames is 11.68 ms before, 11.49
with the interval at 1 and 10.87 with it at 2.

Not kept, with what was measured:

- A memo of `appearance_alpha`, `x3d_lit` and `Appearance.sortKey`: they cost 0.13, 0.12 and 0.21 ms
  a frame in all, at about one call for each shape. A cross-frame memo wants field-observer
  invalidation, including a texture's alpha, which changes as its image loads.
- Keeping the walk's rows from one frame to the next: 0.04 to 0.07 ms off a 0.77 ms walk. The time is
  the scenegraph's per-path lookups (`transformMatrix` 2.4 us, `getPoints` 1.2 us, twice a path),
  and not the array writes.
- Skipping the per-shape fill style, texgen, wave, vertex colour and solid colour setters when
  nothing changed: with all of them stubbed out the frame is 0.14 ms shorter.
- The per-draw transforms in one buffer: the matrix upload is 0.25 ms of a frame, under 2 per
  cent, for a change to both shaders and a second draw path.
- `greatestDepth` reading the walk's answer in place of asking each volume again: at most 0.18 ms.

Left, each under 0.3 ms: the second `getPoints` per path, the caster-geometry arrays rebuilt each
frame (`_casterWorldGeometry`, 0.23 ms), and the PBR shape's `configure_appearance`, which costs
0.66 ms for 34 shapes and whose same-material early-out also wants the same `Appearance`.
