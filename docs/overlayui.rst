Overlay UI
==========

.. rst-class:: introduction

The **overlay UI** draws panels over a live frame and drives them with the
pointer: a settings screen, a key-binding page, a licence notice, a yes/no
question and a console. It is deliberately not a general widget toolkit —
there is no window management, no docking, no rich text — but it is enough to
give a game a screen it can bring up over the running world, and it needs no
artwork to work at all.

Try it: ``oglc-ui-demo`` (add ``--skin`` for the same screens painted with
nine-slice artwork). The keys it binds are printed when it starts.

Screen furniture that must *not* take the input — a reticule, a health bar,
the developer overlay — is a HUD layer rather than a panel, and is drawn
underneath these: see :doc:`HUD & developer overlay <hud>`.

.. _overlayui-quickstart:

Putting a screen on the frame
-----------------------------

A context gains the overlay by mixing in
``OpenGLContext.ui.overlay.OverlayMixin``. Mix it in **ahead of** the
navigation mix-in, so its event routing runs first:

.. code-block:: python

   from OpenGLContext.ui import dialogs, settings
   from OpenGLContext.ui.overlay import OverlayMixin

   class Game(OverlayMixin, GLFWInteractiveContext):
       def OnInit(self):
           self.addEventHandler('keyboard', name='<F10>', state=1,
                                function=self.openSettings)

       def openSettings(self, event):
           settings.open_settings(self)

       def askAboutTextures(self):
           self.pushOverlay(dialogs.confirm(
               'Download the texture pack?',
               detail='About 40MB, cached for next time.',
               yes='Download', no='Not now',
               on_answer=self.texturesAnswered))

Bind a function key on ``keyboard``, not ``keypress``. A ``keypress`` is
character input, and a function key produces no character -- GLFW never raises
one, so a keypress binding for ``<F10>`` is accepted and then silently never
fires. Ordinary letter keys are fine either way. And the handler must be a
bound method of something long-lived: the event system holds callbacks weakly,
so a lambda passed inline is collected the moment the call returns and the key
quietly does nothing.

The mix-in supplies ``pushOverlay(panel)``, ``popOverlay()``, the ``overlays``
stack and the ``renderShaderOverlay`` hook the core-profile render pass calls
once the frame is finished. Nothing else has to be wired up.

**The overlay draws in the shader (core-profile) path only**, which is the
default. A context that has asked for the compatibility profile renders no
overlay.

.. _dialogs:

