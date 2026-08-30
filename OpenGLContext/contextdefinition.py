"""Definition of a Context's visual parameters"""
import os
from vrml import node, field

from OpenGLContext import renderoptions
from OpenGLContext.audio import settings as audiosettings


# The three helpers below are passed to ``newField`` **uncalled**, so each is
# evaluated the first time a definition is asked for that field rather than
# when this module is imported.  An import-time read freezes whatever the
# environment happened to hold when the first module to import this one was
# loaded -- which no application, and no test, can reach afterwards.


def _get_default_profile():
    """The OpenGL profile a context gets when nothing asks for one.

    ``core`` -- OpenGL 3.3 core, rendered through shaders.  It is the default
    because it is what the engine draws with: :class:`PBRMesh`, and so the glTF
    loader and every generator built on it, is shader-only, and the
    fixed-function pipeline a compatibility profile exists for is absent from
    core contexts, from macOS 3.2 and above, from GLES, and from drivers that
    offer core alone.

    ``compatibility`` -- the fixed-function pipeline, for a program that draws
    with ``glBegin``, the matrix stack, display lists, ``glMaterial``/``glLight``
    or GLSL's ``gl_ModelViewProjectionMatrix``.  Fully supported; it is only no
    longer what a caller gets for free.  ``OPENGLCONTEXT_PROFILE`` names it for
    a run, and a program that needs it declares ``profile = 'compatibility'``
    on its context class.  See :meth:`OpenGLContext.context.Context.profile`.
    """
    return os.environ.get('OPENGLCONTEXT_PROFILE', 'core')


def version_for_profile(profile):
    """The OpenGL version a context of ``profile`` needs, unless told otherwise.

    Core profile requires at least OpenGL 3.2; the shaders here target 3.3.
    (0, 0) means "let the driver choose", which is what a compatibility context
    wants: asking for a version there only narrows what the driver may give.
    """
    return (3, 3) if profile == 'core' else (0, 0)


