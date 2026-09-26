"""OpenGLContext plugin classes"""
from collections.abc import Iterable, Sequence
from importlib import metadata
from typing import ClassVar, Union

from OpenGL import plugins
from OpenGL.plugins import importByName

__all__ = [
    'Adapter', 'Context', 'InteractiveContext', 'Loader', 'MovementMode',
    'Node', 'VRMLContext', 'ViewGestures', 'WindowSystem', 'discover',
    'importByName',
]

#: What :meth:`Context.match` and :meth:`Loader.match` will search for: one
#: name, or a sequence of names any of which will do.
Key = bytes | str | Sequence[object]


class Context( plugins.Plugin ):
    """Data-type storage-format handler"""
    registry: ClassVar[list[plugins.Plugin]] = []
    type_key = 'context'
    @classmethod
    def match( cls, key: Key ) -> plugins.Plugin:
        """Determine what platform module to load

        key -- name of GUI system for which to load
        """
        if isinstance( key, (bytes,str)):
            key = [key]
        for plugin in cls.registry:
            if plugin.name in key:
                return plugin
        raise KeyError( """No %s plugin registered for any of %s"""%(cls.__name__, key,))

class InteractiveContext( Context ):
    """Interaction-providing context"""
    type_key = 'interactive'
    registry: ClassVar[list[plugins.Plugin]] = []

class VRMLContext( InteractiveContext ):
    """VRML parser/rendering context"""
    registry: ClassVar[list[plugins.Plugin]] = []
    type_key = 'vrml'

class WindowSystem( plugins.Plugin ):
    """A window system a context can open on (glfw, glut, egl, ...)

    Names a :class:`OpenGLContext.windowsystem.WindowSystem` subclass by its
    dotted path, so the toolkit behind it is imported only when a context asks
    for it by name.  A package outside the engine registers one through the
    ``openglcontext.windowsystems`` entry-point group; see
    :func:`OpenGLContext.windowsystem.registered`.
    """
    registry: ClassVar[list[plugins.Plugin]] = []
    type_key = 'windowsystem'

class MovementMode( plugins.Plugin ):
    """A way of moving a camera (walk, fly, examine, ...), by name

    Names a factory, ``factory(scale=1.0)``, that makes a new
    :class:`OpenGLContext.move.modes.MovementMode` node, so a navigation
    declaration can say ``modes=['walk', 'fly']``.  A game registers its own
    at import, or through the ``openglcontext.movementmodes`` entry-point
    group; see :func:`OpenGLContext.move.navigationdefinition.movementMode`.
    """
    registry: ClassVar[list[plugins.Plugin]] = []
    type_key = 'movementmode'

class ViewGestures( plugins.Plugin ):
    """What the pointer does in one view (plan, examine, ...), by name

    Names a factory, ``factory()``, that makes a new
    :class:`OpenGLContext.multiview.navigation.ViewNavigationMode`.  An editor
    registers its own at import, or through the ``openglcontext.viewgestures``
    entry-point group.
    """
    registry: ClassVar[list[plugins.Plugin]] = []
    type_key = 'viewgestures'

#: The registries whose entry points have been read, and so are not read again.
_DISCOVERED: set[str] = set()

def _entryPoints( group: str ) -> Iterable[metadata.EntryPoint]:
    """The installed distributions' entry points in ``group``"""
    return metadata.entry_points( group=group )

def discover( registry: type[plugins.Plugin], group: str ) -> None:
    """Register what installed distributions declare in the entry-point ``group``

    Read once per group, from the distributions' metadata and without
    importing them; a name already registered keeps its registration.  A
    value ``package.module:name`` is registered as the dotted path
    ``package.module.name``.
    """
    if group in _DISCOVERED:
        return
    _DISCOVERED.add( group )
    known = { plugin.name for plugin in registry.all() }
    for entry in _entryPoints( group ):
        if entry.name not in known:
            registry( entry.name, entry.value.replace( ':', '.' ) )
            known.add( entry.name )

class Loader( plugins.Plugin ):
    """A data-format loader (e.g. vrml97 or obj)"""
    registry: ClassVar[list[plugins.Plugin]] = []
    @classmethod
    def match( cls, key: Key ) -> plugins.Plugin:
        """Determine what platform module to load

        key -- file-extension or mime-type to load from
        """
        if isinstance( key, (bytes,str)):
            key = [key]
        for plugin in cls.registry:
            if plugin.name in key:
                return plugin
        raise KeyError( """No %s plugin registered for any of %s"""%(cls.__name__, key,))

class Adapter( plugins.Plugin ):
    """A viewer scene adapter (e.g. gltf, vrml97 or tiles3d)

    Registered against the file suffixes and content types it opens, so
    ``oglc-view`` picks one from the source rather than from which command was
    typed, and a third party adds a format without editing the viewer.  See
    OpenGLContext.viewer.adapters.
    """
    registry: ClassVar[list[plugins.Plugin]] = []
    type_key = 'adapter'

class Node( plugins.Plugin ):
    """A particular scenegraph node to be rendered"""
    registry: ClassVar[list[plugins.Plugin]] = []
