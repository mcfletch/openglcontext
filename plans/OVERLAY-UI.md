# Plan: Overlay UI — settings, key bindings, console

**Status:** ✅ Complete — all seven stages are built, tested and documented.
User documentation is [docs/overlayui.html](../docs/overlayui.html); the demo is
`oglc-ui` (`--skin` for the nine-slice artwork). The sections below are the
design and its reasoning, which the code follows.

Two things landed alongside the stages and are worth naming because they are not
in the stage list. Every switchable rendering feature — shadows, soft shadows,
cascades, the light limit, bloom, IBL and its intensity, transmission,
instancing, distance LOD, vsync — is now a **field on `ContextDefinition`** read
through `OpenGLContext.renderoptions`, with the environment variable as the
field's default; the settings screen is generated from those fields. And
`twitchoglc.confirm` is gone: the download prompt is a `dialogs.confirm` panel,
so the prototype has been replaced rather than left beside its successor.

## What this is for

A real game needs a screen it can bring up over the running world to change
things: rendering options, preferences, key bindings, and a console. It also
needs somewhere to put a wall of text nobody can style away — copyright and
licence notices — and somewhere to ask a yes/no question, such as whether to
download an asset pack.

Two pieces this plan once listed as missing now exist and are not re-planned
here: the download prompt's answers are **real measured buttons** (hover-lit and
hit-tested, not text with a keyboard trap), and
`ViewPlatformMixin.suspendPointerCapture()` releases a mouse-look mode's grabbed
pointer while an overlay wants it.

There is already a working proof that the overlay path itself is sound.
`twitchoglc.confirm.ConfirmPrompt` plus `FlatPass`'s `renderShaderOverlay` hook
draws a translucent panel over a live frame at full frame rate, with **Yes and
No as real clickable buttons** — measured rectangles, hover highlighting, hit
tested against the pick point — and the keys kept as accelerators. Layout and
hit-testing are separated from drawing, so they are unit tested with no GL
context.

It also shows what a real system still has to add: **the text runs off the
panel**, because nothing measures or wraps it; **there is no press/release
arming**, so a click cannot be cancelled by dragging off; and **the prompt owns
its own keys globally**, because there is no focus model.

This plan is the smallest system that fixes those and scales to a settings
screen. It is deliberately not a widget toolkit.

## Scope

**In:**

- A stack of overlays, nested modals, and per-dialog draft state.
- Widgets: label, button (with a primary/secondary/danger role), toggle
  (checkbox), select (cycle through options), text field (single line), slider,
  and a key-capture field for rebinding.
- Layout: vertical and horizontal boxes, a grid for label/control pairs, and a
  scrollable viewport for when a page or a text block is longer than its space.
- A scrollbar, with drag, wheel and keyboard paging.
- Per-game artwork: a skin supplying an image per widget state.
- A console: scrollback, an input line, and command dispatch.
- An observable model, edited on a copy, committed or discarded as a unit.

**Out, deliberately:** free-form window management, docking, drag-and-drop,
rich text, tables, animation/tweening, an immediate-mode API, and any attempt
to be a general application toolkit. If a game needs those it should host a
real toolkit in another window.

## The model

**A dialog's model is a node, and the widgets edit a copy of it.**

Settings are already nodes with typed fields — `ContextDefinition`,
`WalkMode`, `SwimMode`, `KeyBinding` — which means validation, defaults and
serialisation exist and a settings screen needs none of its own. That is the
same reasoning that put movement modes in `move/modes.py`, and it should not be
re-litigated per subsystem.

```python
session = SettingsSession(target=context.contextDefinition)
session.draft            # a deep copy; every widget edits this
session.dirty            # whether the draft differs from the target
session.commit()         # copy the draft's fields back, one notification per field
session.revert()         # throw the draft away
```

### A sub-record is edited by a nested session

A settings screen opens other screens: movement settings from the main page, a
key-capture dialog from the bindings list, a confirmation over any of them. Each
of those edits a **copy of the sub-record**, launched with that copy and copying
the result back only on success — the same rule as the top level, one layer down.

```python
child = session.child('movementModes', index=0)   # or child(node, 'walk')
child.draft          # a copy of *the parent's draft* sub-node, not of the live one
child.commit()       # writes into the parent's draft; still nothing has been saved
child.revert()       # throws the child's draft away, parent untouched
```

**A child's Commit is not a save.** It writes into the enclosing draft, and only
the outermost `commit()` reaches the real node. That is the whole point: cancel
the movement-settings page and the walk speed is unchanged; cancel the *settings
screen* after applying that page and it is still unchanged. A child dialog that
wrote straight to the live node would make the parent's Cancel a lie, which is
the failure this design exists to prevent.

