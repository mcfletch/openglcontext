# The window system as a held object

**Status:** 🟡 In progress on branch `windowsystem` (worktree
`openglcontext/.claude/worktrees/windowsystem`), 2026-09-26. See *Progress* at
the foot of this page for what has landed and what is next.

## The problem

A context today is assembled by multiple inheritance, three classes per
backend:

```text
GLFWContext            (glfwevents.EventHandlerMixin, Context)
GLFWInteractiveContext (ViewPlatformMixin, InteractiveContext, GLFWContext)
glfwvrmlcontext.VRMLContext (vrmlcontext.VRMLContext, GLFWInteractiveContext)
```

and the same again for glut, pygame, tk, wx, egl, wgl and (in
openglcontext-qt) qt: about thirty modules counting the `*testingcontext`
aliases, and 24 plug-in registrations in three registries (`plugins.Context`, `plugins.InteractiveContext`,
`plugins.VRMLContext`), and a class hierarchy whose shape differs per backend
(`wxContext` *is* a `wx.glcanvas.GLCanvas`, `QtContext` *is* a `QWindow`,
`TkContext` holds its `GLFrame`).

What that costs:

- The backend is chosen where a `class` statement is written, so a program
  picks it at import time through `testingcontext.getInteractive()`, which
  answers `Any` because a checker cannot name a base class chosen at run time.
  Every application subclass is therefore unchecked by mypy.
- Mix-ins that need the context beside them carry `if TYPE_CHECKING: class
  _Host` declarations (`vrmlcontext.py`, `move/viewplatformmixin.py`,
  `events/glfwevents.py`, `context.py`'s own `isCapturingEvents` stub), and the
  MRO order is load-bearing: `qtcontext.py` has to list `Context` before
  `QWindow`, unlike every other backend, because of PySide's cooperative
  initialisers.
- An application's subclass shares one namespace with the toolkit's.
  `wxContext` already has to override `ProcessEvent` (`wxcontext.py:250`)
  because `wx.Window` has a method of that name meaning something else, and an
  application method called `OnPaint`, `Show` or `keyPressEvent` silently
  overrides wx or Qt. The backend's own translation methods (`glfwOnKey`, `PygameKeyDown`,
  `tkOnMouseMove`, ...) sit in the application's namespace too.
- "Plain", "interactive" and "VRML" contexts differ by capabilities almost
  every program wants, and the plain slot does not stand on its own. Each
  plain backend class already mixes in its toolkit's `EventHandlerMixin`, but
  not `InteractiveContext`'s manager table or `ViewPlatformMixin`, while
  `Context` itself calls `addEventHandler` in `setupDefaultEventCallbacks`
  (`context.py:699-740`) and `getViewPlatform` in `examineCenter`
  (`context.py:1742`). `OverlayMixin` calls `suspendPointerCapture` and
  `getInputState` unguarded, which only `ViewPlatformMixin` defines, so the
  documented `class Game(OverlayMixin, Context)` in `docs/hud.rst:531` fails
  at the first pointer event. Folding the mix-ins in resolves these by
  construction.
- There is no way to say "a context, on whichever window system this
  configuration names" as data. [plans/2026-09-20-offscreen-context-class.md](../../plans/2026-09-20-offscreen-context-class.md)
  is one symptom: an offscreen context needs its own factory because the
  backend is a base class.

## The shape wanted

One `Context` class. It *holds* a window system rather than deriving from
one:

```python
context = Context(definition)             # definition.windowsystem chooses
context.windowsystem                      # GLFWWindowSystem, EGLWindowSystem, ...
context.window                            # the toolkit's own window or widget
MyContext.ContextMainLoop()               # still the entry point
```

- `ContextDefinition.windowsystem` is a new field naming the backend, resolved
  through a plug-in registry when the context is constructed.
- Native callbacks are registered by the window system and translated there
  into OpenGLContext events, which it hands to the context
  (`context.ProcessEvent`, `context.OnResize`, `context.OnQuit`).
- Window-level requests on the context (`setCurrent`, `SwapBuffers`,
  `setFullscreen`, `setPointerCapture`, `setPointerShape`, `setVSync`,
  `releaseWindow`, `MainLoop`) delegate to the window system.
- `context.window` is the low-level window or widget the toolkit knows, on
  every backend. An application that packs, sizes or parents the view uses
  `context.window`.
- `EventHandlerMixin`, `InteractiveContext`'s manager table,
  `ViewPlatformMixin` and `vrmlcontext.VRMLContext` become bases of `Context`
  and remain mix-in classes in their own modules. The plain/interactive/VRML
  distinction disappears.
- `ContextDefinition.navigation` declares how the context is moved through:
  the registered movement modes in use, the views and their arrangements,
  and for each whether the user may switch it (keys, on-screen controls) or
  only the application. `NULL` means no navigation at all.
- `ContextMainLoop` remains the entry point.
- The per-backend modules keep their names as aliases: `pygamecontext.PygameContext`,
  `pygameinteractivecontext.PygameInteractiveContext` and
  `pygamevrmlcontext.VRMLContext` are all `Context` with `windowsystem =
  'pygame'` already chosen. Likewise for every other backend.

## Design

### The `WindowSystem` protocol

