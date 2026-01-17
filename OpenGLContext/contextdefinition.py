"""Definition of a Context's visual parameters"""
import os
from vrml.vrml97 import nodetypes
from vrml import node, field, fieldtypes
from OpenGL import GL


def _get_default_profile():
    """Get the default OpenGL profile from environment or fallback to compatibility.

    Environment variable OPENGLCONTEXT_PROFILE can be set to:
        - "core" for OpenGL 3.3+ core profile (shader-based rendering)
        - "compatibility" for legacy fixed-function rendering (default)

    When using core profile, OPENGLCONTEXT_BACKEND should typically be set to
    a backend that supports core profile contexts (e.g., "glfw").
    """
    return os.environ.get('OPENGLCONTEXT_PROFILE', 'compatibility')


def _get_default_version():
    """Get the default OpenGL version based on profile.

    Core profile requires at least OpenGL 3.2. Returns (3, 3) for core profile,
    (0, 0) for compatibility (let the driver choose).
    """
    profile = _get_default_profile()
    if profile == 'core':
        return (3, 3)
    return (0, 0)


class ContextDefinition( node.Node ):
    """Node which defines required parameters for creating a visual context

    Values of -1 generally indicate "choose the default", while
    values > -1 will explicitly request the value be set.

    The profile and version fields control OpenGL context creation:

    profile -- "core" or "compatibility"
        - "core": Use OpenGL 3.3+ core profile with shader-based rendering
        - "compatibility": Use legacy fixed-function pipeline (default)

        Can be overridden by OPENGLCONTEXT_PROFILE environment variable.

    version -- (major, minor) OpenGL version tuple
        - (0, 0): Let the driver choose (default for compatibility)
        - (3, 3): Minimum for core profile

        Automatically set to (3, 3) when profile is "core" and version is (0, 0).
    """
    PROTO = 'ContextDefinition'
    size = field.newField( "size", "SFVec2f", 1, (300,300))
    title = field.newField( "title", "SFString", 1, "")
    profileFile = field.newField( "profileFile", 'SFString',1,"")

    # optional buffers...
    doubleBuffer = field.newField( "doubleBuffer", "SFBool", 1, True)

    depthBuffer = field.newField( "depthBuffer", "SFInt32", 1, -1)
    accumulationBuffer = field.newField( "accumulationBuffer", "SFInt32", 1, -1)
    stencilBuffer = field.newField( "stencilBuffer", "SFInt32", 1, 8)

    # together these define the  colour format for the buffer
    rgb = field.newField( "rgb", "SFBool", 1, True)
    alpha = field.newField( "alpha", "SFBool", 1, True)

    multisampleBuffer = field.newField( "multisampleBuffer", "SFInt32", 1, -1)
    multisampleSamples = field.newField( "multisampleSamples", "SFInt32", 1, -1)
    stereo = field.newField( "stereo", "SFInt32", 1, -1)

    debugBBox = field.newField( "debugBBox", "SFBool", 1, False )
    debugSelection = field.newField( "debugSelection", "SFBool", 1, False )
    debug = field.newField( 'debug', 'SFBool', 1, False )

    # OpenGL profile selection - can be overridden by OPENGLCONTEXT_PROFILE env var
    # "core" requires GLFW or another backend that supports core profile contexts
    profile = field.newField( "profile", "SFString", 1, _get_default_profile() )
    version = field.newField( "version", "SFVec2f", 1, _get_default_version())

    @classmethod
    def fromConfig( cls, cfg, section='contextdefinition' ):
        """Generate a ContextDefinition from a ConfigParser instance"""
        from vrml import protofunctions
        instance = cls()
        for field in protofunctions.getFields( cls ):
            if cfg.has_option( section, field.name ):
                setattr( instance, field.name, cfg.get( section, field.name ))
        return instance