Two rules the copying must keep:

- **Commit copies fields into the existing node, never swaps the node.** A
  sub-record may be `USE`d in two places, and replacing the `SFNode` would leave
  the second reference pointing at the old one. Copying field-by-field also means
  existing watchers — `movementMode` observers, a HUD — are notified normally.
- **`dirty` propagates upward.** A committed child makes its parent dirty, so the
  settings screen's Apply button lights up for a change made two dialogs deep.

Editing a copy is what makes Cancel real, makes Apply/Revert honest, and stops
a half-typed number from reaching the renderer on every keystroke. Committing
writes through the ordinary field setters, so anything already watching a field
— `movementMode` watchers, for instance — is notified normally and nothing
needs a second notification channel.

A widget binds to `(node, field name)`. It reads the current value through the
field, writes through the field, and asks the field for its type to choose an
editor: `SFBool` → toggle, `SFFloat`/`SFInt32` → slider or number field,
`SFString` → text field, `MFString` on a `KeyBinding` → key capture. A screen
can therefore be generated from a node with no per-setting code, and
hand-authored only where the generated form is not good enough.

## Widgets and skinning

A widget is a node too, so a screen is a scenegraph a game can author, parse
and `DEF`/`USE` like anything else:

```
Panel {
  layout Column { spacing 8 }
  children [
    Label  { text "Movement" }
    Row    { children [ Label { text "Walk speed" } Slider { target USE walk  field "walkSpeed" min 1 max 10 } ] }
    Row    { children [ Label { text "Invert look" } Toggle { target USE fps field "invertLook" } ] }
    Row    { children [ Label { text "Jump" }        KeyCapture { target USE jumpBinding field "keys" } ] }
    Row    { children [ Button { text "Apply" role "primary" action "commit" }
                        Button { text "Cancel" action "revert" }
                        Button { text "Reset bindings" role "danger" action "reset" } ] }
  ]
}
```

### Emphasis and focus

A button needs to say two more things than up/over/down: **how much it matters**,
and **whether it is where the keyboard is**. They are different questions and get
different answers.

**Emphasis is a role, and the skin renders it as text colour.** A `Button` carries
`role` — `primary`, `secondary` (the default) or `danger`. Colour rather than a
second frame image because the alternative multiplies the asset set: four states
times three roles is twelve images per button, and a game would ship eleven
near-identical ones. One frame, three text colours from the skin, and a game that
really wants a distinct primary frame can still supply one, since `role` is a
semantic field rather than a colour.

`danger` earns its place at stage 5: "reset all bindings" and "discard changes"
are the two actions a settings screen must not let someone hit by accident.

**Role also carries behaviour, not just paint.** The `primary` button of a panel
is its default action: Enter activates it when focus is not inside a widget that
wants Enter for itself. That is what makes "Yes" the primary on the download
prompt rather than merely the blue one, and it is why the field belongs on the
widget rather than in the skin.

**Focus is a glow, and it is not hover.** They are orthogonal — the pointer can
rest on one widget while the keyboard is on another, and a design that shares one
highlight makes that state unreadable. Hover lights the frame; focus draws an
additive glow *outside* the widget's rect, from its own nine-slice ring in the
skin. Outside rather than inset because a border either eats the widget's padding
or moves its text by a pixel when focus arrives, and text that shifts as you Tab
through a form is the thing that reads as broken.

Two consequences to carry rather than discover:

- **A scroll viewport clips with a scissor rectangle**, so the glow of a focused
  widget at the very edge of a scrolling list is clipped. The viewport therefore
  scrolls a newly focused child to be fully visible *including its glow margin*,
  which it must do anyway to bring off-screen widgets into view.
- **The ring shows for keyboard focus and for text-entry focus, not for every
  click.** Clicking a button and having it keep a ring afterwards looks like it
  is stuck; clicking into a text field and getting no ring leaves you typing with
  no idea where the characters are going.

**Skinning.** A game supplies a `Skin` node holding one image per widget state
— button up/over/down/disabled, check empty/full, slider track and thumb,
scrollbar track/thumb/arrows, panel background. The default skin is drawn from
flat translucent rectangles so the system works with no artwork at all, which
matters for a viewer that is not a game.

Images are nine-slice: four corners fixed, edges stretched, centre stretched or
tiled. Without that, one button image cannot serve two button widths, and a
game ends up shipping an image per label. Text is measured, then drawn into the
widget's content box inset from the frame, so the artwork and the text stay
independent.

