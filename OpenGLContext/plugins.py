"""OpenGLContext plugin classes"""
from typing import List, Sequence, Union

from OpenGL import plugins

#: What :meth:`Context.match` and :meth:`Loader.match` will search for: one
#: name, or a sequence of names any of which will do.
Key = Union[bytes, str, Sequence[object]]


class Context( plugins.Plugin ):
    """Data-type storage-format handler"""
    registry: List[plugins.Plugin] = []
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
    registry: List[plugins.Plugin] = []

class VRMLContext( InteractiveContext ):
    """VRML parser/rendering context"""
    registry: List[plugins.Plugin] = []
    type_key = 'vrml'

class Loader( plugins.Plugin ):
    """A data-format loader (e.g. vrml97 or obj)"""
    registry: List[plugins.Plugin] = []
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
    registry: List[plugins.Plugin] = []
    type_key = 'adapter'

class Node( plugins.Plugin ):
    """A particular scenegraph node to be rendered"""
    registry: List[plugins.Plugin] = []
