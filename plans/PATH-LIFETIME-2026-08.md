# Path lifetime and the cost of a frame

*2026-08-21*

## What was wrong

A drive through a streamed 3D Tiles world grew more expensive the longer it ran.
Measured on the glisteel forest circuit at 960x540: **0.5 s per frame at the
start line, 3.85 s per frame two thirds of the way round**, with the GPU at 0%
utilisation and Python holding 176% of a CPU. The cost tracked how long the
session had run, not what was on screen.

Counting the dispatcher's population during a drive showed why:

| t | receivers | widest signal | cache holders |
|---|---|---|---|
| 15 s | 406,538 | 4,417 | 5,016 |
| 60 s | 947,768 | 10,535 | 11,168 |
| 105 s | 1,273,792 | 14,215 | 14,894 |

Senders and signals stayed flat; receivers climbed about 13,000 a second, and a
single signal reached 14,215 receivers. Every field written on a node that many
paths depended on notified all of them, so the fan-out widened without bound.

Nearly every one of those holders was keyed `('matrix', True, True, True)` --
the transform matrix cached against a `NodePath`.

## Where they came from

`Switch._onSwitchChange` was wired to `('set', whichChoice)`, which fires on
every **assignment**. Level-of-detail assigns `whichChoice` each frame from the
viewer's distance, so the pass was told "the choice changed" every frame with a
choice that had not changed.

`FlatPass.onSwitchChange` responded by walking the subtree again, leaving a
second path to the same node, and a third. Its guard --- invalidate the children
that are not the current choice --- could never fire, because every duplicate
also ended at the current choice. Instrumenting a drive showed
`children_not_value: 0` at every sample while `children_seen` climbed from 52 to
120 per change, and 27,395 paths created over 480 changes.

`FlatPass.purge` had a second, independent defect: it called `npFor(v)` with a
*path* where `npFor` is keyed by *node*, so it looked up an entry that could not
exist, created an empty list, removed nothing from it, and deleted the entry it
had just made. `nodePaths` also holds paths for nodes the pass draws nothing
for, which walking `self.paths` alone can never reach.

## What changed

- **`Switch._onSwitchChange`** sends only when the resolved child differs from
  the one last announced, held weakly so remembering it keeps nothing alive.
  The signal reports a change of child, not a write.
- **`FlatPass.onSwitchChange`** keeps a live path to the named child rather than
  walking it again, and keeps exactly one: further duplicates are invalidated.
- **`FlatPass.purge`** drops invalidated paths from both records, sweeping
  `nodePaths` by node rather than through `self.paths`.
- **PyDispatcher** gained a constant-time presence index for `connect()`, and
  `robustApply` now derives a receiver's parameters once per code object rather
  than on every dispatch. (The workspace checkout already carried the index; the
  virtualenv had a PyPI build installed over it and was not using it.)

## What it bought

Same drive, same measurement points:

| | before | after |
|---|---|---|
| receivers at 105 s | 1,273,792 | 32,343 |
| widest signal | 14,215 | 173 |
| cache holders | 14,894 | 1,195 |
| frame cost | 3.85 s | 0.045 s |

The population now rises and falls with what is streamed in rather than climbing
monotonically, and a frame costs the same at the end of a lap as at the start.
The recorded lap that took two hours and forty-six minutes to reach 2,598 frames
now renders 3,226 frames in two and a half minutes.

## Where the cases live

- `tests/unit/test_flatpass_purge.py` -- a path whose subtree has left the graph
  is dropped from both records, and nothing holds it afterwards.
- `tests/unit/test_switch_integration.py` -- being told the same choice
  repeatedly does not grow either record; a real change is still followed; the
  signal says nothing about an assignment that changes nothing.
- `pydispatcher/tests/test_robustapply.py` -- the signature is derived once per
  code object, distinct signatures are not confused, and a call with no keyword
  arguments needs no signature at all.