**Translucency is the default.** These panels sit over a live world and should
read as a layer on it, not a replacement for it. The default skin is a dark
translucent fill; a game overrides it.

## Layout

One pass, top-down, no constraint solver:

1. Each widget reports a natural size (text measured through the existing
   shader font, images from their nine-slice minimum).
2. A box distributes its main axis: fixed children take their natural size,
   `flex` children share what is left. `hud.py` already carries `flex`, `width`,
   `height`, `left/right/top/bottom` fields for exactly this and is otherwise
   unused — this is what it was for, and it should be used rather than
   duplicated.
3. A scroll viewport gives its child unlimited space on the scroll axis, then
   clips to its own box with a scissor rectangle and offsets by the scroll
   position.

Layout runs when something changes, not per frame.

## Input: the mouse drives it

**When the overlay has focus, the pointer is the interaction.** Everything is
clicked, dragged or scrolled: buttons, toggles, select arrows, slider thumbs,
scrollbars. The keyboard is for two things only — typing into a field that
wants text, and accelerators for people who prefer them. A settings screen that
has to be driven by guessing keys is not a settings screen.

That has consequences the design has to carry from the start, not retrofit:

- **Every widget has a rectangle**, measured at layout time, and hit-testing is
  front-to-back through the panel tree. A widget that only knows its text has
  nothing to click.
- **Hover is a first-class state.** A button that does not light under the
  pointer reads as scenery. It is one of the skin states for that reason.
- **Press and release are distinct.** A button arms on press over itself and
  fires on release over itself, so dragging off it cancels — the behaviour
  every pointer UI has and whose absence is immediately noticeable.
- **The cursor is released while an overlay is up**, so `FPSMode`'s captured
  pointer does not fight the pointer the user needs to click with. Entering an
  overlay ungrabs; leaving re-grabs. This one is built:
  `ViewPlatformMixin.suspendPointerCapture()`.
- **Focus follows the click** for typing-enabled widgets. A text field or a
  key-capture field takes the keyboard only once clicked into; Tab moves
  between them; Escape leaves. A key-capture field then takes the *next* key
  whatever it is, which is why focus has to be explicit rather than implied.

### A modal overlay sinks all input

**While a modal overlay is up, no input reaches the world at all** — not the
events the overlay handles, and not the ones it ignores. It is not a filter that
passes what it does not want; it is a lid. A panel carries a `modal` field, and
the download prompt is modal: it is a question that has to be answered.

That rule is simpler than a per-event `consumed` flag and it is the only one
that can be got right, because "which events does this widget want" is a
question every new widget would have to answer honestly forever.

It has a consequence the wiring must carry, and it is the reason this is stated
here rather than left to the implementation: `ViewPlatformMixin.ProcessEvent`
feeds `InputState` **before** it dispatches, so a key the overlay consumes has
already been recorded as held. Gating the handlers alone would leave a player
walking into a wall while typing into a text field. So:

- while a modal overlay is up, the sampler is not fed at all;
- entering one calls `InputState.clear()`, or whatever was held at that moment
  stays held for as long as the overlay is open;
- leaving one starts from nothing held, which is what the player's fingers
  actually report on the next key event.

`InputState` itself is unchanged: it samples continuous movement, and discrete
pointer-driven UI is a different job.

### Modals stack, and only the top one hears anything

Overlays form a stack. The rule above is the stack applied recursively: **the
topmost modal receives input and everything under it receives nothing** — the
world, and any parent modal. A confirmation over the settings screen means the
settings screen is as deaf as the scene behind it.

Closing a child restores focus to the widget that launched it, or Tab order
restarts at the top of the parent page every time a dialog closes.

**Key capture needs a tighter lid than the rest.** A rebinding dialog has to see
*any* event the user can produce, including the ones the UI would normally eat
for itself: Tab, Enter, the mouse buttons and the wheel are all bindable. So a
panel may declare itself `capturing`, and while it is up the overlay runs no
accelerators, no focus traversal and no primary-button Enter default — every
event goes to the capture widget verbatim.

That leaves one key that cannot be bound, because something must get you out:
**Escape is reserved**, and the dialog says so on its face. The alternative — a
timeout, or requiring a mouse click on Cancel — either makes the dialog feel
broken or fails for the person rebinding mouse buttons.

The natural example of nesting is exactly here: capture a key, find it is already
bound to something else, and raise a confirmation *over the capture dialog* to ask
whether to steal it.

**This reverses a rule the prototype stated deliberately.**
`twitchoglc.confirm.ConfirmPrompt.key()` documented that an unrecognised key was
*not* consumed "so walking and looking keep working while the prompt is up".
Under modality that is wrong: the prototype and the test that pinned it are gone,
and `Panel.key` is a lid.

