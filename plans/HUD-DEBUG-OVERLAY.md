# HUD widgets and the developer overlay

Screen furniture drawn over a live world, and the one place a developer's
numbers belong. Two modules of widgets, one context mix-in, and the retirement
of the frame-rate display that could not run in a core profile.

Requested by twig-bb's [§2 and §3](../../twig-bb/PROJECT-PLAN.md) — a debug
overlay and a game HUD — under the rule that anything a *second* game would
want identically belongs here rather than in the game.

## The problem this solves

Before this, a game had exactly one way to put anything on screen over its
world: an overlay panel. A panel is **modal** — while it is up, nothing under
it hears anything — which is right for a settings screen and wrong for a health
bar. A game that wanted a crosshair had to reach past the whole UI and drive
`OverlayRenderer` itself, which is what twig-bb's movement-mode label did.

And the frame rate was drawn twice, both times badly: `FrameCounter.Render`
used `glOrtho`/`glPushAttrib`, which mean nothing in a core profile, and
`FlatPass.shaderRenderFrameCounter` was a second, shader-side copy of the same
two numbers with its own font size and its own colours. Neither could show
anything a developer actually wanted beyond those two numbers, because adding a
row meant editing the renderer.

## The shape of the answer

**A HUD layer is a widget tree that never takes an event.** It is a
`RootWidget`, like a panel, so it has children and a skin and everything in it
finds both by walking up; unlike a panel it fills the viewport, is laid out
every frame, and answers `widget_at()` with `None` — the pointer goes through it.

**Placement is by anchor.** Health in one corner, ammunition in another, the
reticule in the middle. Every HUD widget carries an `anchor` and an `offset`,
and `place()` is the whole of the arithmetic. A child with no anchor is given
the layer's whole rectangle, so the existing `Row`/`Column`/`Grid` still work
inside a HUD.

**One drawing seam for both kinds.** `ScreenMixin.screenTrees()` returns the
visible HUD layers; `OverlayMixin` overrides it to append the open panels; the
renderer draws the list in one `begin`/`end`. A whole HUD plus the screen over
it is two or three draw calls, and the ordering — HUD under panels — is a
property of one list rather than of two drawing paths that must agree.

**Every context has HUD layers**, because every context has a frame rate to
show. `ScreenMixin` is therefore a base of `Context` itself, not of
`OverlayMixin` alone; `OverlayMixin` inherits from it, so a game gets both and
the MRO stays linear.

## The developer overlay is fed by providers

This is the part that makes it worth building upstream rather than in a game. A
provider is a callable returning name/value pairs and knowing nothing about
drawing:

```python
context.debugOverlay.register('Map', lambda: [
    ('name', loaded.name), ('family', loaded.family),
], order=40)
```

A new subsystem appears in the overlay by registering, not by anyone editing
the overlay. Values are formatted centrally, so a provider hands over the float
or the flag or the vector it has and never a pre-rendered string, and every
subsystem's values line up in one column.

Three decisions that follow from this being *diagnostic equipment*:

- **A provider that raises becomes an `error` row.** A diagnostic that takes the
  frame down with it is worse than no diagnostic.
- **A provider with nothing to say is left out entirely** rather than drawn as an
  empty heading — a physics section on a map with no physics is noise on a
  screen that is short of room.
- **Registration is by title**, so a reloaded subsystem replaces its section
  rather than growing a second one under the same heading.

Shipped providers: `Frame` (windowed-median rate, frame time, frames, viewport),
`Render` (profile and which features are on, plus what the last frame cost in
shapes, draws and instanced groups), `View` (camera position and any character
controller's grounded state, velocity and mode). `physics_provider` is supplied
for body and contact counts and takes a *callable* returning the world, because
a world is replaced when the next level loads.

### Render statistics: counted, never estimated

`passes/renderstats.py` holds counts the pass already knows for a moment each
frame and then throws away: shapes gathered, how they split between the two
geometry passes, instanced groups and the instances they stood in for, and draw
calls issued. Each is incremented at the place the pass does the thing it
counts.

**Triangle counts are deliberately absent.** The pass does not know them — a
geometry node does — and instrumenting every `render()` in the system would cost
more than the answer is worth. A number that is not counted is not reported.

## What was retired

- `FrameCounter.Render` and `FrameCounter.font`, and with them the last
  fixed-function drawing path in the compatibility pass's frame loop.
  `FrameCounter` still measures; it no longer draws.
- `FlatPass.shaderRenderFrameCounter`, the second copy.
- `FrameCounter.display`. `Context.OnFrameRate` (Alt+F) now toggles the debug
  overlay, which is the thing that draws the rate.
- `OPENGLCONTEXT_DISABLE_FPS_DISPLAY` keeps working and keeps meaning what it
  meant — no numbers over my screenshot — by deciding whether the overlay
  **starts** hidden. The capture harness needed no change.

`Panel`'s children/skin/scaling/link machinery moved up into a new
`widgets.RootWidget`, which a panel and a HUD layer are both kinds of; the two
had identical copies of it.

## Testing

Everything except the pixels is arithmetic over a viewport and a font, so it is
tested with no window: anchor placement, reticule geometry at every shape,
meter thresholds and fills, message expiry and fade, provider registration and
ordering, value formatting, the overlay's laid-out rows, and the order the
trees come back in. 93 tests without GL.

The pixels get seven more against a real driver
(`tests/unit/test_ui_hud_gl.py`): a reticule lands in the middle with its gap
clear, a meter at a tenth of its maximum fills red, a message stops being drawn
when it expires, the overlay's plate reaches the frame, a hidden layer draws
nothing, and a panel opened over a HUD changes the pixels in the middle — which
is the drawing order, asserted rather than assumed.

## Status

**✅ Complete.** Modules: `ui/hudwidgets.py`, `ui/debugoverlay.py`,
`ui/screen.py`, `passes/renderstats.py`, plus `widgets.RootWidget` and the HUD
and debug colours on `Skin`. Docs: [docs/hud.html](../docs/hud.html).

First customer: twig-bb's `twig_bb.hud` and its debug providers.
