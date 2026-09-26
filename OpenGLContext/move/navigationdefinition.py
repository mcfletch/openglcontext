"""How a context is moved through and looked at, declared on its definition

``ContextDefinition.navigation`` holds a :class:`Navigation`: the movement
modes in use, the views and how they are arranged, and for each whether the
user may switch it -- by keys, by on-screen controls -- or only the
application.  The same game can then ship a player's definition and an
editor's over one scene::

    Navigation(modes=['fps', 'fps-swim', 'fly'], modeSwitching=[])

    Navigation(
        modes=['examine', 'fly', 'walk'], modeSwitching=['keys', 'controls'],
        views=Views(
            views=[ViewDefinition(name='top', camera='top', gestures=['plan']),
                   ViewDefinition(name='perspective')],
            arrangements=[Arrangement(name='split', views=['top', 'perspective'])],
            switching=['keys', 'controls']),
    )

A *name* where a mode is expected is looked up among the registered movement
modes (:func:`movementMode`) and replaced by the node that registration makes;
a node is taken as it is.  A mode is a node because it carries per-mode
settings -- speeds, sensitivity, the player's rebound keys -- which the
settings screen edits and saves.

Declarations only: no GL and no events.  What reads them is
:class:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin` (the modes)
and :class:`~OpenGLContext.multiview.mixin.MultiViewMixin` (the views).  See
``docs/navigation.rst``.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, ClassVar, Optional

from vrml import field, node

from OpenGLContext import plugins

__all__ = (
    'Arrangement',
    'CAMERAS',
    'MOVEMENT_MODE_ENTRY_POINTS',
    'Navigation',
    'ORTHOGRAPHIC',
    'SPEED_FIELDS',
    'SWITCHING',
    'VIEW_GESTURE_ENTRY_POINTS',
    'ViewDefinition',
    'Views',
    'defaultNavigation',
    'movementMode',
    'registeredGestures',
    'registeredModes',
    'viewGestures',
)

#: How the *user* may switch a mode or an arrangement: ``keys`` binds keys for
#: it, ``controls`` puts on-screen controls up for it.  Neither, and only the
#: application switches it.
SWITCHING = ('keys', 'controls')

#: The orthographic cameras, each looking along one axis.
ORTHOGRAPHIC = ('top', 'front', 'left', 'right', 'back', 'bottom')

#: The camera kinds a view can have: the context's own perspective camera
#: (driven by the movement modes), one of :data:`ORTHOGRAPHIC`, or ``scene``,
#: looking through the scene's bound ``Viewpoint`` or glTF camera.
CAMERAS = ('perspective', *ORTHOGRAPHIC, 'scene')

#: The fields a movement mode's speeds are held in, which :meth:`Navigation.scaled`
#: multiplies.
SPEED_FIELDS = ('walkSpeed', 'runSpeed', 'flySpeed', 'boostSpeed', 'swimSpeed')

#: The entry-point groups a distribution registers movement modes and view
#: gestures in, as ``name = "package.module:factory"``.
MOVEMENT_MODE_ENTRY_POINTS = 'openglcontext.movementmodes'
VIEW_GESTURE_ENTRY_POINTS = 'openglcontext.viewgestures'


def _checkSwitching(ways: Iterable[str], what: str) -> None:
    unknown = [way for way in ways if way not in SWITCHING]
    if unknown:
        raise ValueError(
            '%s can be switched by %s; not %s'
            % (what, ' or '.join(SWITCHING), ', '.join(repr(way) for way in unknown)))


# -- the registries -----------------------------------------------------------

def registeredModes() -> tuple[str, ...]:
    """The registered movement-mode names, in registration order."""
    plugins.discover(plugins.MovementMode, MOVEMENT_MODE_ENTRY_POINTS)
    return tuple(plugin.name for plugin in plugins.MovementMode.all())


def registeredGestures() -> tuple[str, ...]:
    """The registered view-gesture names, in registration order."""
    plugins.discover(plugins.ViewGestures, VIEW_GESTURE_ENTRY_POINTS)
    return tuple(plugin.name for plugin in plugins.ViewGestures.all())


def _factory(registry: type[plugins.Plugin], name: str,
             registered: Sequence[str], kind: str) -> Any:
    if name not in registered:
        raise KeyError('No %s is registered as %r; registered: %s'
                       % (kind, name, ', '.join(registered) or 'none'))
    plugin = registry.by_name(name)
    assert plugin is not None
    return plugins.importByName(plugin.import_path)


def movementMode(name: str, scale: float = 1.0) -> Any:
    """A new :class:`~OpenGLContext.move.modes.MovementMode` for ``name``.

    ``scale`` sizes its speeds to the world, as the avatar is sized.  Raises
    KeyError naming the registered modes where ``name`` is not one.
    """
    factory = _factory(plugins.MovementMode, name, registeredModes(),
                       'movement mode')
    return factory(scale=scale)


def viewGestures(name: str) -> Any:
    """A new :class:`~OpenGLContext.multiview.navigation.ViewNavigationMode`
    for ``name``; KeyError naming the registered ones where it is not one."""
    factory = _factory(plugins.ViewGestures, name, registeredGestures(),
                       'view gesture set')
    return factory()


# -- the declarations ---------------------------------------------------------

class Arrangement(node.Node):
    """A named layout: the views it shows, by name.

    One view fills the window, two sit side by side, four make a quad.
    """

    PROTO = 'Arrangement'
    name = field.newField('name', 'SFString', 1, '')
    views = field.newField('views', 'MFString', 1, list)


class ViewDefinition(node.Node):
    """One view: what it looks through and what the pointer does in it.

    ``camera`` is one of :data:`CAMERAS`.  ``gestures`` names registered view
    gesture sets (``plan``, ``examine``); what they bind is combined, and a
    perspective view with none is moved by the movement modes.  ``style`` is
    ``flat`` (a plain background with a grid) or ``scene`` (the scene's own
    background); empty takes ``flat`` for an orthographic camera and ``scene``
    otherwise.
    """

    PROTO = 'ViewDefinition'
    name = field.newField('name', 'SFString', 1, '')
    camera = field.newField('camera', 'SFString', 1, 'perspective')
    gestures = field.newField('gestures', 'MFString', 1, list)
    style = field.newField('style', 'SFString', 1, '')

    #: What ``style`` may say.
    STYLES: ClassVar[tuple[str, ...]] = ('', 'flat', 'scene')

    def __init__(self, **named: Any) -> None:
        super().__init__(**named)
        if self.camera not in CAMERAS:
            raise ValueError('A view looks through one of %s; not %r'
                             % (', '.join(CAMERAS), self.camera))
        if self.style not in self.STYLES:
            raise ValueError('A view is styled flat or scene; not %r' % (self.style,))
        registered = registeredGestures()
        for gesture in self.gestures:
            if gesture not in registered:
                raise KeyError('No view gesture set is registered as %r; '
                               'registered: %s' % (gesture, ', '.join(registered)))

    def flat(self) -> bool:
        """Whether this view draws a plain background with a grid."""
        return (self.style == 'flat'
                or (not self.style and self.camera in ORTHOGRAPHIC))


class Views(node.Node):
    """The views a window shows, their arrangements, and who switches them.

    ``arrangement`` is the one shown at start, empty for the first declared.
    With no arrangements declared, each view is offered alone under its own
    name, the first two together as ``split`` and the first four as ``quad``.
    """

    PROTO = 'Views'
    views = field.newField('views', 'MFNode', 1, list)
    arrangements = field.newField('arrangements', 'MFNode', 1, list)
    arrangement = field.newField('arrangement', 'SFString', 1, '')
    switching = field.newField('switching', 'MFString', 1, list)

    def __init__(self, **named: Any) -> None:
        super().__init__(**named)
        _checkSwitching(self.switching, 'An arrangement')
        declared = [view.name for view in self.views]
        for arrangement in self.arrangements:
            missing = [name for name in arrangement.views if name not in declared]
            if missing:
                raise ValueError(
                    'The %r arrangement shows %s, which %s not declared'
                    % (arrangement.name, ', '.join(missing),
                       'is' if len(missing) == 1 else 'are'))
            if len(arrangement.views) not in (1, 2, 4):
                raise ValueError(
                    'An arrangement places one, two or four views; %r names %d'
                    % (arrangement.name, len(arrangement.views)))
        if self.arrangement and self.arrangement not in self.arrangementViews():
            raise ValueError('There is no %r arrangement; declared: %s'
                             % (self.arrangement, ', '.join(self.arrangementViews())))

    def arrangementViews(self) -> dict[str, tuple[str, ...]]:
        """Each arrangement's name, and the names of the views it shows."""
        if self.arrangements:
            return {str(arrangement.name): tuple(arrangement.views)
                    for arrangement in self.arrangements}
        names = [str(view.name) for view in self.views]
        offered = {name: (name,) for name in names}
        if len(names) >= 2:
            offered['split'] = tuple(names[:2])
        if len(names) >= 4:
            offered['quad'] = tuple(names[:4])
        return offered