def _get_default_version():
    """The version field's default, from the profile the environment names."""
    return version_for_profile(_get_default_profile())


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

    #: Fill the screen rather than open a window of ``size``
    #: (env: ``OPENGLCONTEXT_FULLSCREEN``).  A game normally wants this and a
    #: tool normally does not, so it is the application's choice rather than
    #: the launcher's.  ``OPENGLCONTEXT_HIDDEN`` outranks it: a window that is
    #: not meant to appear cannot fill the screen, and a capture subprocess
    #: that tried would take the display from whoever started it.
    #: See :meth:`OpenGLContext.context.Context.setFullscreen`.
    fullscreen = field.newField( "fullscreen", "SFBool", 1,
                                 lambda: renderoptions.env_flag('OPENGLCONTEXT_FULLSCREEN', False))

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
    pickEnabled = field.newField( "pickEnabled", "SFBool", 1, _get_default_picking )

    # Non-blocking pick readback: read the MRT object-id/depth under each pick
    # sample into a PBO with a fence instead of a synchronous glReadPixels, and
    # dispatch the resolved events a frame later. Avoids the GPU->CPU stall so
    # picking can run every frame (on-move painting). False = synchronous readback.
    pickAsync = field.newField( "pickAsync", "SFBool", 1, True )

    # OpenGL profile selection - can be overridden by OPENGLCONTEXT_PROFILE env var
    # "core" requires GLFW or another backend that supports core profile contexts
    profile = field.newField( "profile", "SFString", 1, _get_default_profile )
    version = field.newField( "version", "SFVec2f", 1, _get_default_version )

    # -- rendering features -------------------------------------------------
    # Everything below was reachable only through an environment variable read
    # deep inside a render pass, which meant it could be set before the process
    # started and shown to a player never. They are fields so a settings screen
    # can offer them; the environment variable is still the field's *default*,
    # so a script or a CI run pins one exactly as before. Read through
    # :mod:`OpenGLContext.renderoptions`, which is where the passes ask.

    #: Shadow maps (env: OPENGLCONTEXT_SHADOWS). The single most expensive
    #: feature, and the first thing to turn off on a weak GPU.
    shadows = field.newField( "shadows", "SFBool", 1,
                              lambda: renderoptions.env_flag('OPENGLCONTEXT_SHADOWS', True))
    #: PCSS contact-hardening shadows: softer and dearer than the default
    #: filter (env: OPENGLCONTEXT_SHADOWS_SOFT).
    shadowsSoft = field.newField( "shadowsSoft", "SFBool", 1,
                                  lambda: renderoptions.env_flag('OPENGLCONTEXT_SHADOWS_SOFT', False))
    #: Cascades rendered for a directional light: more is crisper at distance.
    #: 0 lets the pass choose from VRAM and frame rate; a fixed value makes
    #: shadow output reproducible (env: OPENGLCONTEXT_SHADOW_CASCADES).
    shadowCascades = field.newField( "shadowCascades", "SFInt32", 1,
                                     lambda: int(renderoptions.env_number('OPENGLCONTEXT_SHADOW_CASCADES', 0, integer=True)))
    #: Lights the shader will bind in one frame. Lower is faster in a scene
    #: with many lights; the shader's own ceiling still applies.
    #: (env: OPENGLCONTEXT_MAXIMUM_LIGHTS)
    maximumLights = field.newField( "maximumLights", "SFInt32", 1,
                                    lambda: int(renderoptions.env_number('OPENGLCONTEXT_MAXIMUM_LIGHTS', 8, integer=True)) )

    #: HDR bloom post-process (env: OPENGLCONTEXT_BLOOM).
    bloom = field.newField( "bloom", "SFBool", 1,
                            lambda: renderoptions.env_flag('OPENGLCONTEXT_BLOOM', False))
    #: Image-based lighting: "auto", "full", "analytic" or "off"
    #: (env: OPENGLCONTEXT_IBL). "auto" degrades itself on a software
    #: rasteriser, where the prefilter precompute is too slow.
    ibl = field.newField( "ibl", "SFString", 1,
                          lambda: renderoptions.env_choice(
                              'OPENGLCONTEXT_IBL', renderoptions.CHOICES['ibl'],
                              {'on': 'full', '1': 'full', 'approx': 'analytic',
                               'analytical': 'analytic', 'none': 'off', '0': 'off'}))
    #: Scales the un-shadowed ambient/environment term; below 1.0 lets a
    #: shadow-casting key light read clearly (env: OPENGLCONTEXT_IBL_INTENSITY).
    iblIntensity = field.newField( "iblIntensity", "SFFloat", 1,
                                   lambda: renderoptions.env_number('OPENGLCONTEXT_IBL_INTENSITY', 1.0))
    #: Refraction through glass: "auto", "full", "blend" or "off"
    #: (env: OPENGLCONTEXT_TRANSMISSION).
    transmission = field.newField( "transmission", "SFString", 1,
                                   lambda: renderoptions.env_choice(
                                       'OPENGLCONTEXT_TRANSMISSION',
                                       renderoptions.CHOICES['transmission'],
                                       {'on': 'full', '1': 'full', 'fake': 'blend',
                                        'none': 'off', '0': 'off'}))
    #: Collapse shapes sharing one geometry into a single instanced draw
    #: (env: OPENGLCONTEXT_INSTANCING).
    instancing = field.newField( "instancing", "SFBool", 1,
                                 lambda: renderoptions.env_flag('OPENGLCONTEXT_INSTANCING', True))
    #: Skin a rigged figure in the vertex shader rather than on the CPU
    #: (env: OPENGLCONTEXT_GPU_SKINNING). Off puts the deform back on the CPU,
    #: which is the reference the shader path is measured against.
    gpuSkinning = field.newField( "gpuSkinning", "SFBool", 1,
                                  lambda: renderoptions.env_flag('OPENGLCONTEXT_GPU_SKINNING', True))
    #: Distance level-of-detail for procedurally tessellated geometry --
    #: teapots, quadrics, NURBS (env: OPENGLCONTEXT_LOD).
    tessellationLOD = field.newField( "tessellationLOD", "SFBool", 1,
                                      lambda: renderoptions.env_flag('OPENGLCONTEXT_LOD', True))
    #: Wait for the display's refresh before presenting a frame. Off uncaps the
    #: frame rate and lets a benchmark measure it (env: OPENGLCONTEXT_NO_VSYNC).
    vsync = field.newField( "vsync", "SFBool", 1,
                            lambda: not renderoptions.env_flag('OPENGLCONTEXT_NO_VSYNC', False))
    #: Sound, as the player controls it: whether it plays, how loud, and how
    #: many voices.  A sub-node rather than loose fields because sound has more
    #: than one knob and they belong together -- the same reasoning as
    #: ``movementModes``.  See :mod:`OpenGLContext.audio.settings`.
    audio = field.newField( "audio", "SFNode", 1, audiosettings.AudioSettings )

    #: How large the overlay interface is drawn, on top of the size the window's
    #: height already asks for: 1 leaves it alone, 2 doubles it.  A player with
    #: a 4K display already gets a larger interface without touching this; this
    #: is for eyesight and viewing distance rather than for resolution
    #: (env: OPENGLCONTEXT_UI_SCALE).  See :mod:`OpenGLContext.ui.metrics`.
    uiScale = field.newField( "uiScale", "SFFloat", 1,
                              lambda: renderoptions.env_number('OPENGLCONTEXT_UI_SCALE', 1.0))

    #: Fields that are *published* rather than chosen, and so are never carried
    #: in a settings dialog's draft: ``movementMode`` says which mode is in
    #: force right now and is written by the navigation manager every frame.
    #: See :mod:`OpenGLContext.ui.session`.
    TRANSIENT_FIELDS = ('movementMode',)

    #: How a generated settings page presents these fields: what to call each
    #: one, and what range or set of values it accepts.  Declared beside the
    #: fields so a new setting appears on the screen with no UI work.
    #:
    #: Every name here appears in one of the section lists below, and a test
    #: holds them to it -- a hint for a field no section shows is presentation
    #: for a control nobody can reach.  ``profile`` and ``title`` are settled
    #: when the window is made and cannot be changed for a running one, so
    #: neither is offered.
    #: See :mod:`OpenGLContext.ui.generate`.
    UI_HINTS = {
        'shadows': {'label': 'Shadows'},
        'shadowsSoft': {'label': 'Soft shadows'},
        'shadowCascades': {'label': 'Shadow cascades', 'minimum': 0,
                           'maximum': 4, 'step': 1},
        'maximumLights': {'label': 'Lights', 'minimum': 0, 'maximum': 8,
                          'step': 1},
        'bloom': {'label': 'Bloom'},
        'ibl': {'label': 'Environment lighting',
                'options': renderoptions.CHOICES['ibl'],
                'optionLabels': renderoptions.LABELS['ibl']},
        'iblIntensity': {'label': 'Environment intensity', 'minimum': 0.0,
                         'maximum': 2.0, 'step': 0.05},
        'transmission': {'label': 'Glass refraction',
                         'options': renderoptions.CHOICES['transmission'],
                         'optionLabels': renderoptions.LABELS['transmission']},
        'instancing': {'label': 'Instanced batching'},
        'gpuSkinning': {'label': 'Skinning on the GPU'},
        'tessellationLOD': {'label': 'Distance detail'},
        'vsync': {'label': 'Wait for refresh (vsync)'},
        'uiScale': {'label': 'Interface size', 'minimum': 0.75, 'maximum': 2.0,
                    'step': 0.25, 'suffix': 'x'},
        'fullscreen': {'label': 'Full screen'},
        'multisampleSamples': {'label': 'Anti-aliasing samples', 'minimum': -1,
                               'maximum': 16, 'step': 1},
        'pickEnabled': {'label': 'Mouse picking'},
        'pickAsync': {'label': 'Non-blocking picking'},
        'debugBBox': {'label': 'Show bounding boxes'},
        'debugSelection': {'label': 'Show the selection buffer'},
        'debug': {'label': 'Debug output'},
    }

    #: Fields a settings screen shows under "Rendering", in the order they
    #: should read: the expensive things first, the diagnostics last.
    RENDERING_FIELDS = (
        'shadows', 'shadowsSoft', 'shadowCascades', 'maximumLights',
        'bloom', 'ibl', 'iblIntensity', 'transmission',
        'instancing', 'gpuSkinning', 'tessellationLOD',
        'multisampleSamples', 'vsync',
    )
    #: Fields a settings screen shows under "Interface": how the overlay itself
    #: is drawn and how much of the display the window takes, as opposed to what
    #: is in the world.
    INTERFACE_FIELDS = (
        'uiScale', 'fullscreen',
    )
    #: Fields of the ``audio`` sub-node a settings screen shows under "Sound".
    #: Its own section rather than a corner of "Rendering": a player looking for
    #: the volume looks for a heading that says sound.
    AUDIO_FIELDS = audiosettings.AudioSettings.FIELDS
    #: Fields a settings screen shows under "Diagnostics".
    DIAGNOSTIC_FIELDS = (
        'pickEnabled', 'pickAsync', 'debugBBox', 'debugSelection', 'debug',
    )

    def __init__( self, **named ):
        # Zero-argument super, so an instance of this class still finds its own
        # base after the module has been reloaded: the two-argument form looks
        # the class up as a module global, which a reload has rebound to a
        # different class object by then.
        super().__init__( **named )
        if 'profile' in named and 'version' not in named:
            # ``version``'s default is chosen from the profile, and a field
            # default cannot see the node it belongs to -- so left unset it
            # reads the profile the *environment* names.  A definition that
            # states its profile settles its version from that one instead,
            # since a backend turns ``version >= 3`` into a context hint and
            # would otherwise open a 3.3 window for a compatibility request.
            self.version = version_for_profile( self.profile )

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

