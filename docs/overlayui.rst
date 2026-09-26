Overlay UI
==========

.. rst-class:: introduction

The **overlay UI** draws panels over the running scene and operates them with
the pointer and keyboard: a settings screen, a key-binding page, a licence
notice, a yes/no question, a menu bar and a console. It is a set of screens
for a game or viewer, not a general widget toolkit: it has no window
management, no docking and no rich text. It needs no artwork.

To see it, run ``oglc-ui-demo``. Add ``--skin`` to see the same screens drawn
with nine-slice artwork. The demo prints its key bindings when it starts.

Screen elements that must not take input, such as a reticule, a health bar
or the developer overlay, are HUD layers rather than panels. They are drawn
under the panels; see :doc:`HUD & developer overlay <hud>`.

.. _overlayui-quickstart:

Adding the overlay to a context
-------------------------------

Mix ``OpenGLContext.ui.overlay.OverlayMixin`` into the context. Put it
**ahead of** the navigation mix-in in the bases, so that its event routing
runs first:

.. code-block:: python

   from OpenGLContext.ui import dialogs, settings
   from OpenGLContext.ui.overlay import OverlayMixin

   class Game(OverlayMixin, Context):
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

The mix-in provides ``pushOverlay(panel)``, ``popOverlay()``, the
``overlays`` stack, and the ``renderShaderOverlay`` hook that the
core-profile render pass calls when the frame is finished. Nothing else needs
to be connected.

Two rules for the key binding:

- Bind a function key on ``keyboard``, not ``keypress``. A ``keypress`` is
  character input, and a function key produces no character. GLFW never
  sends a ``keypress`` for one, so a ``keypress`` binding for ``<F10>`` is
  accepted and never fires. Letter keys work with either.
- Pass a bound method of a long-lived object. The event system holds
  callbacks weakly, so a ``lambda`` passed inline is collected when the call
  returns, and the key does nothing. See :doc:`eventmodel`.

The overlay is drawn only in the shader (core-profile) path, which is the
default. A context that uses the compatibility profile draws no overlay.

.. _dialogs:

