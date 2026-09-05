# Examine navigation: orbit, dolly and pan

Status: **In Progress** (2026-09-05)

## The problem

A right-drag in any OpenGLContext viewer orbits the camera about a pivot. In
practice a small drag threw the camera right round the model and left the user
looking at empty space, with the horizon on its side.

Three separate causes, all measured against `OpenGLContext.move.trackball` as it
stood:

1. **The drag measure is asymmetric.** `move.dragwatcher.DragWatcher.fractions`
   divides the movement by the distance from where the drag *started* to the
   edge of the window — a different divisor on each side of the start point. A
   drag beginning 40 pixels from the left edge of an 800-pixel window turns
   **135°** for 30 pixels of leftward movement and **7°** for the same 30 pixels
   rightward: a nineteen-fold difference decided by where the pointer happened
   to be when the button went down. Starting anywhere near an edge makes the
   gesture uncontrollable in the direction of that edge.

2. **The horizon rolls.** The trackball rotates about the camera's own right and
   up axes. Composing those two rotations produces roll, so a diagonal drag
   tilts the world: 200 pixels of diagonal drag from the middle of the window
   leaves the camera's up vector at `(-0.87, -0.50, 0.00)` — upside down and
   rolled 60°.

3. **Nothing bounds the pitch, and nothing gets you back.** The camera can be
   driven over the pole, and there is no dolly and no pan, so a view that has
   gone wrong has to be repaired with the arrow keys.

## The standard behaviour, and what we adopt

Every established 3D viewer and modelling tool uses the same three gestures with
the same shape, and the engine now matches them:

| Gesture | Action |
|---|---|
| Right-drag | Orbit about the pivot |
| Middle-drag | Pan: the pivot and the camera slide together |
| Wheel | Dolly toward or away from the pivot |

The orbit is a **turntable**: horizontal movement swings the camera about the
world's up axis, vertical movement raises and lowers it, and the elevation is
clamped just short of the pole so the view can never flip. This is what keeps
the horizon level — yaw about a fixed up axis and pitch about the horizontal
axis perpendicular to the view introduce no roll — and it is the behaviour of
Blender's turntable orbit, Maya's tumble and the browser-side `OrbitControls`
convention alike. The alternative, Shoemake's arcball, has no preferred up and
so trades a level horizon for the ability to spin a model freely; for examining
a scene that stands on a ground plane, the turntable is the better default.

Sensitivity is **uniform**: the angle turned is proportional to the pixels
moved, at the same rate everywhere in the window and in both directions, with
the window's height as the span for both axes so a circular hand movement traces
a circular orbit. A drag the height of the window is half a turn
(`EXAMINE_DRAG_ANGLE`).

The camera keeps whatever aim it had. The pivot is the point under the cursor,
which is usually not the centre of the screen, so orienting the camera straight
at it would snap the view the instant the button went down. The orbit records
the rotation between "looking at the pivot" and "looking where you were looking"
when the drag begins, and re-applies it every frame; the view therefore starts
moving from exactly where it was.

## What was built

- **`OpenGLContext/move/orbit.py`** — `TurntableOrbit`, the whole of the maths,
  as a plain object that takes numbers and answers a position and an
  orientation. No GL, no window, no events, so every rule in it is directly
  testable. `rotate()`, `dolly()` and `pan()` are the three gestures;
  `aimAt()` is the levelled look-at they are all built on.
- **`OpenGLContext/move/examinemanager.py`** — drives the orbit from events, and
  now understands the wheel (dolly) and a pan drag as well as the rotate drag.
  A wheel notch arriving during a rotate drag no longer *cancels* the drag,
  which it did: the notch's button release read as "a button other than mine
  came up", which is the cancel condition.
- **`OpenGLContext/move/movementmanager.py`** / **`direct.py`** — the pan and
  dolly bindings, beside the examine binding that was already there.
- **`OpenGLContext/move/dragwatcher.py`** — `uniformFractions`, the symmetric
  measure, beside the edge-relative `fractions` that some interactions still
  want. `Trackball` uses the symmetric one.

## Not changed

`Trackball` stays. It is a documented customisation point, it is what
`ExamineManager.OnBuildOrbit` can be overridden to return, and an application
that wants a free-spinning arcball rather than a turntable should have it. What
it gained is the symmetric drag measure, since the asymmetry was a defect in it
rather than a property anyone chose.