## Console

The console is a scroll viewport plus an input line, and it is the same
scrolling machinery a licence notice uses. Commands dispatch through a registry
a game adds to; the log view is fed by a Python logging handler so engine
warnings appear where a player can read them.

## Delivery

Each stage ends with something usable and tested, and stops if it turns out to
be the wrong direction.

1. **Measurement and boxes** — `ui/geometry.py`, `ui/metrics.py`, `hud.py`
   (`GUINode`/`GUIBox` implemented rather than replaced), `ui/layout.py`,
   `ui/skin.py`. Delivered: the download prompt as a `Panel` whose text wraps
   to a measured `preferredColumns` width and stays inside its box.
2. **Widgets and focus** — `ui/widgets.py`, `ui/panel.py`, `ui/overlay.py`,
   `ui/draw.py`. Delivered: the prompt as a modal `Panel` whose Download is the
   primary/Enter default, drawn by one batched GL program;
   `twitchoglc.confirm` deleted.
3. **Model binding** — `ui/session.py`, `ui/generate.py`, `ui/settings.py`.
   Delivered: a rendering-settings page generated from `ContextDefinition`'s
   fields, opening a movement sub-page whose Cancel is real at both levels.
4. **Scrolling** — `ui/scroll.py`. Delivered: `dialogs.notice`, a licence screen
   that scrolls, and every long page in the system.
5. **Key binding** — `ui/bindings.py`, `move/bindingstore.py`. Delivered: a
   rebinding page over `NavigationManager.binding_table()`, with a `capturing`
   dialog, a conflict confirmation raised over it, and JSON persistence in the
   per-user app-data directory.
6. **Skinning** — `Skin`, `NineSlice` and the nine-slice draw path. Delivered:
   `oglc-ui --skin`, whose artwork is generated at start-up so the demo proves
   one image serves every widget width with no binary in the repository.
7. **Console** — `ui/console.py`: scrollback, input line, command registry and
   a `logging.Handler` that puts engine warnings where a player can read them.

## Risks

- **Scope.** A UI toolkit is a place where work goes to disappear. The scope
  list above is a commitment, and anything not on it needs a reason before it
  is added.
- **Text quality.** The shader font is a fixed-size bitmap atlas. Fine for a
  console and adequate for settings; a game wanting a distinctive typeface will
  want signed-distance-field glyphs, which is a separate job.
- **Whether nodes are the right substrate for widgets.** Fields give
  validation, serialisation and change notification for free, which is most of
  a UI framework. The risk was per-widget-per-frame node overhead in a large
  scrolling list. It has not bitten: layout runs on a change rather than a
  frame, scrolling offsets the laid-out rectangles instead of re-measuring, and
  the whole tree draws in two or three batched calls. A list long enough to
  need virtualising has not appeared; the binding page, the longest so far, is
  a few dozen widgets.

## Decisions

Settled at review; the sections above are written to match.

1. **Input: a modal overlay sinks everything.** Not a per-event consumed flag,
   not "only the keys it binds". See §A modal overlay sinks all input.
2. **Settings pages are generated from the node's fields, with an authored
   override.** The field's type picks the editor, so a new `SFFloat` on
   `WalkMode` appears in the settings screen with no UI work and cannot silently
   go missing; a screen wanting better grouping or wording supplies an authored
   `Panel` instead. The cost is one fallback path, which is worth it.
3. **The console is deferred.** It shares only the scrolling viewport with the
   settings work, so it stays at stage 7, after the licence screen has proved
   the scrolling.
4. **Emphasis is a `role` field rendered as text colour; focus is a separate
   additive glow.** `primary`/`secondary`/`danger`, with `primary` doubling as
   the panel's Enter default. Focus and hover are never the same highlight. See
   §Emphasis and focus.
5. **Modals stack; a sub-record is edited by a nested session whose commit
   writes into the enclosing draft, not into the live node.** Only the outermost
   commit saves. Commit copies fields into the existing node rather than swapping
   it, so `USE` sharing and watchers survive. A `capturing` panel suspends every
   UI-level key so a rebinding dialog sees Tab, Enter and the mouse; Escape is
   reserved as the way out and is therefore not bindable. See §A sub-record is
   edited by a nested session and §Modals stack.
6. **`hud.py` is implemented rather than replaced.** Its `flex`, `width`,
   `height` and `left`/`right`/`top`/`bottom` fields are what a Row/Column
   needs and are already declared; a second parallel set with different names
   would be the worse outcome.