Ready-made screens
------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - Screen
   * - ``dialogs.confirm(question, detail, on_answer=...)``
     - A modal yes/no question. ``on_answer`` is called once with True or False;
       Escape answers False. ``danger=True`` marks the yes button as the
       destructive action.
   * - ``dialogs.message(text, title)``
     - A message with one button to acknowledge it.
   * - ``dialogs.notice(title, text)``
     - A long scrolling text, such as a copyright or licence notice.
   * - ``settings.open_settings(context)``
     - The rendering settings screen; see :ref:`overlayui-settings`.
   * - ``bindings.open_bindings(context)``
     - The key-binding page for the context's :doc:`movement modes
       <navigation>`; see :ref:`overlayui-bindings`.
   * - ``console.console_panel(registry=...)``
     - A console with scrollback, an input line and a command registry; see
       :ref:`console`.
   * - ``contentscreen.ContentScreen(packs, on_fetch=..., wanted=...)``
     - Content packs on offer, each with the size of the whole set it
       fetches and its terms, a Download and a Stop button, and a progress
       bar whose text says how far a download is, or that it failed (and
       why) or was stopped. ``screen.panel`` is the panel to push; call
       ``screen.poll()`` once a frame. ``together=True`` offers every pack as
       one set, for a first run's base packs. See :doc:`contentpacks`.

Every button can be clicked with the pointer. The keys on a dialog are
accelerators, not the only way to use it.

.. _menus:

Menus
-----

Use a **menu** when there are more actions than there is room for buttons.
A ``MenuBar`` is a row of titles along the top of the window, each opening a
list. A ``Menu`` is one list, opened under a control or at the pointer on a
right-click.

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

A pop-up menu is one call. Its submenus open on the stack it is pushed on:

.. code-block:: python

   def showMenu(self, event):
       x, y = event.getPickPoint()
       self.pushOverlay(Menu(anchor=(x, y), items=[
           MenuItem(text='Rename', on_activate=self.rename),
           MenuItem(text='Delete', on_activate=self.delete),
           Separator(),
           MenuItem(text='Move to', submenu=[MenuItem(text=name) for name in folders]),
       ]))

A menu is a ``Panel``, so it has focus handling, the skin, accelerators, and
Escape to close it. In addition:

- Placement - ``Menu(anchor=(x, y))`` puts the menu's top-left corner at
  that point, in window pixels, and moves it left if needed to stay on
  screen. A menu that would run off the bottom opens upwards, from
  ``above`` (the top edge of the control that opened it, so the list does not
  cover that control) or from the anchor if ``above`` is not given. A menu
  with no room either way is moved as little as needed to fit in the window.
  For a right-click menu, pass the pick point as the anchor.
- Choosing - choosing an item runs it at once, and the menu closes
  ``linger`` seconds later (0.2 by default), so the chosen row's ripple can
  be seen. Nothing else can be chosen in that time. ``linger=0`` closes it at
  once. A click anywhere else also closes the menu, and that click does not
  also press what is behind the menu.
- Keyboard - the row under the pointer is highlighted and has keyboard
  focus, so Up and Down move on from where the pointer was. Enter chooses and
  Escape closes. An item's ``shortcut`` runs it from anywhere in the menu and
  is shown on the right of its row.
- Mnemonics - every row has a letter that runs it, underlined in its text.
  It is the first letter of one of its words that no other row uses, or
  otherwise the first of its letters that is free.
  ``MenuItem(mnemonic='p')`` sets the letter, and ``Menu(mnemonics=False)``
  turns mnemonics off for a menu.
- ``checkable`` makes an item a setting rather than an action: it shows its
  state and toggles it when chosen.
- ``submenu`` makes an item open another menu beside it. Choosing an item in
  a submenu closes the whole chain.

A ``MenuBar`` is not modal and does not block input. A click that misses it
goes to whatever is under it, so the scene can still be used while the bar
is shown. Push the bar once, at the bottom of the overlay stack, and leave it
there. The menus it opens go above it; they are modal and take all input
until an item is chosen or the menu is closed.

.. rst-class:: technical

Both classes are in ``OpenGLContext/ui/menu.py``. For an editor, see also
:doc:`the editor toolkit <editing>`: tool modes, a plan view, and the point
under the cursor.

.. _overlayui-settings:

The settings screen
-------------------

``settings.open_settings(context)`` shows the rendering settings. Each is a
field on the ``ContextDefinition``, and the screen shows all of them:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Type / range
     - What it does
     - Environment default
   * - ``shadows``
     - bool
     - Shadow maps. The most expensive feature, and the first to turn off on a
       slow GPU.
     - ``OPENGLCONTEXT_SHADOWS``
   * - ``shadowsSoft``
     - bool
     - PCSS contact-hardening shadows: softer, and more expensive.
     - ``OPENGLCONTEXT_SHADOWS_SOFT``
   * - ``shadowCascades``
     - int, 0–4
     - Cascades for a directional light. 0 lets the pass choose from VRAM and frame
       rate; a fixed value makes shadow output reproducible.
     - ``OPENGLCONTEXT_SHADOW_CASCADES``
   * - ``maximumLights``
     - int, 0–8
     - Lights bound in one frame. The shader's own limit still applies.
     - —
   * - ``bloom``
     - bool
     - HDR bloom post-process.
     - ``OPENGLCONTEXT_BLOOM``
   * - ``ibl``
     - ``auto``/``full``/``analytic``/``off``
     - Image-based lighting. ``auto`` uses a cheaper mode on a software
       rasteriser, where the prefilter step is too slow.
     - ``OPENGLCONTEXT_IBL``
   * - ``iblIntensity``
     - float, 0–2
     - Scales the unshadowed ambient/environment term.
     - ``OPENGLCONTEXT_IBL_INTENSITY``
   * - ``transmission``
     - ``auto``/``full``/``blend``/``off``
     - Refraction through glass.
     - ``OPENGLCONTEXT_TRANSMISSION``
   * - ``planarReflections``
     - bool
     - Mirrors and water reflect the scene around them (:doc:`reflections`).
       The developer overlay's Render section shows what they cost
       (:doc:`hud`).
     - ``OPENGLCONTEXT_PLANAR_REFLECTIONS``
   * - ``reflectionViews``
     - int, 0-16
     - The most mirror views a frame draws; 0 is the strategy's own.
     - ``OPENGLCONTEXT_REFLECTION_VIEWS``
   * - ``reflectionBounces``
     - int, 1-3
     - How many reflections deep a chain of mirrors is followed.
     - ``OPENGLCONTEXT_REFLECTION_BOUNCES``
   * - ``instancing``
     - bool
     - Collapse shapes sharing a geometry into one instanced draw.
     - ``OPENGLCONTEXT_INSTANCING``
   * - ``gpuSkinning``
     - bool
     - Skin a rigged figure in the vertex shader rather than on the CPU. Off is
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
     - A multiplier on the overlay's size, on top of the size set by the window's
       height. See :ref:`scale`.
     - ``OPENGLCONTEXT_UI_SCALE``
   * - ``fullscreen``
     - bool
     - Fill the screen rather than open a window of the definition's ``size``.
       Applying it resizes the open window and keeps the GL context and
       everything loaded into it. Ignored while ``OPENGLCONTEXT_HIDDEN`` is set;
       see :ref:`fullscreen`.
     - ``OPENGLCONTEXT_FULLSCREEN``

The environment variable is the field's default. A field that has not been
set reads its environment variable each time the pass reads it, so a shell
variable can still set a feature for a script or a CI run. Once the field is
written, as the settings screen does, the field's value is used. Passes read
these settings through ``OpenGLContext.renderoptions``, not from the
environment directly.

To set them in code, pass them to the definition:

.. code-block:: python

   from OpenGLContext.contextdefinition import ContextDefinition
   definition = ContextDefinition(shadows=False, maximumLights=2, ibl='analytic')

The window's profile and title are set when the context is created and
cannot change while it runs, so the screen does not offer them.

Generated pages
~~~~~~~~~~~~~~~

The settings page is **generated from the node's fields**
(``OpenGLContext.ui.generate``), so a new field appears on the screen with no
UI code. A node class says how its fields should be shown by declaring
``UI_HINTS``:

.. code-block:: python

   class WalkMode(_GroundMode):
       walkSpeed = field.newField('walkSpeed', 'SFFloat', 1, 3.0)
       UI_HINTS = {
           'walkSpeed': {'label': 'Walking speed', 'minimum': 0.5,
                         'maximum': 20.0, 'step': 0.5, 'suffix': ' m/s'},
       }

The field's type chooses the control:

- ``SFBool`` - a toggle.
- A number with a ``minimum`` and ``maximum`` - a slider.
- A number without a range - a number field, rather than a slider over an
  arbitrary 0 to 1.
- ``SFString`` with ``options`` - a select that cycles through them.
- ``MFString`` with ``{'editor': 'keys'}`` - a key capture.

For a different grouping, write the panel by hand; see
:ref:`overlayui-authoring`.

A ``NumberField`` holds the text being typed and writes to the node only when
the text is a complete number. Partial input such as ``''``, ``'-'`` or
``'3.'`` is not written to the ``SFFloat``. A character that cannot be part
of a number is refused.

Saving the player's changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Apply writes the edited values into the live definition, then calls the
``on_apply`` callback passed to ``open_settings``. The application decides
what to do with the settings: write them to a file, send them to a server, or
nothing:

.. code-block:: python

   def saveSettings(session):
       changed = session.changed_fields()        # only what the player moved
       with open(profilePath, 'w') as output:
           json.dump({name: str(getattr(session.draft, name)) for name in changed},
                     output)

   settings.open_settings(context, on_apply=saveSettings)

``changed_fields()`` compares against the values the screen opened with, so
it is still correct after Apply. Saving only the changed fields keeps the
player's choices without also saving every default. A later version of the
game can then change a default, and the player's file does not override it.

A context can also define ``settingsChanged()``. It is called whether or not
``on_apply`` was given, and is where options set once on the window, such as
the swap interval, are applied again. A changed profile or buffer format
takes effect only in the next context.

.. _sessions:

Cancel undoes every change
~~~~~~~~~~~~~~~~~~~~~~~~~~

The widgets edit a **copy** of the node (``OpenGLContext.ui.session``).
Nothing reaches the live settings until Apply:

.. code-block:: python

   session = SettingsSession(context.contextDefinition)
   session.draft            # a copy; every widget binds to this
   session.dirty            # whether the draft differs from the target
   session.commit()         # copy the draft's fields back, field by field
   session.revert()         # throw the draft away

A sub-record, such as a movement mode opened from the main page, is edited in
a **nested session** over a copy of the parent's draft. Its Apply writes into
the parent's draft, and only the outermost ``commit()`` changes the real
node. If the player cancels the movement page, the walk speed is unchanged.
If they apply the movement page and then cancel the settings screen, the walk
speed is still unchanged.

``commit()`` copies fields into the existing node rather than replacing it.
A sub-record ``USE``\ d in two places keeps its identity, and anything
watching a field is notified as usual.

.. _overlayui-bindings:

The key-binding page
--------------------

The key-binding page lists every command of every declared :doc:`movement
mode <navigation>`. Clicking a row opens a capturing dialog. If the captured
key is already bound in the *same* mode, a confirmation asks whether to move
it. The same key in another mode is not a conflict, because two modes are
never in force at once.

Mouse buttons can be bound like keys. A held button goes through the same
input sampler as a held key, under a name in the same vocabulary
(``<mouse-0>``, from ``mouseevents.button_name``). A binding can list it, a
movement mode can read it, and the page shows it as "Left mouse". A
first-person game can therefore put its trigger on the left button. A click
the overlay takes never reaches the sampler, so clicking a button on a screen
does not also fire the command behind it.

A captured key takes effect immediately, so a new binding can be tried
without leaving the page, but the file is written only by Save. Cancel and
Escape restore every binding as the page found it, including after Reset.

Bindings are saved as JSON (``keybindings.json``) in the per-user app-data
directory by ``OpenGLContext.move.bindingstore``. The file is replaced
whole, so an interrupted save cannot leave a file that does not parse.

The file can be edited by hand, and loading tolerates mistakes. A mode or
command this version does not have is skipped, as is a value of the wrong
shape. ``"keys": "wasd"`` is refused with a warning rather than read as four
bindings. An unknown modifier is dropped, so the binding stays usable.

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
print. ``help`` and ``clear`` are built in. The scrollback holds 500 lines by
default, and the arrow keys step through the command history.

``ConsoleLogHandler`` shows the engine's log messages in the console, where a
player can see them. It adds itself to the ``OpenGLContext`` logger, and
removes itself when the console closes. It holds the panel weakly, so a
closed console is not kept alive by the logging framework. Pass ``logger=``
to attach it to a different logger.

New output scrolls the view only while it is at the bottom. Scroll up to read
an earlier message and the view stays there; scroll back to the bottom and it
follows new output again.

.. _overlayui-input:

How input reaches panels
------------------------

**While a modal panel is open, nothing below it receives input**: not the
events the panel handles, not the events it ignores, not the scene and not a
parent panel.

Non-modal panels are layers. An event is offered to the panels from the top
down, as far as the first modal one, and stops at the first panel that takes
it. So a menu bar along the top and a tool palette down the side can both be
open, and each receives the events the other does not take. The pointer's
position is offered to every layer, whatever they do with it, so that each
layer can update its hover state.

``OverlayMixin`` also handles these cases:

- The input sampler (``InputState``) is not fed while a modal panel is open,
  and is cleared when one opens and when the last one closes. A key the
  panel took is not left recorded as held, so the player does not keep
  walking while typing.
- The pointer is released from capture
  (``ViewPlatformMixin.suspendPointerCapture``), so a mouse-look mode does
  not hold the pointer the panel needs. Pointer motion stops turning the view
  as well. The backend reports cursor motion straight to the sampler rather
  than through the event queue, so holding back events would not stop it. The
  position is still tracked, so the movement across the panel does not arrive
  as one jump when capture resumes. See :ref:`pointer-capture`.
- Mouse-move events are delivered while an overlay is open, so hover works
  even in a scene with no move handlers of its own.
- A wheel notch is a press and release of a button no physical mouse has:
  ``WHEEL_UP`` (3) and ``WHEEL_DOWN`` (4) in
  ``OpenGLContext.events.mouseevents``, the X11 numbering. GLUT and pygame
  report the wheel as those buttons. GLFW reports scrolling as offsets on a
  callback of its own, which the backend converts. A notch goes to the widget
  under the pointer and then up through its parents, so a wheel over a page
  that cannot scroll further reaches an enclosing page that can. See
  :ref:`wheel`.
- A press the overlay took also takes its release, even if no overlay is
  open when the release arrives. Otherwise, Escape's key-down would close the
  last panel, and its key-up would reach the scene's own Escape handler,
  which quits every OpenGLContext application. Likewise, the release of a
  click that dismisses a dialog does not pick what was behind the dialog.
- When a panel takes the input, the scene is sent a release for every key it
  was holding. The real release goes to the panel, and an application that
  tracks held keys itself, as a movement mode or a game's steering does, has
  no other way to learn the key came up. Without it, a throttle stays open
  behind the menu. Clearing ``InputState`` covers the sampler, and
  ``letGoOfHeldInput()`` sends a key-up for each held key to everything else.
  The key that opened the panel is not released this way, for the Escape
  reason above. ``clearHeldKeys()`` does the same for a window that loses
  focus while a key is down (see :doc:`eventmodel`).

A panel can declare itself ``capturing``. While it is open, the overlay runs
no accelerators, no Tab traversal and no Enter default, so a rebinding dialog
receives Tab, Enter and the mouse buttons as they are. **Escape is reserved**
as the way out, and is the one key that cannot be bound.

A button arms when pressed over it and fires when released over it, so
dragging off the button cancels the click. Hover highlights the frame. Focus
is shown as a separate ring outside the widget, a solid border with an
additive glow, so that it is visible over any scene. The ring is shown for
keyboard focus and text entry but not after an ordinary click. On a generated
settings page, the whole row under the pointer or with keyboard focus is
highlighted, so the label and the control read as one target.

.. _wheel:

The wheel
---------

One notch scrolls ``ui.scroll.WHEEL_LINES`` lines (3) of the content's font,
so it moves the same amount of text at every interface scale. A notch that
nothing uses is passed on: a wheel over a list that is already at its end
scrolls the enclosing page.

**A control takes the wheel only while it has focus.** A focused slider or
select adjusts on a notch as it does on an arrow key. Unfocused, the notch
passes to the enclosing viewport, which scrolls. A settings page is mostly
controls, and this keeps scrolling the page from changing whatever control
the pointer passes over. Override ``Widget.wheelAdjusts`` to change this for
a widget of your own.

Two properties of the wheel differ from a click:

- Each notch counts. Pending pick events are held in a mapping
  (``Context.addPickEvent``), so that two identical events in one frame are
  handled once. That suits a click or a pointer move, where only the latest
  position matters. For the wheel, each notch must scroll one more step. An
  event's key in the mapping comes from ``Event.getPickKey``, and each wheel
  notch has a distinct key, so three notches in one frame scroll three steps.
- Scrolling arrives in fractions, and one wheel click is not always 1.0. A
  touchpad reports a stream of partial notches. These are summed, and the
  remainder is carried to the next report and dropped when the direction
  reverses, so a slow drag still scrolls and jitter does not scroll
  backwards. A wheel reports whole clicks, but in the platform's own units:
  X11 reports 1.0, and GLFW's Wayland backend reports 1.5 (the protocol's
  15.0 divided by ten). GLFW does not report the size of a click, so the
  backend infers it: a report that is not a whole number of clicks of the
  assumed size is taken as one click of a smaller size.

To diagnose a notch that seems to count twice, set
``OPENGLCONTEXT_DEBUG_WHEEL=1``. Backends and compositors report wheels
differently; a Wayland compositor may report one detent both as a legacy axis
and as a discrete one. With the variable set, every scroll callback logs the
offset it received, the remainder it carries, and how many notches it sent:

.. code-block:: bash

   OPENGLCONTEXT_DEBUG_WHEEL=1 twig-bb some-map.bsp
   INFO wheel: reported +1.0000, carrying +0.0000, sending 1 notch(es)

Two lines for one movement of the wheel mean the wheel is reported twice.
One line saying ``2 notch(es)`` means the offset itself arrived doubled.

.. _pointer-feedback:

Pointer shapes and tooltips
---------------------------

A widget declares the pointer shape and the tooltip shown over it:

.. code-block:: python

   class Splitter(Widget):
       cursor = 'resize-x'
       tooltip = 'Drag to move the line between the views'

``cursor`` is one of ``OpenGLContext.context.CURSORS``: ``arrow``, ``hand``,
``text``, ``crosshair``, ``resize-x``, ``resize-y``, ``resize`` and ``no``.
The overlay sets the context's pointer shape as the pointer crosses the
window, only when the shape changes. GLFW, GLUT, pygame, Tk, wx and Qt each
map these names to their own shapes. If a platform does not have a shape,
``setPointerShape`` returns False and the pointer is left unchanged, rather
than showing a wrong shape; the caller can then show the information another
way. GLUT and Tk have no "not allowed" pointer, so both refuse ``no``. A minimal Wayland cursor theme has only the arrow and the text bar, so
the view splitters also draw a grip.

While a mouse-look mode holds the pointer it is hidden, and the overlay asks
for no shape, so a hover cannot show it again. When the mode lets go, the
shape the control under the pointer wants is put back at once.

``tooltip`` is one line of text, shown when the pointer rests on the control
for ``OpenGLContext.ui.tooltip.TOOLTIP_PAUSE`` seconds (0.6). It is drawn over
the panels rather than pushed on the stack, so it takes no events and does
not change modality. The pause restarts on every movement, so a pointer
passing over a control shows no tooltip. The overlay asks for the frame the
tooltip appears in with ``Context.redrawAt``, so it appears in a window that
draws only when something happens.

Every interactive control also shows a highlight while the pointer rests on
it and a ripple when it is used, with nothing declared; see
:ref:`overlayui-skinning`.

.. _scale:

Everything scales with the window
---------------------------------

An interface laid out in fixed pixels suits one resolution only: at 4K a
16-pixel font is tiny and a checkbox is hard to hit. The overlay scales the
whole interface from one number:

- The window's height selects a font size (``ui.metrics.font_size_for``).
  The reference is the 16-pixel atlas in a 1080-line window, and a 2160-line
  window gets twice that. Smaller windows keep the reference size, because
  smaller text is unreadable. The result is always one of the nine atlas
  sizes, so resizing a window does not build a new atlas for every pixel,
  and the largest atlas is the upper limit.
- ``uiScale`` multiplies that size, for eyesight and viewing distance. It is
  on the settings screen under *Interface*, and applying it lays the panels
  out again at once.
- The font carries a ``scale``, and every pixel measurement goes through
  it: the skin's padding and switch sizes (``Skin.scaled``), a widget's
  margins and ``maximumWidth``, a box's spacing and padding, and a grid's row
  padding. A skin is designed once, at the reference size.

Two measurements are in characters, not pixels. A button's horizontal
padding is in characters, because the text already carries the size. A
panel's ``preferredColumns`` is in characters, which makes it a maximum
width that holds at every scale:

.. code-block:: python

   Panel(fill=True, preferredColumns=78, ...)   # full height, at most 78 columns wide

``fill`` means full height. The width is limited by ``preferredColumns``, and
the panel is centred in the remaining space. This keeps the settings screen a
readable column on a 4K display, with each label next to its control.

A game that draws its own HUD with the overlay's renderer should get the
font size from the context rather than fixing one. There is one renderer per
context, and asking it for a different size every frame rebuilds its atlas
every frame:

.. code-block:: python

   renderer = OverlayRenderer.forContext(self, self.overlayFontSize())
   margin = renderer.metrics.pixels(12)          # 12 at the reference size

.. _overlayui-skinning:

Skinning
--------

A ``Skin`` node holds every colour and inset the widgets use, and an optional
``NineSlice`` image for each widget state. The default skin is flat
translucent rectangles and needs no artwork, which suits a viewer as well as
a game. Its sizes are pixels at the reference font size, multiplied by the
interface scale before use, so a skin is designed once and works at every
resolution (see :ref:`scale`).

.. code-block:: python

   from OpenGLContext.ui.skin import NineSlice, Skin

   panel.skin = Skin(
       buttonImage=NineSlice(url=['art/button.png'], border=(8, 8, 8, 8)),
       buttonHoverImage=NineSlice(url=['art/button_hover.png'], border=(8, 8, 8, 8)),
       panelPadding=20.0,
   )

``border`` is the size, in source pixels, of the corners, in the order left,
top, right, bottom. The four corners are drawn at their own size, the edges
stretch along one axis and the centre along both, so one image serves buttons
of any width. An image left unset falls back to the flat fill, so a game can
skin only the buttons. An image that fails to load logs a warning and falls
back to the flat fill.

A button has a ``role``: ``primary``, ``secondary`` or ``danger``. The skin
draws each role in its own text colour. The ``primary`` button is also the
panel's Enter default. Use ``danger`` for actions that must not be triggered
by accident.

While the pointer rests on an enabled control, ``hoverWash`` is drawn over
it. Buttons, which change their fill, and menu rows, which draw
``menuHighlight``, do not use it. A press spreads a ripple of ``rippleFill``
across the control from where the pointer went down, clipped to the control,
fading as it grows over ``RIPPLE_SECONDS`` (0.45 s, in
``OpenGLContext.ui.widgets``). A control run from the keyboard, by an
accelerator or by a menu letter ripples from its middle. The window keeps
drawing frames while a ripple runs, and a capture's fixed clock times it like
everything else. A widget class opts out with ``washOnHover = False`` or
``ripples = False``. Sliders, text fields, scrolling viewports and view
splitters do not ripple.

A boolean is drawn as a sliding switch rather than a check box: a knob at one
end of a track that changes colour, which can be read at a glance. The
track's ends and the knob come from an antialiased disc the renderer
generates at start-up, so they stay smooth at any interface scale and need no
artwork. A game can supply its own ``switchOnImage``, ``switchOffImage`` and
``switchKnobImage``.

For the HUD's colours, see :ref:`hud-skinning`.

.. _overlayui-authoring:

Building a screen
-----------------

Every widget is a scenegraph node, so a screen can be built in code or parsed
from a file, and its parts ``DEF``/``USE``\ d like any other node:

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

Layout is one top-down pass with no constraint solver. A widget reports its
preferred size. A box gives fixed children their natural size and divides the
remaining space among the ``flex`` children. A ``Grid`` aligns a column of
labels across rows. Sizes are pixels, and the origin is the bottom left of
the window, the same origin as a mouse event's pick point. Layout runs when
something changes, not every frame.

The layout fields are on ``OpenGLContext.hud.GUINode``:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - What it does
   * - ``width``, ``height``
     - An explicit size; 0 means "measure me".
   * - ``flex``
     - Share of the leftover space along the box's axis; 0 keeps the natural size.
   * - ``left``, ``right``, ``top``, ``bottom``
     - Margin outside the widget.
   * - ``maximumWidth``
     - A limit on the width, whatever space is offered; 0 for none. Stops a control
       stretching across a 4K display.
   * - ``alignSelf``
     - ``stretch`` (take the full width), ``start``, ``center`` or ``end``. Any
       value but ``stretch`` also shrinks the widget to its measured width, so a
       switch can sit against the right margin of a wide column.

A ``Panel`` adds ``preferredColumns``, a content width in characters. It is
also the panel's maximum width, so a dialog with one long sentence stays a
readable column.

A generated settings page uses ``Grid``'s row style: ``rowPadding`` adds
space above and below each row, which also enlarges the click target; a thin
line is drawn between rows; and the active row is highlighted. The two
columns share the width evenly, so the controls line up down the page.

A ``ProgressBar`` (in ``ui.widgets``) shows how far a task has got, such as
a download, a bake or a world streaming in. Unlike a ``Slider``, it takes no
focus or input, and its value comes from the task. ``fraction`` is clamped
to 0 to 1. ``text`` is drawn over the bar, for example "Ashdown — 40%".

.. _picture-lifetime:

Pictures and how long they are kept
-----------------------------------

``ui.gallery`` provides ``Carousel`` and ``Picture``, for choosing items by
their image rather than their name. An arrow key moves through the pictures
and clicking a picture chooses it, so a caller can open the chosen item
without opening every item the user browses past.

The pictures are loaded by ``ui.pictures``. It fetches an http(s) URL through
the hardened resolver, decodes on a worker thread, uploads a few pictures per
frame on the render thread, and evicts the least recently used once a texel
budget is reached. A gallery of several hundred entries therefore uses a
bounded amount of GPU memory and never decodes inside a draw call.

Two caches sit behind a gallery, with different lifetimes:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Cache
     - Holds
     - Released
   * - On disk (the resolver's)
     - The downloaded file, for an ``http(s)`` picture
     - Never, by the overlay. A picture is downloaded once, not once per
       session.
   * - On the GPU (``ui.pictures``)
     - The decoded RGBA texture
     - When the texel budget is exceeded (least recently used first), and when
       the **last panel closes**.

Eviction runs only while new pictures are arriving. Once the panel that was
browsing has closed, nothing would trigger it, and a library browsed up to
the budget would hold ``DEFAULT_BUDGET`` (64M texels, 256 MB at RGBA8) for the
rest of the session. So closing the last panel calls
``releaseOverlayPictures()``, which drops every texture.

Reopening decodes from the file again, which for a local or already
downloaded file is a disk read rather than a download. The worker pool keeps
running, so decoding still happens off the render thread and the first frame
back does not stutter. ``PictureCache.close()``, by contrast, stops the
workers and is called when the context is destroyed.

Moving between screens keeps the textures: they are released only when no
panel is left open. A dialog opened over the gallery and closed again leaves
the gallery's pictures in place.

To change the limit, set ``renderer.pictures.budget`` (in texels). To free
the textures sooner, call ``releaseOverlayPictures()``; the cache can be used
again immediately afterwards.

.. _picture-formats:

Pictures in other formats
~~~~~~~~~~~~~~~~~~~~~~~~~

Pictures are decoded with the Python Imaging Library (PIL), which reads PNG,
JPEG, TGA, WebP and the other common image formats. For content in another
format, such as a block-compressed game texture container, register a
decoder for the file suffix:

.. code-block:: python

   from OpenGLContext.ui import pictures

   pictures.registerDecoder('.crn', my_module.load)

``pictures.unregisterDecoder('.crn')`` removes the decoder for a suffix and
returns it, or ``None`` when none was registered.

The decoder receives a file path and returns a PIL image, or ``None`` to
decline the file, for example when an optional dependency it needs is
missing. A declined picture is not drawn, and a gallery shows its empty
plate. A decoder that raises an exception fails only that picture, which is
counted in ``PictureCache.failures``.

Every picture path in the toolkit uses the registry, so a skin, a gallery
and a thumbnail all read the new format. Registering a suffix that PIL
already reads replaces PIL for that suffix, so an application can use a
faster or more permissive reader. The registry is empty by default, and
formats with no registered decoder go to PIL.

.. _overlayui-modules:

Where things are
----------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - Contents
   * - ``ui.geometry``, ``ui.metrics``
     - Rectangles, and measuring and wrapping text.
   * - ``hud``
     - The layout protocol and the box.
   * - ``ui.layout``
     - ``Row``, ``Column``, ``Grid``.
   * - ``ui.widgets``
     - ``Label``, ``Button``, ``Toggle``, ``Select``, ``Slider``, ``ProgressBar``,
       ``TextField``, ``NumberField``, ``KeyCapture``.
   * - ``ui.scroll``
     - The clipping viewport and its scroll bar.
   * - ``ui.panel``
     - One screen: focus, accelerators, modality and commands. Tab and Shift-Tab,
       or Up and Down, move the focus; Space or Return presses the focused item.
       Return with nothing focused presses the primary button, and Escape closes a
       screen that can be closed. Left and Right go to the focused widget, because
       a ``Select``, a ``Slider`` and a ``Carousel`` use them. A modeless panel,
       such as a tool palette or the :doc:`view chrome <multiview>`, shares the
       keyboard with the scene under it: Up and Down go to the camera until Tab
       moves the keyboard into the panel. Clicking one of its buttons does not.
       ``Panel.walksWithArrows()`` returns which applies.
   * - ``ui.overlay``
     - The overlay stack and the context mix-in.
   * - ``ui.menu``
     - ``MenuBar``, ``Menu`` and ``MenuItem``; see :ref:`menus`.
   * - ``ui.toolpalette``
     - A strip of tool buttons down one side, bound to an :doc:`editor's
       <editing>` ``ToolManager``: one button per tool, the active one
       highlighted.
   * - ``ui.tooltip``
     - The tooltip shown when the pointer rests on a control.
   * - ``ui.screen``, ``ui.hudwidgets``, ``ui.debugoverlay``
     - The :doc:`HUD layers <hud>` drawn under the panels, and the developer
       overlay.
   * - ``ui.viewchrome``
     - The controls drawn in each view of a :doc:`window of several views
       <multiview>`.
   * - ``ui.draw``
     - The GL renderer: one program, one batched vertex buffer.
   * - ``ui.gallery``
     - ``Carousel`` and ``Picture``; see :ref:`picture-lifetime`.
   * - ``ui.pictures``
     - The picture cache behind the gallery.
   * - ``ui.skin``
     - Colours, insets and nine-slice images.
   * - ``ui.session``
     - Editing on a copy.
   * - ``ui.generate``
     - A settings page generated from a node's fields.
   * - ``ui.dialogs``, ``ui.settings``, ``ui.bindings``, ``ui.console``,
       ``ui.contentscreen``
     - The ready-made screens.
   * - ``renderoptions``
     - How a pass reads a rendering setting.

The design and its reasoning are in ``plans/OVERLAY-UI.md``.