The ready-made screens
----------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - What it is
   * - ``dialogs.confirm(question, detail, on_answer=...)``
     - A modal yes/no question. ``on_answer`` is called once with True or False;
       Escape answers False. ``danger=True`` marks the affirmative as the destructive
       one.
   * - ``dialogs.message(text, title)``
     - Something to acknowledge, with one button.
   * - ``dialogs.notice(title, text)``
     - A wall of text that scrolls — a copyright or licence notice.
   * - ``settings.open_settings(context)``
     - The rendering settings screen (below).
   * - ``bindings.open_bindings(context)``
     - The key-binding page for the context's declared :doc:`movement modes
       <navigation>`.
   * - ``console.console_panel(registry=...)``
     - A console: scrollback, an input line and a command registry.

Every button is a **measured rectangle**, hovered and clicked with the
pointer; the keys on a dialog are accelerators for people who prefer them, not
the only way in.

.. _menus:

Menus
-----

A screen is what an application shows when it wants an answer. A **menu** is
what it shows when there are more things to do than there is room for buttons:
a bar of titles along the top of the window, a list under each of them, and
the same list at the pointer on a right-click.

.. code-block:: python

   from OpenGLContext.ui.menu import Menu, MenuBar, MenuItem
   from OpenGLContext.ui.widgets import Separator

   bar = MenuBar(menus=[
       ('File', [MenuItem(text='Open', shortcut='<ctrl-o>', on_activate=open_),
                 Separator(),
                 MenuItem(text='Quit', on_activate=quit_)]),
       ('View', [MenuItem(text='Wireframe', checkable=True, on_activate=wire),
                 MenuItem(text='Recent', submenu=[MenuItem(text='a.wrl')])]),
   ], stack=context.overlays)
   context.overlays.push(bar)

A pop-up menu -- under a control, or at the pointer on a right-click -- is one
call. The stack it is pushed on is where its submenus open:

.. code-block:: python

   def showMenu(self, event):
       x, y = event.getPickPoint()
       self.pushOverlay(Menu(anchor=(x, y), items=[
           MenuItem(text='Rename', on_activate=self.rename),
           MenuItem(text='Delete', on_activate=self.delete),
           Separator(),
           MenuItem(text='Move to', submenu=[MenuItem(text=name) for name in folders]),
       ]))

A menu is a ``Panel``, so it already has the focus, the skin, the accelerators
and the Escape that closes a screen. What it adds is where it opens and how it
leaves:

- **It opens where it is asked to.** ``Menu(anchor=(x, y))`` puts its top-left
  corner there, in window pixels, and it moves left to stay on screen. One
  that would run off the bottom opens *upwards*, sitting on ``above`` -- the
  top edge of the control that opened it, so the list does not cover what was
  clicked -- or on the anchor where that is not given. A list with room neither
  way is moved as little as keeps it inside the window. For a right-click menu
  the anchor is the pick point.

- **Choosing runs the item at once and puts the menu away** ``linger`` seconds
  later (0.2 by default), long enough for the chosen row's ripple to be seen;
  nothing more can be chosen meanwhile, and ``linger=0`` puts it away at once.
  Clicking anywhere else puts it away too. That click is spent on dismissing
  the menu and does not also press what was behind it.

- **The row under the pointer is lit, and the keyboard is on it**, so Up and
  Down carry on from wherever the pointer left off. Enter chooses, Escape
  leaves. A ``shortcut`` runs its item from anywhere in the menu and is drawn
  on the right of the row, which is how the reader learns it.

- **Every row has a letter that runs it**, underlined in its text: the first
  letter of one of its words where no other row has it, and otherwise the first
  of its letters that is free. ``MenuItem(mnemonic='p')`` names the letter where
  the one given will not do, and ``Menu(mnemonics=False)`` gives a menu none.

- ``checkable`` makes an item a setting rather than an action: it draws its
  state and flips it when chosen.

- ``submenu`` makes it a way in. It opens another menu beside itself; choosing
  something in *that* closes the whole chain.

A ``MenuBar`` is **not modal and not a wall**: a click that misses it is
offered to whatever is under it, so the world carries on being usable while
the bar is on screen. It lives at the bottom of the overlay stack — push it
once and leave it — and the menus it opens go above it, where they are modal
and take everything until one is chosen.

.. rst-class:: technical

Both are in ``OpenGLContext/ui/menu.py``. An editor built on them wants
:doc:`the editor toolkit <editing>` as well: tool modes, a plan view, and the
point under the cursor.

.. _overlayui-settings:

The settings screen
-------------------

Most of what the renderer does is decided for the player and is invisible:
shadows on, image-based lighting probed for and degraded on a weak GPU,
geometry batched, detail dropped with distance. Each of those is now a field
on the ``ContextDefinition``, and the settings screen offers all of them:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Type / range
     - What it does
     - Environment default
   * - ``shadows``
     - bool
     - Shadow maps. The most expensive feature, and the first thing to turn off on a
       weak GPU.
     - ``OPENGLCONTEXT_SHADOWS``
   * - ``shadowsSoft``
     - bool
     - PCSS contact-hardening shadows: softer and dearer.
     - ``OPENGLCONTEXT_SHADOWS_SOFT``
   * - ``shadowCascades``
     - int, 0–4
     - Cascades for a directional light. 0 lets the pass choose from VRAM and frame
       rate; a fixed value makes shadow output reproducible.
     - ``OPENGLCONTEXT_SHADOW_CASCADES``
   * - ``maximumLights``
     - int, 0–8
     - Lights bound in one frame. The shader's own ceiling still applies.
     - —
   * - ``bloom``
     - bool
     - HDR bloom post-process.
     - ``OPENGLCONTEXT_BLOOM``
   * - ``ibl``
     - ``auto``/``full``/``analytic``/``off``
     - Image-based lighting. ``auto`` degrades itself on a software rasteriser, where
       the prefilter precompute is too slow.
     - ``OPENGLCONTEXT_IBL``
   * - ``iblIntensity``
     - float, 0–2
     - Scales the un-shadowed ambient/environment term.
     - ``OPENGLCONTEXT_IBL_INTENSITY``
   * - ``transmission``
     - ``auto``/``full``/``blend``/``off``
     - Refraction through glass.
     - ``OPENGLCONTEXT_TRANSMISSION``
   * - ``waterReflection``
     - bool
     - Water reflects the scene around it; costs a second opaque draw at a
       quarter of the pixels in a frame with water in view.
     - ``OPENGLCONTEXT_WATER_REFLECTION``
   * - ``instancing``
     - bool
     - Collapse shapes sharing a geometry into one instanced draw.
     - ``OPENGLCONTEXT_INSTANCING``
   * - ``gpuSkinning``
     - bool
     - Skin a rigged figure in the vertex shader rather than on the processor. Off is
       the reference the shader path is measured against.
     - ``OPENGLCONTEXT_GPU_SKINNING``
   * - ``tessellationLOD``
     - bool
     - Distance level of detail for procedural geometry. Off gives deterministic
       tessellation.
     - ``OPENGLCONTEXT_LOD``
   * - ``vsync``
     - bool
     - Wait for the display's refresh before presenting.
     - ``OPENGLCONTEXT_NO_VSYNC`` (inverted)
   * - ``uiScale``
     - float, 0.75–2
     - How large the overlay is drawn, *on top of* the size the window's height
       already asks for. See :ref:`Everything scales with the window <scale>`.
     - ``OPENGLCONTEXT_UI_SCALE``
   * - ``fullscreen``
     - bool
     - Fill the screen rather than open a window of the definition's ``size``.
       Applying it moves the window a player is already looking at, keeping the GL
       context and everything loaded into it. Ignored while ``OPENGLCONTEXT_HIDDEN``
       is set.
     - ``OPENGLCONTEXT_FULLSCREEN``

**The environment variable is the field's default, not a competitor.** A field
nobody has set reads its environment variable every time the pass asks, so a
shell variable still pins a feature for a script or a CI run; writing the
field — which is what the settings screen does — takes precedence from then
on. Passes read through ``OpenGLContext.renderoptions`` rather than the
environment directly.

.. code-block:: python

   from OpenGLContext.contextdefinition import ContextDefinition
   definition = ContextDefinition(shadows=False, maximumLights=2, ibl='analytic')

The page is **generated from the node's fields**
(``OpenGLContext.ui.generate``), so a new setting appears on the screen with
no UI work and cannot silently go missing. A node class says how its fields
should be presented by declaring ``UI_HINTS`` beside them:

.. code-block:: python

   class WalkMode(_GroundMode):
       walkSpeed = field.newField('walkSpeed', 'SFFloat', 1, 3.0)
       UI_HINTS = {
           'walkSpeed': {'label': 'Walking speed', 'minimum': 0.5,
                         'maximum': 20.0, 'step': 0.5, 'suffix': ' m/s'},
       }

The field's type picks the editor: ``SFBool`` a toggle, a number with a range
a slider (without one a *number field* — a slider over an invented 0–1 is a
wrong answer rather than a missing one), an ``SFString`` with ``options`` a
cycling select, ``MFString`` with ``{'editor': 'keys'}`` a key capture. A
screen wanting better grouping supplies an authored panel instead.

A ``NumberField`` rather than a plain text field, because a number on its way
in is not a number yet: ``''``, ``'-'`` and ``'3.'`` are all positions the
caret passes through, and each of them written to an ``SFFloat`` would either
raise or store something nobody asked for. The text being typed is held by the
widget and only a complete number reaches the node; a character that could not
begin one is refused rather than shown and then dropped.

A hint names a field that a section actually shows — a test holds them to it,
so a hint cannot outlive the control it describes. The window's profile and
title are settled when the context is made and cannot be changed for a running
one, so neither is offered.

What happens to the player's changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Apply writes the draft into the live definition and then tells whoever opened
the screen, which is where **what to do with the settings** is decided —
writing them to a file, sending them to a server, or nothing at all:

.. code-block:: python

   def saveSettings(session):
       changed = session.changed_fields()        # only what the player moved
       with open(profilePath, 'w') as output:
           json.dump({name: str(getattr(session.draft, name)) for name in changed},
                     output)

   settings.open_settings(context, on_apply=saveSettings)

``changed_fields()`` is measured against the values the screen opened with, so
it is still the right answer after the commit. Saving only those keeps the
player's choices without also freezing every default the game ships — a later
build can change a default and the player's file will not quietly override it.

A context may instead define ``settingsChanged()``, which is called whether or
not an ``on_apply`` was given, and is where the few options set once on the
window — the swap interval, the buffer format — are re-applied. A changed
profile or buffer format takes effect on the next context, and nothing
pretends otherwise.

.. _scale:

Everything scales with the window
---------------------------------

A screen laid out in fixed pixels is comfortable at one resolution and
unusable at the next: at 4K a 16-pixel font is a smudge and a checkbox is too
small to hit. So **one number drives the whole interface**.

- The window's height picks a font size (``ui.metrics.font_size_for``): the
  reference is a 16-pixel atlas in a 1080-line window, and a 2160-line window
  gets twice that. Smaller windows stay at the reference — text scaled *down*
  for a 720p display is unreadable rather than merely small. The answer is
  always one of the nine atlases that exist, so dragging a window edge cannot
  build a new atlas per pixel, and the largest of them is the ceiling.

- ``uiScale`` multiplies that, for eyesight and viewing distance rather than for
  resolution. It is on the settings screen under *Interface*, and applying it
  re-lays the panels out at once.

- The font that comes back carries a ``scale``, and **every pixel measurement
  goes through it**: the skin's paddings and switch sizes (``Skin.scaled``), a
  widget's margins and ``maximumWidth``, a box's spacing and padding, a grid's
  row padding. A skin is authored once, at the reference size.

Two things are deliberately *not* in pixels. A button's horizontal padding is
in characters, because the text already carries the size; and a panel's
``preferredColumns`` is in characters, which is what makes it a maximum width
that holds at every scale:

.. code-block:: python

   Panel(fill=True, preferredColumns=78, ...)   # full height, at most 78 columns wide

``fill`` means full *height*; the width is capped by ``preferredColumns`` and
the panel is centred in what is left. That is what keeps the settings screen a
readable column on a 4K display instead of a page with a label at one edge and
its control at the other.

A game drawing its own HUD into the overlay's renderer should ask the context
for the size rather than pinning one, since there is one renderer per context
and asking it for a second size every frame rebuilds its atlas every frame:

.. code-block:: python

   renderer = OverlayRenderer.forContext(self, self.overlayFontSize())
   margin = renderer.metrics.pixels(12)          # 12 at the reference size

.. _sessions:

Cancel is real, at every level
------------------------------

Widgets edit a **copy** of the node (``OpenGLContext.ui.session``). Nothing
reaches the live settings until Apply:

.. code-block:: python

   session = SettingsSession(context.contextDefinition)
   session.draft            # a copy; every widget binds to this
   session.dirty            # whether the draft differs from the target
   session.commit()         # copy the draft's fields back, field by field
   session.revert()         # throw the draft away

A sub-record — a movement mode opened from the main page — is edited by a
**nested session** over a copy of the parent's draft. Its Apply writes into
that draft, and only the outermost ``commit()`` reaches the real node. Cancel
the movement page and the walk speed is unchanged; cancel the settings screen
after applying that page and it is *still* unchanged.

Commit copies fields into the existing node and never swaps it, so a
sub-record ``USE``\ d in two places keeps its identity and everything already
watching a field is notified normally.

.. _overlayui-input:

Input: a modal overlay is a lid
-------------------------------

**While a modal panel is up, nothing below it hears anything** — not the
events the panel handles, and not the ones it ignores; not the world, and not
a parent panel. It is not a filter that passes what it does not want.

**Panels that are not lids are layers.** An event is offered to the panels
topmost first, down to and including the first modal one, and stops at
whichever takes it. So an application can have a menu bar along the top *and*
a tool palette down the side and each gets a look at what the other left,
rather than only the one that happened to be pushed last. The pointer's
*position* is offered to every layer whatever they do with it, because hover
is not something one layer takes from another: a pointer leaving the bar for
the strip has to stop the bar drawing itself hovered.

That has consequences the mix-in carries for you:

- The input sampler (``InputState``) is not fed while a modal overlay is up, and
  is cleared when one opens and when the last one closes. Without that, a key
  the overlay consumed would stay recorded as held and the player would walk
  into a wall while typing.

- The pointer is handed back (``ViewPlatformMixin.suspendPointerCapture``), so a
  mouse-look mode's grabbed pointer does not fight the pointer needed to click
  with. **Its motion stops steering the view too**: a backend reports cursor
  motion straight to the sampler rather than through the event queue, so gating
  the event queue does not reach it, and without that the world keeps turning
  under the dialog the player is reading. The position is still tracked, so the
  journey across the dialog is not delivered as one flick when the pointer is
  handed back.

- Mouse-move events are kept alive while an overlay is up, so hover works even
  in a scene with no move handlers of its own.

- **A wheel notch is a press and release of a button no physical mouse has** —
  ``WHEEL_UP`` (3) and ``WHEEL_DOWN`` (4) in
  ``OpenGLContext.events.mouseevents``, the X11 numbering. Each backend
  translates to that spelling: GLUT and pygame are told in those buttons
  already, while GLFW reports scrolling on a callback of its own, in offsets. A
  notch goes to the widget under the pointer and then up through its parents, so
  a wheel over a page that has nothing left to scroll reaches whatever encloses
  it that has. See :ref:`the wheel <wheel>`.

- **A press the overlay took takes its release with it**, whether or not an
  overlay is still up by the time the release arrives. Without that ledger the
  last panel on the stack is a trap: Escape's key-*down* closes it, the stack
  empties, and the key-*up* lands on the world's own Escape handler, which in
  every OpenGLContext application quits it. The same goes for the click that
  dismisses a dialog, whose release would otherwise pick whatever was behind it.

- **The world is told to let go of what it was holding** the moment a panel
  takes the input. The real release never reaches it — the panel has the
  keyboard — and an application that tracks held keys itself, as a movement mode
  and a game's steering both do, has no other way to learn the key came up. Left
  alone that is a throttle stuck open and a wheel stuck at full lock behind the
  menu that stopped them being let go of. Clearing ``InputState`` covers the
  sampler; ``letGoOfHeldInput()`` covers everyone else, by sending a key-*up*
  for each held key, in the only language an input handler speaks. The keystroke
  that *opened* the panel is not among them, for the Escape reason above. It is
  the same idea as ``clearHeldKeys()``, which does it for a window that loses
  focus mid-key.

A panel may also declare itself ``capturing``: while one is up the overlay
runs no accelerators, no Tab traversal and no Enter default, so a rebinding
dialog sees Tab, Enter and the mouse buttons verbatim. **Escape is reserved**
as the way out and is therefore the one key that cannot be bound.

Press and release are distinct: a button arms on press over itself and fires
on release over itself, so dragging off it cancels. Hover lights the frame;
**focus is a separate ring drawn outside the widget** — a solid border and an
additive glow, because either alone disappears over a world the panel does not
control — shown for keyboard focus and text entry but not for an ordinary
click. On a generated settings page the whole row the pointer is on or the
keyboard is in is washed as well, so a row is one target rather than two
things that happen to be side by side.

.. _wheel:

The wheel
---------

A notch scrolls by ``ui.scroll.WHEEL_LINES`` lines of the font the content is
drawn in, so it moves the same amount of text at every interface scale, and a
notch nothing uses is passed on rather than swallowed: a wheel over a list
already at its end reaches the page that encloses it.

**A control takes the wheel only while it has focus.** A slider or a select
adjusts on a notch the way it does on an arrow key, and for the same reason —
but only when the keyboard would reach it too. A settings page is mostly
controls and the wheel is how it is read; one that took every notch crossing
it would turn reading the page into editing it, wherever the pointer happened
to rest. Unfocused, the notch passes on to the viewport and scrolls. Override
``Widget.wheelAdjusts`` to choose differently for a widget of your own.

Two things about a notch differ from a click, and both are why a wheel that is
nearly working scrolls nothing at all.

- **A notch is an increment, not a state.** Pending pick events are held in a
  mapping (``Context.addPickEvent``) so that asking the same question twice in
  one frame costs one answer — right for a click or a movement, where
  where-the-pointer-is-now is the whole of the news, and wrong for the wheel,
  where each notch is another line. An event says which of the two it is through
  ``Event.getPickKey``, and the wheel's is distinct per notch, so a flick that
  lands three notches in one frame scrolls three.

- **Scrolling arrives in fractions, and a wheel's click is not always 1.0.** A
  touchpad reports a stream of parts of a notch; those are summed, the remainder
  kept for the next report and dropped when the direction reverses, so a slow
  drag still scrolls and a jitter over the pad does not scroll backwards. A
  *wheel* reports a whole click at a time — but in whatever units the platform
  measures one in: X11 says 1.0 and GLFW's Wayland backend says **1.5**, because
  it divides the protocol's 15.0 by ten. GLFW offers no count of detents, so the
  size of a click is *learned*: a report that is not a whole number of the click
  we assumed is itself the evidence that the assumption was wrong, and is one
  click of a smaller size. Taking 1.0 for granted made every other click of such
  a wheel scroll twice — 1.5 is one notch with half of one carried, and the next
  1.5 makes 2.0 and fires two.

**When a notch appears to count twice, look at what arrived.** Backends and
compositors disagree about how a wheel reaches an application — a Wayland
compositor may report one physical detent both as a legacy axis and as a
discrete one — and a detent delivered twice is indistinguishable from a quick
flick of the wheel unless the offsets themselves can be seen. Set
``OPENGLCONTEXT_DEBUG_WHEEL=1`` and every scroll callback says what it was
given, what it is carrying and how many notches it made of it:

.. code-block:: bash

   OPENGLCONTEXT_DEBUG_WHEEL=1 twig-bb some-map.bsp
   INFO wheel: reported +1.0000, carrying +0.0000, sending 1 notch(es)

Two lines for one movement of the finger say the wheel is being reported
twice; one line saying ``2 notch(es)`` says the offset itself arrived doubled.
They want different answers, which is why the diagnostic prints both halves.

.. _overlayui-bindings:

Key bindings
------------

**A mouse button is an input with a name, like a key.** Held buttons go
through the same sampler held keys do, under a name in the same vocabulary
(``<mouse-0>``, from ``mouseevents.button_name``), so a binding can list one,
a movement mode can read one and this page can show one — as “Left mouse”,
because the raw spelling tells a player nothing. That is what lets a
first-person game put its trigger where every player expects it. A click the
overlay takes never reaches the sampler, so clicking a button on a screen does
not also fire what is behind it.

The binding page lists every command of every declared movement mode. Clicking
a row opens a capturing dialog; capture a key already bound in the *same* mode
and a confirmation is raised over that dialog asking whether to steal it. (The
same key in another mode is not a conflict — walking and flying are never in
force at the same moment.)

**The page saves when it is left with Save.** A capture takes effect
immediately — a mode resolves a command to keys when it samples, so a new
binding can be tried without leaving the screen — but the file is written only
by Save. Cancel and Escape put every binding back as the page found it, a
Reset included. Writing on every captured key would put a save between the
player and every keystroke, and leave no way back from a mis-hit.

Bindings are saved as JSON in the per-user app-data directory
(``keybindings.json``) by ``OpenGLContext.move.bindingstore``. The file is
replaced whole rather than truncated and rewritten, so an interrupted save
cannot leave a file that will not parse.

Loading is forgiving in both directions, because this is a file people edit by
hand: a mode or command this build no longer has is skipped, and so is a value
of the wrong shape. ``"keys": "wasd"`` is refused with a warning rather than
read as four separate bindings, and a modifier this build does not know is
dropped rather than left to make the binding permanently unreachable.

.. code-block:: python

   from OpenGLContext.move import bindingstore
   bindingstore.load_bindings(context.getNavigation())     # at start-up
   bindingstore.save_bindings(context.getNavigation())     # what Save does

.. _console:

The console
-----------

.. code-block:: python

   from OpenGLContext.ui import console

   registry = console.CommandRegistry()
   registry.add('fps', lambda panel: '%.1f' % context.frameCounter.recentFps(),
                'the recent frame rate')
   panel = console.console_panel(registry=registry)
   console.ConsoleLogHandler(panel)          # attaches itself to 'OpenGLContext'
   context.pushOverlay(panel)

Commands are called as ``function(panel, *words)`` and return the text to
print. ``help`` and ``clear`` are built in. The logging handler is the point
of it: engine warnings otherwise go somewhere a player cannot see. Scrollback
is bounded (500 lines by default) and the arrow keys walk the command history.

The handler adds itself to the logger and takes itself off again when the
console closes, and holds the panel weakly. A handler outlives what it writes
to — the logging framework keeps it for the life of the process — so a game
that opens and closes several consoles over a session would otherwise keep
every one of them, with its whole widget tree, alive. Pass ``logger=`` to
attach it somewhere other than ``OpenGLContext``.

**New output follows the end only for a reader who is at the end.** Scroll up
to read an earlier traceback and the lines the engine is still logging leave
the view where you put it; scroll to the bottom again and it resumes
following.

.. _overlayui-skinning:

Skinning
--------

A ``Skin`` node holds every colour and inset the widgets use, plus an optional
``NineSlice`` image per widget state. The default skin is flat translucent
rectangles and needs no artwork at all, which matters for a viewer that is not
a game. Its sizes are **pixels at the reference font size** and are multiplied
by the interface scale before anything is measured against them, so a skin is
authored once and works at every resolution (see :ref:`Everything scales with
the window <scale>`).

.. code-block:: python

   from OpenGLContext.ui.skin import NineSlice, Skin

   panel.skin = Skin(
       buttonImage=NineSlice(url=['art/button.png'], border=(8, 8, 8, 8)),
       buttonHoverImage=NineSlice(url=['art/button_hover.png'], border=(8, 8, 8, 8)),
       panelPadding=20.0,
   )

``border`` is how many pixels of the source are corner, in the order left,
top, right, bottom: those four squares are drawn at their own size, the edges
stretch along one axis and the centre along both. Without that one button
image cannot serve two button widths. Any image left unset falls back to the
flat fill, so a game can skin the buttons and leave the rest; an image that
will not load logs a warning and falls back rather than taking the frame down.

**Emphasis is a role, not a colour.** A button carries ``role`` — ``primary``,
``secondary`` or ``danger`` — which the skin renders as text colour. The
``primary`` button is also the panel's Enter default; ``danger`` marks the
actions a settings screen must not let someone hit by accident.

**A control shows the pointer it can be used.** While the pointer rests on an
enabled control, ``hoverWash`` is drawn over it; a button, whose fill already
changes, and a menu row, which draws ``menuHighlight``, do without. A press
spreads a ripple of ``rippleFill`` across the control from where the pointer
went down, clipped to it, fading as it grows over ``RIPPLE_SECONDS`` (0.45 s,
in ``OpenGLContext.ui.widgets``). A control run from the keyboard, by an
accelerator or by a menu's letter ripples from its middle. The window draws
frames for as long as a ripple is running, and a capture's fixed clock times
it like everything else. A widget class opts out with ``hoverWash = False`` or
``ripples = False``: a slider, a text field, a scrolling viewport and a view's
splitter do not ripple.

**Round shapes need no artwork.** A boolean is drawn as a sliding switch, not
a check box, because the state is then the shape: a knob at one end or the
other on a track that changes colour reads at a glance, while a tick inside a
box has to be looked at. The track's ends and the knob come from one
antialiased disc the renderer generates at start-up, so they stay smooth at
any interface scale and cost nothing to ship. A game that would rather draw
its own supplies ``switchOnImage``, ``switchOffImage`` and
``switchKnobImage``.

.. _overlayui-authoring:

Authoring a screen
------------------

Every widget is a scenegraph node, so a screen can be built in code or parsed
from a file and its parts ``DEF``/``USE``\ d like anything else:

.. code-block:: python

   from OpenGLContext.ui.layout import Column, Row
   from OpenGLContext.ui.panel import Panel
   from OpenGLContext.ui.widgets import Button, Label, Slider, Spacer, Toggle, PRIMARY

   panel = Panel(title='Movement', modal=True, preferredColumns=48, children=[
       Column(spacing=6, children=[
           Label(text='How the character moves.', wrap=True),
           Row(children=[Label(text='Walk speed', flex=1),
                         Slider(target=walk, fieldName='walkSpeed',
                                minimum=1, maximum=10, step=0.5)]),
           Toggle(text='Invert look', target=fps, fieldName='invertLook'),
           Row(spacing=8, children=[Spacer(),
                                    Button(text='Cancel', name='cancel'),
                                    Button(text='Apply', role=PRIMARY, name='apply')]),
       ])])

Layout is one top-down pass with no constraint solver. A widget reports the
size it wants; a box gives fixed children their natural size and divides what
is left among the ``flex`` children; a ``Grid`` lines a column of labels up
across unrelated rows. Sizes are pixels and the origin is the bottom-left of
the window — the same origin a mouse event's pick point arrives in. Layout
runs when something changes, not every frame.

The layout fields live on ``OpenGLContext.hud.GUINode``:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - What it does
   * - ``width``, ``height``
     - An explicit size; 0 means "measure me".
   * - ``flex``
     - Share of the leftover main-axis space; 0 keeps the natural size.
   * - ``left``, ``right``, ``top``, ``bottom``
     - Margin outside the widget.
   * - ``maximumWidth``
     - A ceiling on the width whatever rectangle is offered; 0 for none. What stops a
       control running the width of a 4K display.
   * - ``alignSelf``
     - ``stretch`` (take it all), ``start``, ``center`` or ``end``. Anything but
       ``stretch`` also shrinks the widget to its measured width, which is how a
       switch ends up against the right margin rather than adrift in the middle of a
       wide column.

A ``Panel`` adds ``preferredColumns``, a content width in characters, which is
both what keeps a dialog holding one long sentence a readable column and the
panel's maximum width.

A generated settings page uses ``Grid``'s row treatment: ``rowPadding`` gives
each row room above and below (a bigger target as well as air), a hairline is
drawn in the gap between one row and the next, and the active row is washed.
The two columns share the width evenly, so controls line up down the page
instead of stepping in and out with the labels.

.. _overlayui-modules:

Where things are
----------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - What is in it
   * - ``ui.geometry``, ``ui.metrics``
     - Rectangles, and measuring/wrapping text.
   * - ``hud``
     - The layout protocol and the box.
   * - ``ui.layout``
     - Row, Column, Grid.
   * - ``ui.widgets``
     - Label, Button, Toggle, Select, Slider, ProgressBar, TextField, NumberField,
       KeyCapture.
   * - ``ProgressBar``
     - How far something has got — a download, a bake, a world streaming in. **Not a
       disabled slider**: a ``Slider`` is a control, taking focus and input, and its
       value is the user's; a ``ProgressBar`` reports, takes no focus, and its value
       is somebody else's news. ``fraction`` is held between 0 and 1 rather than
       validated, since it comes from a job measuring itself and a bar is not the
       place to raise about arithmetic elsewhere; ``text`` is drawn over it, because
       "Ashdown — 40%" says more than a bar alone and a bar alone says more than a
       number.
   * - ``ui.scroll``
     - The clipping viewport and its bar.
   * - ``ui.panel``
     - One screen: focus, accelerators, modality, commands. Walked with Tab/Shift-Tab
       or the up/down arrows, and the focused item is pressed with Space or Return;
       Return with nothing focused presses the primary action, and Escape leaves a
       screen that can be left. Left and right are left to whatever is focused, since
       a ``Select``, a ``Slider`` and a ``Carousel`` all use them.
   * - ``ui.overlay``
     - The stack and the context mix-in.
   * - ``ui.toolpalette``
     - A strip of tools down one side, bound to an :doc:`editor's <editing>`
       ``ToolManager``: one button per tool, the one in force lit, and a click puts
       the pointer into it.
   * - ``ui.screen``, ``ui.hudwidgets``, ``ui.debugoverlay``
     - The :doc:`HUD layers <hud>` drawn under these panels, and the developer
       overlay.
   * - ``ui.draw``
     - The GL renderer: one program, one batched vertex buffer.
   * - ``ui.gallery``
     - ``Carousel`` and ``Picture``: choosing by what a thing looks like rather than
       by its name. An arrow *looks* and a picture *chooses*, so a caller may open
       what was chosen without opening something every time somebody presses an
       arrow.
   * - ``ui.pictures``
     - The picture cache behind both: fetches an http(s) URL through the hardened
       resolver, decodes on a worker thread, uploads a couple per frame on the render
       thread, and evicts the least recently used once a texel budget is reached. A
       gallery of several hundred entries therefore costs a bounded amount of card
       memory and never decodes inside a draw call. See :ref:`how long a picture is
       kept <picture-lifetime>`.
   * - ``ui.skin``
     - Colours, insets and nine-slice art.
   * - ``ui.session``
     - Editing on a copy.
   * - ``ui.generate``
     - A page from a node's fields.
   * - ``ui.dialogs``, ``ui.settings``, ``ui.bindings``, ``ui.console``
     - The ready-made screens.
   * - ``renderoptions``
     - How a pass reads a rendering feature's setting.

