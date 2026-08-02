"""OpenGLContext plugin classes"""
from OpenGL import plugins
from OpenGL._bytes import bytes, unicode

class Context( plugins.Plugin ):
    """Data-type storage-format handler"""
    registry = []
    type_key = 'context'
    @classmethod
    def match( cls, key ):
        """Determine what platform module to load
        
        key -- name of GUI system for which to load
        """
        if isinstance( key, (bytes,unicode)):
            key = [key]
        for plugin in cls.registry:
            if plugin.name in key:
                return plugin
        raise KeyError( """No %s plugin registered for any of %s"""%(cls.__name__, key,))

class InteractiveContext( Context ):
    """Interaction-providing context"""
    type_key = 'interactive'
    registry = []

class VRMLContext( InteractiveContext ):
    """VRML parser/rendering context"""
    registry = []
    type_key = 'vrml'

class Loader( plugins.Plugin ):
    """A data-format loader (e.g. vrml97 or obj)"""
    registry = []
    @classmethod
    def match( cls, key ):
        """Determine what platform module to load
        
        key -- file-extension or mime-type to load from
        """
        if isinstance( key, (bytes,unicode)):
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
    registry = []
    type_key = 'adapter'

class Node( plugins.Plugin ):
    """A particular scenegraph node to be rendered"""
    registry = []
