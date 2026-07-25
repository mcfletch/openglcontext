"""Definition of a Context's visual parameters"""
import os
from vrml import node, field


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


def _get_default_picking():
    """Whether colour-based scenegraph picking is enabled by default.

    Disabled when OPENGLCONTEXT_PICKING is set to a falsey value
    (0/off/false/no). Turning picking off skips the selection render, the MRT
    id/depth buffer and its readback -- useful for headless capture or any
    context that never queries object ids.
    """
    value = os.environ.get('OPENGLCONTEXT_PICKING')
    if value is None:
        return True
    return value.strip().lower() not in ('0', 'off', 'false', 'no', '')


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

    #: Movement modes this context offers, as nodes (see
    #: :mod:`OpenGLContext.move.modes`).  Declared rather than hard-coded so a
    #: game states which ways of moving it has and how each is tuned.
    movementModes = field.newField( 'movementModes', 'MFNode', 1, list )
    #: The mode in force right now.  Written by the navigation manager and
    #: watchable like any field, so a game can react to entering water without
    #: the manager knowing anything about it.
    movementMode = field.newField( 'movementMode', 'SFNode', 1, node.NULL )


    # optional buffers...
    doubleBuffer = field.newField( "doubleBuffer", "SFBool", 1, True)

    depthBuffer = field.newField( "depthBuffer", "SFInt32", 1, -1)
    accumulationBuffer = field.newField( "accumulationBuffer", "SFInt32", 1, -1)
    stencilBuffer = field.newField( "stencilBuffer", "SFInt32", 1, 8)

    # together these define the  colour format for the buffer
    rgb = field.newField( "rgb", "SFBool", 1, True)
    alpha = field.newField( "alpha", "SFBool", 1, False)

    multisampleBuffer = field.newField( "multisampleBuffer", "SFInt32", 1, -1)
    multisampleSamples = field.newField( "multisampleSamples", "SFInt32", 1, -1)
    stereo = field.newField( "stereo", "SFInt32", 1, -1)

    debugBBox = field.newField( "debugBBox", "SFBool", 1, False )
    debugSelection = field.newField( "debugSelection", "SFBool", 1, False )
    debug = field.newField( 'debug', 'SFBool', 1, False )

    # Colour-based scenegraph picking. When false the selection render, MRT
    # object-id buffer and its readback are all skipped (env: OPENGLCONTEXT_PICKING).
    pickEnabled = field.newField( "pickEnabled", "SFBool", 1, _get_default_picking() )

    # Non-blocking pick readback: read the MRT object-id/depth under each pick
    # sample into a PBO with a fence instead of a synchronous glReadPixels, and
    # dispatch the resolved events a frame later. Avoids the GPU->CPU stall so
    # picking can run every frame (on-move painting). False = synchronous readback.
    pickAsync = field.newField( "pickAsync", "SFBool", 1, True )

    # OpenGL profile selection - can be overridden by OPENGLCONTEXT_PROFILE env var
    # "core" requires GLFW or another backend that supports core profile contexts
    profile = field.newField( "profile", "SFString", 1, _get_default_profile() )
    version = field.newField( "version", "SFVec2f", 1, _get_default_version())

    @classmethod
    def fromConfig( cls, cfg, section='contextdefinition' ):
        """Generate a ContextDefinition from a ConfigParser instance"""
        from vrml import protofunctions
        instance = cls()
        for definition in protofunctions.getFields( cls ):
            if cfg.has_option( section, definition.name ):
                setattr( instance, definition.name,
                         cfg.get( section, definition.name ))
        return instance