def _resolvedModes(modes: Iterable[Any]) -> list[Any]:
    """``modes`` with every name replaced by the node its registration makes"""
    return [movementMode(mode) if isinstance(mode, str) else mode for mode in modes]


class Navigation(node.Node):
    """The movement modes a context has, its views, and who switches them.

    ``modes`` are the ways the perspective camera can move; ``mode`` the one
    selected at start (empty for the first selectable); ``current`` the one in
    force, written by the navigation manager; ``modeSwitching`` how the *user*
    may change it -- the application always can, through
    ``context.getNavigation().select(name)`` and ``cycle()``, and a mode the
    world imposes (swimming) applies regardless.  ``views`` is a
    :class:`Views`, or NULL for one full-window perspective view.
    """

    PROTO = 'Navigation'
    modes = field.newField('modes', 'MFNode', 1, list)
    mode = field.newField('mode', 'SFString', 1, '')
    current = field.newField('current', 'SFNode', 1, node.NULL)
    modeSwitching = field.newField('modeSwitching', 'MFString', 1, list)
    views = field.newField('views', 'SFNode', 1, node.NULL)

    #: Published rather than chosen, so never carried in a settings draft: the
    #: navigation manager writes ``current`` every frame.
    TRANSIENT_FIELDS: ClassVar[tuple[str, ...]] = ('current',)

    def __init__(self, **named: Any) -> None:
        if 'modes' in named:
            named['modes'] = _resolvedModes(named['modes'])
        super().__init__(**named)
        _checkSwitching(self.modeSwitching, 'A movement mode')

    def scaled(self, scale: float) -> Navigation:
        """A copy whose modes move ``scale`` times as fast.

        For a world bigger or smaller than a person: the modes are copied and
        each one's speeds (:data:`SPEED_FIELDS`) multiplied, and this
        navigation is left as it is, so scaling from it again does not
        compound.
        """
        modes = []
        for mode in self.modes:
            copied = mode.copy()
            for name in SPEED_FIELDS:
                if hasattr(copied, name):
                    setattr(copied, name, float(getattr(mode, name)) * scale)
            modes.append(copied)
        return Navigation(modes=modes, mode=self.mode,
                          modeSwitching=list(self.modeSwitching),
                          views=self.views)

    def examines(self) -> bool:
        """Whether the classic arrow-key and drag navigation is declared."""
        from OpenGLContext.move.modes import ExamineMode

        return any(isinstance(mode, ExamineMode) for mode in self.modes)

    def movingModes(self) -> list[Any]:
        """The declared modes that move a body: every mode but ``examine``."""
        from OpenGLContext.move.modes import ExamineMode

        return [mode for mode in self.modes if not isinstance(mode, ExamineMode)]

    def setMovingModes(self, modes: Iterable[Any]) -> None:
        """Declare ``modes`` as the ones that move a body, names or nodes.

        The classic navigation stays declared where it was, so a context that
        learns what it can walk with once a world has loaded keeps its
        free-fly camera.
        """
        from OpenGLContext.move.modes import ExamineMode

        kept = [mode for mode in self.modes if isinstance(mode, ExamineMode)]
        self.modes = kept + _resolvedModes(modes)


def defaultNavigation() -> Navigation:
    """What a context that declares nothing gets: the classic navigation, one view"""
    return Navigation(modes=['examine'])


def navigationFromNames(names: Optional[str]) -> Navigation:
    """A navigation from a configuration file's comma-separated mode names"""
    return Navigation(modes=[name.strip() for name in (names or '').split(',')
                             if name.strip()])