A new package `OpenGLContext/windowsystem/`, one module per backend
(`glfw.py`, `glut.py`, `pygame.py`, `tk.py`, `wx.py`, `egl.py`, `wgl.py`), the
Qt one in `OpenGLContext_qt/windowsystem.py`. `windowsystem/base.py` holds the
abstract class. Its surface is what the backends override on `Context` today
(measured from the classes' own namespaces, 2026-09-26):

| Group | Today, on the backend context class | On `WindowSystem` |
|---|---|---|
| Lifetime | the backend's `__init__` before `Context.__init__`, `releaseWindow`, `OnQuit`, `close` (egl, wgl) | `open(definition)`, `release()`, `close()` |
| Current / present | `setCurrent`, `unsetCurrent`, `_glHandle`, `SwapBuffers`, `applyVSync`, `setVSync` | `makeCurrent()`, `doneCurrent()`, `glHandle()`, `swap()`, `applyVSync(definition)` |
| Window requests | `setFullscreen`, `applyFullscreen`, `setPointerCapture`, `setPointerShape`, `recentrePointer`, `pointerWarpEcho`, `settingsChanged` | the same names |
| Loop | `MainLoop`, `_loopIteration`/`loopIteration`, `pumpWindowEvents`, `OnIdle` scheduling, `ContextMainLoop` (classmethod) | `mainLoop()`, `pump()`, and a classmethod `run(contextClass, *args, **named)` for the toolkits that need an application object before a window (wx `App`, Qt `QApplication`, Tk root, `glutInit`). `Context.ContextMainLoop` stays the application's entry point: it resolves the definition, looks up the window-system class and calls its `run` |
| Native events | `glfwOn*`, `glutOn*`, `Pygame*`, `tkOn*`, wx `On*`, Qt `*Event` overrides, `emitKey` overrides, wheel-notch arithmetic | the window system's own methods, bound to the toolkit's callbacks; they build the existing `events/*events.py` event objects and call into the context |
| Capabilities | `providesGLUT`, `deferRedraw`, `_nativeRepeat`, `TimeManagerClass` (egl/wgl) | class attributes on the window system, read by the context |
| Deferred start | Qt `DoInit`/`completeInit`/`waitForExposure`, wx first-paint `DoInit` | `open()` answers whether GL is ready; if not, the window system calls `context.completeInit()` when it is |

What stays on `Context`, backend-neutral: the definition, the render passes,
redraw scheduling, picking, the frame counter and loop trace, telemetry, auto
exit and capture, event dispatch, the camera and navigation, scene loading.

The window system holds its context strongly and the context holds the window
system: they are one object's two halves and die together.
`OpenGLContext.contextresources` keys stay on the context.

The per-frame delegated calls (`makeCurrent`, `swap`) cost one attribute hop
each; native callbacks bind straight to window-system methods, so the event
path is no deeper than it is now. `check_still_frame` and the loop trace hold
this.

### `context.window`: the toolkit's window, held

`wxContext` and `QtContext` are toolkit widgets today, and an embedding
application places the context itself in its layout. After this change the
window system creates the toolkit's window and the context exposes it as
`context.window`, the same attribute on every backend:

| Backend | `context.window` |
|---|---|
| glfw | the GLFW window handle (the attribute's meaning today) |
| glut | the GLUT window id |
| pygame | the display surface |
| tk | the `OpenGL.Tk.GLFrame` (`self.frame` today) |
| wx | a `wx.glcanvas.GLCanvas` subclass |
| qt | a `QtGui.QWindow` subclass |
| egl, wgl | the pbuffer surface |

For wx and Qt the window is a small toolkit subclass whose only job is to
forward the toolkit's virtual methods (paint, size, key, mouse, close) to the
window system. The application's own subclass no longer shares a namespace
with the toolkit.

`context.window` is set by the window system's `open()` and is `None` once
`releaseWindow()` has let it go, as GLFW's is now.

This is the change an embedding application sees: code that packs, sizes,
parents or focuses the view uses `context.window`.
`sizer.Add(context)` becomes `sizer.Add(context.window)`,
`context.SetFocus()` becomes `context.window.SetFocus()`, and Qt's
`view.container(splitter)` becomes
`QWidget.createWindowContainer(context.window, splitter)` (the window system
keeps a `container()` helper for the checks it makes). The wx and Qt alias
classes keep their constructor signatures (`wxContext(parent,
definition=None, ...)`). `docs/embedding.rst`, `OpenGLContext/demos/` and
`OpenGLContext_qt/demos/` are written against the new form.

`Context.__init__` gains a keyword-only `parent`, the toolkit container the
view is created inside (wx parent window, Tk master, Qt container), passed to
`WindowSystem.open`. Backends with no notion of one reject it.

### `ContextDefinition.windowsystem`

An `SFString` field. Its values are the registered plug-in names plus two
that resolve at construction:

- `''` (the default) - the `OPENGLCONTEXT_BACKEND` variable, then the user's
  `defaultcontext.txt` preference, then the first registered window system
  that imports, in a platform order (glfw first).
- `'offscreen'` - `egl`, or `wgl` on Windows, from the existing
  `getOffscreenBackendName`. This replaces the separate offscreen factory the
  2026-09-20 plan asked for: `Context(windowsystem='offscreen')`.

Resolution is a plain function with no GL and no import side effects,
`windowsystem.choose(requested, environment, preference, platform,
available)`, unit-tested over every branch. A name that is not registered, or
whose toolkit will not import, raises naming the backend, the registered set
and the import error, as `testingcontext._required` does now.

The field is read once, in `Context.__init__`. It is not a runtime setting:
`UI_HINTS` does not offer it.

A class pins its window system the way it pins its profile: a class
attribute, `Context.windowSystemName: ClassVar[str | None] = None`, applied by
`resolveDefinition` over a definition that did not set the field itself. The
alias classes are exactly this:

```python
class PygameContext(Context):
    windowSystemName = 'pygame'

PygameInteractiveContext = PygameContext      # pygameinteractivecontext.py
VRMLContext = PygameContext                   # pygamevrmlcontext.py
```

Precedence, highest first: a definition passed to the constructor that sets
the field, the class's `windowSystemName`, the class's declared
`contextDefinition`, the environment/preference default. A test run's
`OPENGLCONTEXT_TEST_WINDOWING=offscreen` therefore reaches every plain
`Context` but not a program that explicitly asked for `PygameContext`; the
test harness sets the definition field where it needs to override that.

### Plug-in registry

`plugins.WindowSystem` replaces the three context registries.
`OpenGLContext/__init__.py` registers the built-in seven. No `pyproject.toml`
in the workspace declares a context entry point today: registration is the
hard-coded calls in `OpenGLContext/__init__.py:39-66` and a `try: import
OpenGLContext_qt` at `:68-74`, and `getContextType`'s docstring describing
entry points is out of date. Third parties (openglcontext-qt first) register
through a new `openglcontext.windowsystems` entry-point group, which replaces
the import probe. `scripts/writeplugins.py`, an unused generator for the
setuptools strings, is deleted.

`plugins.Context`, `plugins.InteractiveContext` and `plugins.VRMLContext` stay
for one release, each entry pointing at the alias class, so
`getContextType(name)` and `testingcontext.getInteractive(name)` still answer
a class, and warn. `getInteractive()` / `getVRML()` with no preference answer
`Context` itself, whose type a checker can name, so the `Any` goes. `getVRML`
has no callers and is deprecated with the registries.

### Folding the mix-ins into `Context`

`EventHandlerMixin` (with `HeldKeyMixin`), `InteractiveContext`'s
`EventManagerClasses` and `TimeManagerClass`, `ViewPlatformMixin` (with
`PhysicsWalkMixin`), and `vrmlcontext.VRMLContext` (`load`,
`setupFontProviders`, `initialPosition`) become part of `Context`.

They stay mix-in classes, each in its own module, and `Context`'s bases list
them once:

```python
class Context(
    ViewPlatformMixin, EventHandlerMixin, VRMLSceneMixin,
    ScreenMixin, ScreenshotMixin, ContextConfigMixin,
):
```

They were split out of `context.py` to keep that module to a size a reader
can hold, and they stay split for the same reason. What changes is who
composes them: `Context`, once, instead of every backend in three
combinations. The `_Host` declarations shrink to naming `Context`, the one
class they are mixed into. The test fakes that build a partial host from a
mix-in alone (`twig-bb/tests/viewersupport.py:95`
`HeadlessContext(ViewPlatformMixin)`, `twig-bb/tests/test_viewer.py:1176`,
`test_terrainwalk_avatar.py:78`, `test_inputstate.py:367`,
`test_default_key_bindings.py:103`, `test_physicswalk.py:102`, the `test_ui_*`
fakes) keep working, since the classes they name still exist.

`vrmlcontext.VRMLContext` is renamed `VRMLSceneMixin` in the same module, since
`VRMLContext` becomes the alias name every backend's `*vrmlcontext` module
exports; `vrmlcontext.VRMLContext` stays as an alias of the mix-in.
`InteractiveContext`'s `EventManagerClasses` and `TimeManagerClass` move onto
`EventHandlerMixin` as its defaults, and `interactivecontext.InteractiveContext`
becomes an alias of `EventHandlerMixin`.

Behaviour a plain-slot context gains, and how each is contained:

- Keyboard and mouse managers - inert until a handler is bound.
- The default navigation bindings (`setupDefaultEventCallbacks`) and the
  camera (`ViewPlatform`, created lazily at the first render) - governed by
  `ContextDefinition.navigation`, below. A `NULL` navigation binds no
  navigation keys or drags and gives the context no view platform, so a tool,
  a bake or a test that sets its own projection in `Render` draws with it
  alone. `getViewPlatform()` on such a context answers `None`, and
  `examineCenter`, `OverlayMixin` and `ScreenMixin` are made to accept that.
- Font providers - loaded at init today for VRML contexts only. Made lazy
  (at the first text node) so a context that draws no text does not import
  FontTools.

### `ContextDefinition.navigation`

How a context is moved through and looked at is declared, not coded: which
movement modes it has, which views, how they are arranged, and who may
switch between them. The same game can then ship a player's definition and
an editor's definition over one scene. For example:

- A game with registered `fps`, `fps-swim`, `fps-map` and `fps-fly` modes,
  switched only by its own logic (entering water, opening the map, a pickup),
  in a single perspective view.
- The editor for that game with one view or four, the editor's orthographic
  plan and elevation views beside a perspective one, and the user switching
  both mode and arrangement from on-screen controls and keys.

#### What is there to build on

- `move/modes.py`: `MovementMode` nodes (`WalkMode`, `FlyMode`, `SwimMode`,
  `FPSMode`) with their own fields (speeds, `capturePointer`, `bindings`),
  declared today as `ContextDefinition.movementModes` (`MFNode`). The mode in
  force is published as `ContextDefinition.movementMode`.
- `move/navigation.py`: `NavigationManager`, which applies a mode the world
  imposes (`enter_when`, as swimming does) over the one selected, and offers
  `select(name)` and `cycle()`.
- User switching today is a key: `cycleMovementMode` on `m` in
  `viewer/sceneviewer.py:1170` and `openglcontext-forest` `run.py:104`; twig-bb
  calls `navigation.select`/`cycle` from game logic (`viewer.py:1774-1780`).
- `multiview/navigation.py`: `ViewNavigationMode` nodes for the gestures in
  one view, with the `plan_mode()` and `examine_mode()` presets.
- `multiview/viewset.py` / `multiview/mixin.py`: `ViewSet` with named
  arrangements (`single`, `split`, `quad`), `MultiViewMixin.startViews()`
  building a perspective view and three `OrthoView` elevations, and
  `ui/viewchrome.py`, the on-screen furniture that switches arrangements and
  maximises a view.
- `ui/settings.py` and `ui/session.py` edit `movementModes` (a mode's key
  bindings) through a draft of the definition.

None of these is configured from the definition beyond `movementModes`: the
views are built by a method call, the user's switching is whichever key an
application happened to bind, and the modes are instances the application
constructs.

#### The structure

`navigation` becomes an `SFNode` holding a `Navigation` node, in a new
`move/navigationdefinition.py` (declarations only, no GL, no events):

```python
Navigation(
    modes=['fps', 'fps-swim', 'fps-map', 'fps-fly'],
    mode='fps',
    modeSwitching=[],                      # the game's logic only
    views=Views(
        views=[ViewDefinition(name='main', camera='perspective')],
        arrangements=[Arrangement(name='single', views=['main'])],
        arrangement='single',
        switching=[],
    ),
)

Navigation(                                # the editor for the same game
    modes=['orbit', 'fly', 'fps'],
    mode='orbit',
    modeSwitching=['keys', 'controls'],
    views=Views(
        views=[
            ViewDefinition(name='top', camera='top', gestures=['plan']),
            ViewDefinition(name='front', camera='front', gestures=['plan']),
            ViewDefinition(name='left', camera='left', gestures=['plan']),
            ViewDefinition(name='perspective', camera='perspective'),
        ],
        arrangements=[
            Arrangement(name='single', views=['perspective']),
            Arrangement(name='quad', views=['top', 'front', 'left', 'perspective']),
        ],
        arrangement='quad',
        switching=['keys', 'controls'],
    ),
)
```

`Navigation` fields:

- `modes` - `MFNode` of `MovementMode`. The ways the perspective camera can
  move, as today's `movementModes`. A mode is a node because it carries
  per-mode settings (speeds, sensitivity, the player's rebound keys) that the
  settings screen edits and saves. A *name* where a mode is expected (a
  string in a configuration file, or in the Python constructor as above) is
  looked up in the movement-mode registry and replaced by the node that
  registration makes.
- `mode` - `SFString`, the mode selected at start; empty means the first
  selectable one, as `NavigationManager` does now.
- `current` - `SFNode`, the mode in force, written by the manager each frame
  (today's `movementMode`, and `TRANSIENT_FIELDS` as that is).
- `modeSwitching` - `MFString`, how the *user* may change mode:
  - `keys` - the `cycleMovementMode` binding and each mode's own selection
    key.
  - `controls` - an on-screen mode selector on the overlay.
  - Empty - neither. `context.navigation.select(name)` and `cycle()` work in
    every case; this field governs only what the user is offered, never what
    the application may do. A world-imposed mode (`enter_when`) applies
    regardless.
- `views` - `SFNode` holding a `Views` node, described below. `NULL` means
  one full-window perspective view, today's default.

`Views` fields:

- `views` - `MFNode` of `ViewDefinition`, each with:
  - `name`
  - `camera` - a registered camera kind: `perspective` (the context's
    `ViewPlatform`, driven by `modes`), `top`/`front`/`left`/`right`/`back`/
    `bottom` (an `OrthoView` along that axis), or `scene` (looking through
    the scene's bound `Viewpoint` or glTF camera).
  - `gestures` - `MFString` of registered `ViewNavigationMode` names (`plan`,
    `examine`), what the pointer does in that view. Empty on a perspective
    view means `modes` drives it.
  - `style` - background, grid.
- `arrangements` - `MFNode` of `Arrangement(name, views)`; the named layouts
  `ViewSet` already takes as a dictionary. The number of views picks the
  tiling (`single`, `split`, `quad`), as `viewset.ARRANGEMENT_FOR` does.
- `arrangement` - the one shown at start.
- `switching` - `MFString`, as `modeSwitching`: `keys` binds the
  arrangement and maximise keys, and `controls` puts up `ViewChrome`. Empty
  leaves arrangement to the application (`context.views.show(name)`).

Setting `navigation` to `NULL` gives the context no navigation at all. The
default is a `Navigation` whose `modes` are the engine's classic bindings
(below) and whose `views` is `NULL`, so a context that says nothing behaves
as an interactive context does today.

#### Registries

Two new plug-in registries in `plugins.py`, beside `WindowSystem`:

- `plugins.MovementMode` - name to a factory returning a configured
  `MovementMode` node. The engine registers `walk`, `fly`, `swim`, `fps` and
  `examine`. `examine` is the classic arrow-key and drag navigation that
  `setupDefaultEventCallbacks` binds today, wrapped as a mode so that it is
  one choice among the others rather than a separate code path. A game
  registers its own (`fps-map`, a mode whose `update` drives a map camera) at
  import, or through an `OpenGLContext.movementmodes` entry point.
- `plugins.ViewGestures` - name to a factory returning a
  `ViewNavigationMode`. The engine registers `plan` and `examine`. An editor
  registers its own.

The camera kinds are a closed set in the engine (`multiview/cameras.py`
builds them).

A factory takes the world's scale where it needs one, as `walk_fly_modes(scale)`
does now. Registered modes are made with the default scale, and
`Navigation.scaled(scale)` answers a copy with each mode's speeds scaled.
`PhysicsWalkMixin`, `TerrainWalkMixin` and the viewer, which set
`movementModes` from a scale today, call that instead.

#### What reads it

- `ViewPlatformMixin.getNavigation()` builds the `NavigationManager` from
  `definition.navigation`, as it does now from `movementModes`. The manager
  gains a `userSwitching` view of `modeSwitching`, which the key binding and
  the selector consult. `select` and `cycle` remain the application's API.
- `MultiViewMixin` becomes a base of `Context` with the other folded mix-ins
  and builds its `ViewSet` from `navigation.views` at init, replacing the
  `startViews()` call an application makes today. `startViews()` stays for an
  application that switches views on at run time, and writes what it made
  back into the definition. With `views` `NULL` it builds nothing and costs
  nothing per frame.
- The on-screen controls (`ViewChrome`, and a new mode selector in
  `ui/hudwidgets.py`) need the overlay stack. `OverlayMixin` is an
  application's choice today; a definition asking for `controls` on a context
  without it raises at construction, naming the mix-in. Whether
  `OverlayMixin` should fold into `Context` too is open (see *Decisions*).
- The settings screen edits `navigation.modes` where it edits
  `movementModes` now. User settings saved under `movementModes` are read
  into `navigation.modes` when loaded. `movementModes` and `movementMode`
  remain on `ContextDefinition` for one release as properties forwarding to
  `navigation`, with a warning.

#### Tests

The declarations and the choice of what is built from them are plain objects
and are tested without a window: registry lookup and the unknown-name error;
a name becoming a node in both the configuration and constructor paths;
`modeSwitching` empty leaving `cycleMovementMode` unbound while `select()`
still works; a world-imposed mode applying with switching empty; each
`Views` declaration producing the `ViewSet` `startViews()` would; `controls`
without `OverlayMixin` raising; `NULL` navigation giving no view platform; a
settings file naming `movementModes` loading into `navigation.modes`. Each
cached derivation (the manager, the `ViewSet`) gets `check_memo_inputs`, one
edit per field it is built from.

`glutvrmltestingcontext.VRMLContext.createMenus` (the pop-up world menu) moves
onto the GLUT window system as an optional feature the testing context
switches on.

## Phases

Each phase lands green through `tools/preflight.py openglcontext` (and the
other projects it touches) and is Red/Green: the test for the new behaviour
exists and fails before the code does.

**Phase 0 - pin what is there.** Before anything moves, the behaviour each
backend presents to an application is held by tests that address it through
the *context's* public API rather than the backend's method names: a key,
button, motion and wheel reaching a handler; resize reaching `OnResize` and
the viewport; close reaching `OnQuit`; fullscreen, pointer capture and shape,
vsync; `drawAndReadFrame`; teardown releasing GL objects. Many exist in
`tests/unit/` and `openglcontext-qt/tests/` under the backend's own method
names (`ctx.glfwOnKey(...)`); those are rewritten to go through the window
system's translation from the start, so they survive the move unchanged. The
consumer inventory below is completed here.

**Phase 1 - the registries and the fields.** `plugins.WindowSystem`,
`plugins.MovementMode`, `plugins.ViewGestures`,
`ContextDefinition.windowsystem`, the `Navigation`, `Views`,
`ViewDefinition` and `Arrangement` nodes, `ContextDefinition.navigation`,
`windowsystem.choose()` and `Context.windowSystemName`, with nothing using
them yet. Fully unit-tested, no GL.

**Phase 2 - fold the mix-ins.** `Context` gains the event, navigation,
multi-view and scene-loading bases; lazy font providers. The backend classes
still derive from `Context` and still work. The interactive and VRML classes
become aliases of the plain one for backends where that is already true in
effect (egl, wgl).

**Phase 2b - navigation from the definition.** The `examine` mode wrapping
the classic bindings; `NavigationManager` and the `ViewSet` built from
`navigation`; `modeSwitching` and `switching` governing the keys and the
controls; the mode selector widget; the settings screen and saved settings
moved to `navigation.modes`, with the `movementModes`/`movementMode`
forwarding properties. `oglc-view` is the first consumer: its `--views`
option and its `m` binding become a `Navigation` it builds from its options.
This phase is independent of the window-system work and can land before
phase 3 or beside it.

**Phase 3 - one backend at a time.** Order: egl (no events, no loop to speak
of: the smallest complete protocol), glfw (the default and what the test
fixtures open), glut, pygame, tk, wx, wgl, then qt in its own repository. For
each: the window-system class, the native-event translation moved onto it,
the old module reduced to its alias, its tests green. wx is not installed in
this container and wgl needs Windows; both are ported with their CI jobs as
the gate, and neither is called done until those jobs have run.

**Phase 4 - consumers.** Everything in the inventory that names a backend
class moves to `Context` (or keeps an alias where it is a published name).
The games and demos are the check that the API reads well: a program should
read `class Game(Context)` with the window system and the navigation in its
definition. For navigation that means: the games declare their modes and
`modeSwitching` instead of setting `movementModes` and binding
`cycleMovementMode` themselves (forest `run.py:104`, twig-bb's
`select`/`cycle` stays as game logic with switching empty); the viewer and
the editors (glisteel-editor, marble-editor, openglcontext-editor's tool
views) declare their views and arrangements instead of calling
`startViews()`.

**Phase 5 - documentation.** `docs/backends.rst` (rewritten around the
field and the protocol, including how to write a window system),
`docs/structure.rst`, `docs/embedding.rst`, `docs/eventmodel.rst`,
`docs/navigation.rst` (rewritten around the `Navigation` declaration and the
movement-mode registry), `docs/multiview.rst` (views declared rather than
started), `docs/overlayui.rst` (the settings screen and the mode selector),
`docs/offscreen.rst`, `docs/profiles.rst` (the
precedence paragraph), `docs/testing.rst`, the tutorials' `BaseContext`
preamble where it changes, `README.md`, and this project's `CLAUDE.md`
directory map and `OPENGLCONTEXT_BACKEND` section. The workspace plan
[2026-09-20-offscreen-context-class.md](../../plans/2026-09-20-offscreen-context-class.md)
is closed as done by `windowsystem='offscreen'`.

**Phase 6 - removal**, one release later: the three old registries, the
`getContextType` path, and any deprecation shims phase 3 needed. The alias
modules stay; they are published names.

## Compatibility

Kept working:

- Every alias module and class name, with its constructor signature.
- `class TestContext(BaseContext)` with `BaseContext` from
  `testingcontext.getInteractive()` / `getVRML()`.
- Subclasses overriding `OnInit`, `Render`, `OnIdle`, `OnResize`, `ViewPort`,
  `setupCallbacks`, `setupDefaultEventCallbacks` and calling up: these are
  `Context` methods and stay so.
- `OPENGLCONTEXT_BACKEND` and the `defaultcontext.txt` preference.

Changing, each listed in the release notes with its replacement:

- Embedding: the context is no longer the wx `GLCanvas` or the Qt `QWindow`.
  Packing, sizing, parenting and focusing the view go through
  `context.window`.
- Tk's `context.frame` becomes `context.window`; `frame` stays as a
  read-only property for one release, with a warning. GLFW's
  `context.window` keeps its meaning.
- wx and Qt widget methods called on the context (`SetFocus`, `GetSize`,
  `requestUpdate`, ...) are called on `context.window`.
- Subclasses overriding a backend's own translation methods (`glfwOnKey`,
  `PygameKeyDown`, wx `OnPaint`, Qt `keyPressEvent`, `emitKey`) no longer
  reach them. The replacement is a window-system subclass named by the
  context (`windowSystemClass`), or better, an engine event the override was
  standing in for. No application in the workspace does this; the tests that
  do are rewritten in phase 0.
- `isinstance(context, GLFWContext)` and friends: true only for contexts made
  through that alias. The replacement is `context.windowsystem.name`.

## Consumer inventory

Surveyed 2026-09-26 across every submodule and `downstream/`; worktrees,
`build/` and `.venv` excluded.

### The games and demos

Every application reaches its backend the same way and none reaches past the
context to the toolkit:

| Project | Class | Base |
|---|---|---|
| openglcontext-forest `run.py:126` | `Forest(OverlayMixin, TerrainWalkMixin, BaseContext)` | `getInteractive()` |
| twig-bb `viewer.py:617` | `TwigContext(OverlayMixin, AsyncSceneMixin, BaseContext)` | `getInteractive()` |
| twig-bb `hudsample.py:150` | `HUDSampleContext(OverlayMixin, BaseContext)` | `getInteractive()` |
| glisteel `game.py:142` | `GlisteelContext(RecordingMixin, OverlayMixin, BaseContext)` | `getInteractive()` |
| glisteel-editor `app.py:112` | `EditorContext(OverlayMixin, BaseContext)` | `getInteractive()` |
| marble-demo `run.py:146` | `MarbleContext(RecordingMixin, BaseContext)` | `getInteractive()` |
| marble-editor `app.py:113` | `EditorContext(RecordingMixin, OverlayMixin, BaseContext)` | `getInteractive()` |

Each sets `OPENGLCONTEXT_BACKEND=glfw` with `os.environ.setdefault` before
calling `getInteractive()` at module level. They override `OnInit`, `OnIdle`,
`OnEscape`/`OnQuit`, `ViewPort` (glisteel-editor), `ProcessEvent`
(glisteel-editor, marble-editor), `close` (glisteel) and `OnResize` (forest,
the one override of a method a backend defines, and it calls up). They call
`ContextMainLoop`, `setCurrent`, `triggerRedraw`, `addEventHandler`,
`getViewPlatform`, and read or assign `platform` and `movementManager`. There
is no `self.window`, `self.frame` or `self.canvas`, no raw toolkit call, and
no override of a backend's translation methods.

All of that is `Context` API after this plan, so the games need no change to
keep working. Phase 4 moves them to `class Game(Context)` with the window
system in the definition, and drops the `setdefault` in favour of the
field; `twig-bb/twig_bb/match.py:29` imports `ContextConfigMixin` and moves
with it.

`downstream/` has no OpenGLContext use. pyopengl and pyopengl-demo name no
context class.

### openglcontext library code naming a backend class

- `OpenGLContext/__init__.py:39-74` - the registrations; becomes the
  `WindowSystem` registrations.
- `viewer/__init__.py:82` `viewerFor(backend)` builds
  `type(..., (OverlayMixin, SceneViewerMixin, base))` from
  `getContextType(backend)`. Becomes one class, with the backend passed as the
  definition's field.
- `viewer/sceneviewer.py:1269-1272` `ViewerContext(OverlayMixin,
  SceneViewerMixin, testingcontext.getInteractive())` - its base becomes
  `Context`, which is also what lets mypy check the viewer.
- `context.py:1856-1896` `CONFIG_CONTEXT_PLUGINS` / `fromConfig` builds a
  subclass from a config file's backend; becomes a definition field set from
  the config.
- `bin/gltest.py:38-39`, `bin/choosecontext.py:19` - list and pick backends;
  move to the `WindowSystem` registry.
- `bin/gltf_demo.py:379` calls `getInteractive().setupCallbacks(self)` to skip
  the viewer's own bindings; becomes `Context.setupCallbacks(self)`.
- `extensionmanager.py:151`, `testing/scenes.py:86`,
  `docbuild/surface_swatches.py:58`, `scripts/multiview_bench.py:110` -
  `getInteractive()`.
- `testing/glcontext.py:437` imports `EGLContextError` and `PbufferContext`
  from `eglcontext`; these move with the EGL window system and keep an import
  from the old module.
- `demos/wx_viewer.py:54` imports `wxcontext` for its side effect of settling
  `PYOPENGL_PLATFORM`; that side effect moves to the wx window system's
  module.
- `bin/character_sheet.py:204-216` overrides `SwapBuffers` to read back before
  the swap. `Context.SwapBuffers` stays the method the frame calls, delegating
  to `windowsystem.swap()`, so the override and `drawAndReadFrame`'s
  per-instance intercept both keep working.
- Docstring examples naming backend classes: `ui/overlay.py:20`,
  `ui/settings.py:24`, `passes/zonebake.py:16`,
  `move/viewplatformmixin.py:139`, `events/*events.py`, `demos/tk_viewer.py:22`,
  `context.py:646,878`, `testing/glfwteardown.py:42`, `renderoptions.py:119`,
  the `TestRenderer` examples at the foot of each backend module.

openglcontext-editor: `bake/probes.py:76,91` `class Baker(EGLContext)`;
becomes `Context` with `windowsystem='offscreen'`, which also makes the baker
run on Windows.

### Embedding: the context is the widget

These move to `context.window` (see *`context.window`: the toolkit's window,
held*):

- `demos/wx_viewer.py:122,337` - the view is a `GLCanvas` placed in a
  splitter, and `view.SetFocus()`.
- `demos/tk_viewer.py:111,190,211` - `SceneView(parent=holder)`,
  `loopIteration()`, `releaseWindow()`; Tk already holds its frame, so only
  `loopIteration` moves.
- `openglcontext-qt/OpenGLContext_qt/demos/qt_viewer.py:113,117,199-200,300` -
  `view.container(splitter)` on the view as a `QWindow`,
  `startRenderTimer`/`stopRenderTimer`, `releaseWindow()`, `deferRedraw`.
- `tests/wx_multiple_contexts.py`, `tests/wx_with_controls.py`,
  `tests/glprint.py:90`, `tests/wx_font.py` subclass the wx contexts.

### Tests

- About 30 files in `tests/unit/` import a backend module; 9 construct a
  backend class with `__new__` to call its translation methods directly
  (`test_wheel_input:83`, `test_pointer_capture:171`, ...), and several
  monkeypatch `GLFWContext.SwapBuffers` (`test_planar_mirror_gl:223,375`).
  These move to the window system's methods in phase 0/3.
- Source-structure tests read backend files by path and assert which methods
  each class defines: `test_backend_parity.py:41-45,452-453`,
  `test_backend_context_lifecycle.py:29-34`,
  `test_context_definition_resolution.py:81-84`,
  `test_contextresources.py:322-323`, `test_code_health_py2.py:94`. They are
  rewritten to assert the same capabilities against the `WindowSystem`
  classes, which is a stricter check: an abstract method a window system does
  not implement fails at class creation.
- `test_viewer_for_backend.py:20` asserts `issubclass(viewerFor('tk'),
  TkContext)`; becomes an assertion on `windowsystem.name`.
- `test_wglcontext.py:501`, `test_offscreen_backend_choice.py`,
  `test_context_from_config.py`, `test_testingcontext.py` move with the
  registry.
- `tests/helpers/_tk_backend_drive.py:43`, `_glut_init_drive.py:38`,
  `_zone_bake.py:54` subclass backend classes.
- openglcontext-qt: `conftest.py`, `test_application_lifecycle.py`,
  `test_pointer_shape.py:27,38`, `test_window_capabilities.py`,
  `test_surfaceformat.py`, `test_context_gl.py`, `test_events.py`.
- `getInteractive()` appears in 231 places with no argument and 22 with a
  backend name, nearly all in `tests/*.py` demo scripts. They keep working
  unchanged and are not churned: the tutorial scripts are tutorials, and the
  no-argument call answers `Context`.

### Documentation naming backend classes

`docs/offscreen.rst:23-28`, `docs/zones.rst:312-315` (`class
Baker(EGLContext)`), `docs/overlayui.rst:33`, `docs/hud.rst:531`,
`docs/testing.rst:181-183`, `docs/backends.rst:57,144-150,292-312`,
`docs/recording.rst:125`.

### Duck-typed probes that become unconditional

`hasattr(mode.context, 'ProcessEvent')` (`passes/_flat.py:423`,
`passes/asyncpick.py:73`), `getattr(context, 'getViewPlatform'/'platform')`
(`audio/scene.py:149-152`, `viewer/adapters/tiles.py:215`,
`twig-bb/twig_bb/debug.py:220`), `getattr(self, 'movementManager')`
(`move/physicswalk.py`, `viewer/sceneviewer.py`, and three games),
`getattr(..., 'triggerRedraw')` (`passes/reflectionpass.py:233`,
`passes/asyncpick.py:211`). Once every context has these, the probes are
plain attribute access; the ones in the engine are simplified in phase 2.

### Mix-ins combined ahead of the context

`MultiViewMixin` joins `Context`'s bases (see `ContextDefinition.navigation`);
its `super()` chain into `ProcessEvent`, `ViewPort` and
`hasMouseMoveHandlers` is unchanged, since it already sits above the event
and view-platform mix-ins. `SceneViewerMixin` lists it as a base today and
drops it. `OverlayMixin` is the open decision below.

`SceneViewerMixin`, `TerrainWalkMixin`, `RecordingMixin`, `AsyncSceneMixin`
and `EventInjectionMixin` are application-chosen features combined *ahead
of* the context, and they chain through `super()` into `ProcessEvent`,
`ViewPort`, `setPointerCapture`, `OnIdle` and `wantsMoreFrames`. They are out
of scope. What changes for them
is that the methods they chain into are always present below them, so their
`_Host` protocols shrink to "a `Context`". `ScreenMixin`, `ScreenshotMixin`
and `ContextConfigMixin` are already bases of `Context`; the backend
selection in `ContextConfigMixin` moves to `windowsystem.choose()`.

## Decisions

Settled with the maintainer, 2026-09-26:

- Navigation is declared by `ContextDefinition.navigation`, a sub-structure
  naming the registered movement modes in use, whether the user may switch
  them (by keys, by on-screen controls) or only the application may, and the
  views and arrangements, with the same choices for switching those.
- The toolkit's low-level window or widget is `context.window` on every
  backend; embedding applications pack and parent that.
- `ContextMainLoop` remains the entry point.
- The folded mix-ins remain mix-in classes in their own modules, so
  `context.py` does not grow back to the size they were split out of.

Open:

- Whether `OverlayMixin` folds into `Context` as well. `navigation`'s
  `controls` need the overlay stack, and five of the seven applications and
  the viewer already mix it in; the stack is inert until something is pushed
  onto it. Proposed: fold it, which removes the construction-time error for
  `controls` without it and the ordering rule (`OverlayMixin` first) every
  application has to know.

## Progress

Branch `windowsystem`, worktree `openglcontext/.claude/worktrees/windowsystem`.
Run from the worktree with `PYTHONPATH=<worktree>`; GLUT and Tk need
`xvfb-run -a` in the container.

2026-09-26, first session:

- Phase 1 landed: `plugins.WindowSystem`, the `openglcontext.windowsystems`
  entry-point group (read lazily by `windowsystem.registered()`),
  `ContextDefinition.windowsystem`, `windowsystem.choose()`,
  `Context.windowSystemName` applied in `resolveDefinition`, and
  `tests/unit/test_windowsystem_selection.py`.
- Phases 2 and 3 landed together for the seven in-tree window systems, since a
  `Context` that opens its own window system cannot coexist with backend
  classes that open theirs:
  - `OpenGLContext/windowsystem/` holds `base.py` (the `WindowSystem`
    protocol, the shared loop) and `glfw.py`, `glut.py`, `pygame.py`, `tk.py`,
    `wx.py`, `egl.py`, `wgl.py`.  The toolkit translation moved there from
    the `events/*events.py` mix-ins; those modules keep the event classes and
    key tables.
  - `context.py`: the old class body is `ContextCore`;
    `Context(ViewPlatformMixin, EventHandlerMixin, VRMLSceneMixin,
    ContextCore)`.  The split is what lets the mix-ins' `ViewPort`,
    `setupDefaultEventCallbacks` and `hasMouseMoveHandlers` chain into the
    core's through `super()`; `Context`'s own body holds only `emitKey`.  The
    `_Host` declarations cannot name `Context` (a checker would see an
    inheritance cycle), so they stay as short protocols.
  - `EventHandlerMixin` carries the manager table; `interactivecontext` and
    `vrmlcontext.VRMLContext` are aliases.  Font providers load at the first
    `Text` compile (`VRMLSceneMixin.ensureFontProviders`).
  - `Context.__init__(definition=None, *, parent=None, **named)`;
    `completeInit()` runs `OnInit` and sizes the viewport, called by the
    window system for wx (which waits for the canvas to be created).
    `Context.OnIdle` does nothing; the loop draws.
  - The `*context`, `*interactivecontext`, `*vrmlcontext` and
    `*testingcontext` modules are stubs naming `Context` with the window
    system chosen.
  - `testingcontext.getInteractive()` answers `Context`; named, the stub
    class.  `getContextType(s)` and `getVRML` warn.
  - GLFW, EGL, GLUT, pygame and Tk render a scene through the new `Context`
    (GLUT and Tk under Xvfb).  wx and WGL are written but not run here.
- Phase 0 as rewrites rather than first: the tests that drove the old
  mix-ins and backend classes (about 370 failures in 70 files once the source
  moved) now drive the window systems' own methods, over a real `Context`
  made with `__new__` or a small recording host.  The source-structure tests
  (`test_backend_parity`, `test_backend_context_lifecycle`) assert the
  capabilities of the `WindowSystem` classes, with every registered one
  loading and none left abstract.
- Qt (`openglcontext-qt`, branch `windowsystem`, worktree
  `openglcontext-qt/.claude/worktrees/windowsystem`):
  `OpenGLContext_qt/windowsystem.py` holds `QtWindowSystem` and `QtWindow`, a
  `QWindow` whose virtuals hand the events to the window system;
  `qtcontext` is the stub; the package declares
  `[project.entry-points."openglcontext.windowsystems"] qt = ...`.  The
  engine's `try: import OpenGLContext_qt` is gone.  169 tests green.  The
  entry-point group is spelled in lower case, as groups are, and so that
  prose naming it is not read as a module path.
- Consumers inside the engine: `ViewerContext` is an ordinary class
  (`OverlayMixin, SceneViewerMixin, Context`), `viewerFor(name)` pins
  `windowSystemName`; `bin/gltest`, `bin/choosecontext`, `bin/gltf_demo`,
  `bin/profile_view`, `bin/keyboardevents`, the Tk and wx embedding demos;
  `testing/glcontext` imports from `windowsystem.egl`.
  `scripts/writeplugins.py` is deleted.  `Context.fromConfig` sets the
  field from `[context] gui`.
- openglcontext-editor (branch `windowsystem`, worktree
  `openglcontext-editor/.claude/worktrees/windowsystem`): the zone-probe
  `Baker` is `Context` with `windowSystemName = 'offscreen'`, so the bake runs
  on Windows as well.
- Defects the fold exposed, fixed: every context now loads the TrueType
  providers, so `Text` draws with `ToolsSolidFont` where interactive contexts
  drew with the bitmap font; that font made a vertex array every frame, kept
  one glyph buffer for the whole process (a second context's first frame was
  `GL_INVALID_OPERATION`), and was culled inside out under a mirroring
  transform.  Its buffer and vertex array are now per context
  (`contextresources.ContextNames`), made once, and it follows the winding
  (`winding.apply_winding_cull`).  A font built directly loads the registry
  on first use (`TTFFontProvider.getTTFRegistry`).  `getTTFFiles` moved to
  `ContextConfigMixin`, which is sanctioned in the open audit as a reader of
  the user's own files.
- Documentation: `docs/backends.rst` is rewritten as *Window Systems*
  (choosing one, the classes, writing one); `embedding`, `offscreen`,
  `environment`, `eventmodel`, `profiles`, `structure`, `documentation`,
  `viewer`, `zones`, `overlayui` and `testing` follow; CLAUDE.md's directory
  map and `OPENGLCONTEXT_BACKEND` section; the Qt README.
- Gates in the worktree: ruff, oglc-check, mypy (from `.preflight-venv`,
  whole package) clean; the full suite green in both passes (12621 and 16).
  The sibling suites, run by `verify-everything.py` against the three
  worktrees (a `PYTHONPATH` of the packages alone -- the engine worktree's
  root would put its own `tests` package ahead of theirs), are green:
  openglcontext-editor 1478, forest 66, marble-demo 896, marble-editor 162,
  glisteel 1638, glisteel-editor 469, twig-bb 2355.

Still to do:

- The script suite (`tests/test_all_scripts.py`, every script's frame
  against its reference image) passes from the worktree with `PYTHONPATH`
  set, which the subprocesses inherit.  Run it again on the main checkout
  with the merge staged, as preflight does, before the merge is committed.
- wx and WGL: written against their APIs, not run here; their CI jobs are
  the gate.
- Phase 2b (navigation from the definition) -- not started.  It folds the
  classic `smooth.Smooth` manager into an `examine` movement mode, which
  touches `PhysicsWalkMixin.enablePhysics` (it unbinds and rebinds that
  manager), the viewer's `g`/`m` keys and every game; worth doing as its own
  change.
- Phase 4 for the games (forest, twig-bb, glisteel, glisteel-editor,
  marble-demo, marble-editor): they keep working unchanged, since
  `getInteractive()` answers `Context`; moving them to `class Game(Context)`
  with the window system in the definition is still to do.
- Phase 6 (removal of the old registries and `getContextType`) is a release
  later.