The design and its reasoning are in ``plans/OVERLAY-UI.md``.

.. _picture-lifetime:

How long a picture is kept
--------------------------

Two caches sit behind a gallery, and they have very different lifetimes.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Cache
     - Holds
     - Released
   * - On disk (the resolver's)
     - The downloaded file, for an ``http(s)`` picture
     - Never, by the overlay. A picture is fetched once ever, not once a session.
   * - On the card (``ui.pictures``)
     - The decoded RGBA texture
     - When the least recently used is pushed past the texel budget, and when the
       **last panel closes**.

The second of those matters more than it looks. Eviction only runs while
pictures are *arriving*, so once the panel that was browsing them has gone
there is nothing left to trigger it: without the close, a library browsed to
the budget would hold up to ``DEFAULT_BUDGET``\  = 64M texels — 256 MB at
RGBA8 — for the rest of the session, with no interface on screen to show for
it.

So closing the last panel calls ``releaseOverlayPictures()``, which drops
every texture. Reopening decodes from the file again, which for a local file
or an already-downloaded one is a disk read rather than a fetch. The worker
pool stays up, so the decode is still off the render thread and the first
frame back is not a stutter; this is what separates it from
``PictureCache.close()``, which stops the workers and belongs to context
teardown.

Moving *between* screens keeps everything: the release happens on the
transition to nothing-on-screen, not on each panel. A dialog opened over the
gallery and dismissed again leaves the gallery's pictures where they were.

A caller that wants a different bound sets ``renderer.pictures.budget`` (in
texels); one that wants the textures back sooner may call
``releaseOverlayPictures()`` itself, and the cache is usable immediately
afterwards.

.. _picture-formats:

Pictures in a format the imaging library cannot read
----------------------------------------------------

Pictures are decoded with the Python Imaging Library, which covers PNG, JPEG,
TGA, WebP and the rest of what a toolkit's own artwork is drawn in. An
application whose content is in something else — a block-compressed game
texture container, say — registers a decoder for the suffix:

.. code-block:: python

   from OpenGLContext.ui import pictures

   pictures.registerDecoder('.crn', my_module.load)

The decoder is handed a filesystem path and returns a PIL image, or ``None``
where it declines the file — an optional dependency it needs being absent,
say. Declining is not an error: the picture is simply not drawn, and a gallery
shows its plate, which is what an unreadable picture has always done. A
decoder that raises costs that one picture and is counted in
``PictureCache.failures``.

Every picture path in the toolkit goes through this, so a skin, a gallery and
a thumbnail all gain the format at once. Registering a suffix the imaging
library already reads overrides it, which is deliberate: an application with a
faster or more permissive reader for a format should be able to say so.

The registry is empty by default. An entry in it is an application saying it
has content the imaging library cannot read — it is not a layer over the
ordinary case, which still goes straight to PIL.

What the pointer is told
------------------------

A control says what it is by what the pointer does over it. Two things say it,
and a widget declares both:

.. code-block:: python

   class Splitter(Widget):
       cursor = 'resize-x'
       tooltip = 'Drag to move the line between the views'

``cursor`` is one of ``OpenGLContext.context.CURSORS`` -- ``arrow``, ``hand``,
``text``, ``crosshair``, ``resize-x``, ``resize-y``, ``resize`` and ``no`` --
and the overlay asks the context for it as the pointer crosses the window,
setting it when it changes rather than on every movement. Every backend
answers in those words: GLFW, GLUT, pygame, Tk, wx and Qt each map them to
their own. **A shape a platform has not got is answered rather than
approximated** -- ``setPointerShape`` returns False -- because a window that
cannot say "this drags" is better than one that says it with the wrong
picture, and a caller that is told can say it another way. A minimal Wayland
cursor theme carries the arrow and the text bar and nothing else, which is why
the view splitters also draw a grip.

``tooltip`` is one line, shown where the pointer comes to rest on the control
for ``OpenGLContext.ui.tooltip.TOOLTIP_PAUSE`` seconds. It is drawn over the
panels rather than pushed on the stack, so it takes no events and changes
nothing about modality; a pointer that is only crossing the window shows
nothing, because the pause restarts with each movement.

Every interactive control also answers the pointer on its own, with nothing
declared: a wash while the pointer rests on it and a ripple when it is used
(see :ref:`Skinning <overlayui-skinning>`).

