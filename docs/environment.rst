Environment Variables
=====================

.. rst-class:: introduction

Every switchable rendering feature is a field on the ``ContextDefinition``,
and the environment variable is that field's **default**. So a shell variable
pins a feature for a script or a CI run, a settings screen can still show the
same feature and change it while the program runs, and the two never disagree
about what the default was. The reader is ``OpenGLContext.renderoptions``; a
pass asks through it rather than reading the environment itself.

How values are read
-------------------

**Yes and no.** A boolean accepts ``1``, ``on``, ``true``, ``yes`` for true
and ``0``, ``off``, ``false``, ``no``, ``none`` for false, in any
capitalisation. A value that is neither is **ignored with a warning** and the
default stands, rather than being treated as true: these variables are how a
feature is pinned for a run, and a typo that silently reversed the pin would
make the result of that run a lie. An unparseable number is reported the same
way.

``auto``. The three-valued options mean "the engine decides". Image-based
lighting and transmission both degrade themselves on a software rasteriser,
and a setting that forced a choice would take that away.

**Read once.** These are start-up switches, read the first time they are
needed and then remembered. A pass that changed its mind mid-session because
something else edited ``os.environ`` would be unpredictable. The
``ContextDefinition`` field is the thing meant to change while the program
runs, and it outranks whatever the variable settled.

**Rendering something reproducible?** Use
``renderoptions.clean_environment()`` to build the environment for the
subprocess. It drops every variable in the table below except the two marked
*presentation*, so a reference image cannot depend on what the parent process
happened to be carrying, and lets you pin exactly what the render needs.

Choosing the renderer
---------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Values
     - Default
     - What it does
   * - ``OPENGLCONTEXT_PROFILE``
     - ``core``, ``compatibility``
     - ``core``
     - Which OpenGL profile the context asks for. ``core`` uses GLSL throughout;
       ``compatibility`` gives the fixed-function pipeline. See :doc:`Core-profile
       rendering <renderpasses>`.
   * - ``OPENGLCONTEXT_BACKEND``
     - ``glfw``, ``glut``, ``pygame``, ``wx``, ``qt``, ``egl``
     - chosen by availability
     - Which GUI toolkit owns the window. ``qt`` needs the separate
       ``OpenGLContext-qt`` distribution installed. ``egl`` owns no window at all and
       renders offscreen, on Linux and Android — see :doc:`Rendering offscreen
       <offscreen>`.
   * - ``OPENGLCONTEXT_RENDERER``
     - ``pbr``
     - unset
     - ``pbr`` selects the metallic/roughness renderer. See :doc:`PBR <pbr>`.

Lighting and shadows
--------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Values
     - Default
     - What it does
   * - ``OPENGLCONTEXT_SHADOWS``
     - yes/no
     - on
     - Dynamic shadow mapping. See :doc:`Shadows <shadows>`.
   * - ``OPENGLCONTEXT_SHADOWS_SOFT``
     - yes/no
     - off
     - Percentage-closer filtering on the shadow lookup: softer edges, more samples
       per fragment.
   * - ``OPENGLCONTEXT_SHADOW_CASCADES``
     - integer 0–4
     - ``0``
     - Cascades for a directional light; more is crisper at distance. ``0`` lets the
       pass choose from VRAM and frame rate, so pin a fixed value when shadow output
       has to be reproducible.
   * - ``OPENGLCONTEXT_MAXIMUM_LIGHTS``
     - integer 0–8
     - ``8``
     - Lights the shader binds in one frame. Lower is faster in a scene with many
       lights; the shader's own ceiling still applies.
   * - ``OPENGLCONTEXT_IBL``
     - ``auto``, ``full``, ``analytic``, ``off``
     - ``auto``
     - Image-based lighting. ``full`` is the precomputed
       irradiance/prefilter/BRDF-LUT probe, ``analytic`` the cheaper sky
       approximation.
   * - ``OPENGLCONTEXT_IBL_INTENSITY``
     - number
     - ``1.0``
     - Scale on the ambient contribution from the environment.
   * - ``OPENGLCONTEXT_ENV_HDR``
     - path or URL
     - unset
     - An equirectangular Radiance ``.hdr`` to light and reflect from, and to draw as
       the skybox. Takes precedence over the cubemap.
   * - ``OPENGLCONTEXT_ENV_CUBEMAP``
     - face-name prefix
     - unset
     - Six cubemap faces, named by a common prefix — for example
       ``/path/pimbackground_`` for the ``_UP``/``_DN`` face set. Used when no HDR is
       given.
   * - ``OPENGLCONTEXT_BLOOM``
     - yes/no
     - off
     - The bright-pass bloom composite.
   * - ``OPENGLCONTEXT_TRANSMISSION``
     - ``auto``, ``full``, ``blend``, ``off``
     - ``auto``
     - Glass (``KHR_materials_transmission``). ``full`` captures the backdrop and
       refracts it; ``blend`` is the cheap alpha-blended stand-in.

How much work per frame
-----------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Values
     - Default
     - What it does
   * - ``OPENGLCONTEXT_INSTANCING``
     - yes/no
     - on
     - Collapse repeated shapes into one instanced draw. See :doc:`Instanced geometry
       <instancing>`.
   * - ``OPENGLCONTEXT_INSTANCE_MIN``
     - integer
     - ``4``
     - How many copies of a shape it takes before the pass batches them rather than
       drawing each.
   * - ``OPENGLCONTEXT_INSTANCE_COLLAPSE``
     - yes/no
     - on
     - Whether shapes sharing a geometry and a compatible appearance are gathered
       into one group.
   * - ``OPENGLCONTEXT_INSTANCE_CLUSTER_CULL``
     - yes/no
     - off
     - Cull a whole instance group by its combined bounds before testing the members
       individually.
   * - ``OPENGLCONTEXT_LOD``
     - yes/no
     - on
     - Distance level of detail: ``LOD`` nodes, vegetation and character meshes all
       pick a cheaper form with range.
   * - ``OPENGLCONTEXT_GPU_SKINNING``
     - yes/no
     - on
     - Skin a rigged mesh in the vertex shader rather than on the CPU.
   * - ``OPENGLCONTEXT_GPU_SKELETON``
     - yes/no
     - on
     - Evaluate the pose itself on the card, so a crowd costs one upload.
   * - ``OPENGLCONTEXT_GPU_BLEND``
     - yes/no
     - on
     - Blend between animation clips on the card.
   * - ``OPENGLCONTEXT_PICKING``
     - yes/no
     - on
     - Object-id picking. Off, the selection pass, its object-id buffer and its
       readback are all skipped — worth it for a program that never picks.
   * - ``OPENGLCONTEXT_EGL_DEVICE``
     - device index
     - the first hardware device
     - Which EGL device the offscreen context renders on, for a machine with several.
       ``OpenGL.EGL.devices`` lists them. An index out of range is an error rather
       than a fallback. See :doc:`Rendering offscreen <offscreen>`.
   * - ``OPENGLCONTEXT_WGL_ANY_ACCELERATION``
     - yes/no
     - off
     - Accept a pixel format that does not call itself fully accelerated, for the
       Windows offscreen context. An unusual or virtualised adapter may advertise no
       accelerated pbuffer format at all, and rendering slowly beats refusing. See
       :doc:`Rendering offscreen <offscreen>`.
   * - ``OPENGLCONTEXT_PHYSICS``
     - yes/no
     - off
     - Whether the viewer walks the scene with gravity and collision rather than
       framing it. See :doc:`Physics <physics>`.

The window, capture and the interface
-------------------------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Values
     - Default
     - What it does
   * - ``OPENGLCONTEXT_HIDDEN``
     - yes/no
     - off
     - *Presentation.* Render without mapping a window. A hidden window renders and
       reads back identically, so a suite of several hundred GL tests costs nobody
       their desktop. Not supported by the Qt backend.
   * - ``OPENGLCONTEXT_NO_VSYNC``
     - yes/no
     - off
     - *Presentation.* Do not wait for the compositor on swap.
   * - ``OPENGLCONTEXT_FULLSCREEN``
     - yes/no
     - off
     - Open filling the screen at the display's current resolution rather than a
       window of ``ContextDefinition.size``. The default for the ``fullscreen``
       field, which a program sets for itself and the settings screen offers.
       ``OPENGLCONTEXT_HIDDEN`` outranks it: a window that is not meant to appear
       cannot fill the screen. Honoured by the GLFW, GLUT, Pygame and wx backends.
   * - ``OPENGLCONTEXT_UI_SCALE``
     - number
     - ``1.0``
     - Multiplier on the overlay interface's size. The window height already picks
       the font size, so this is a preference on top of that. See :doc:`Overlay UI
       <overlayui>`.
   * - ``OPENGLCONTEXT_DISABLE_FPS_DISPLAY``
     - yes/no
     - off
     - Suppress the frame-rate readout, which otherwise differs between two runs of
       the same capture.
   * - ``OPENGLCONTEXT_VIEW_YAW``
     - number, radians
     - ``-0.62``
     - The angle a model with no camera of its own is turned to when it is framed —
       the three-quarter view.
   * - ``OPENGLCONTEXT_AUTO_EXIT_FRAMES``
     - integer
     - unset
     - Quit after this many frames. With the capture settings below, this is how a
       screenshot is taken without a person present.
   * - ``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR``
     - path
     - unset
     - Where the automatic capture is written.
   * - ``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME``
     - filename
     - the script's name
     - What the automatic capture is called.
   * - ``OPENGLCONTEXT_CAPTURE_DELAY``
     - seconds
     - ``0.5``
     - How long the comparison harness lets a scene settle before reading the
       framebuffer.
   * - ``OPENGLCONTEXT_CAPTURE_FPS``
     - frames a second
     - ``60`` during a bounded run, otherwise off
     - What a capture's world clock advances by per frame drawn. A bounded run puts
       the engine's time source on a clock that counts frames from zero rather than
       reading the wall clock, so a scene animated from a ``Timer`` or a
       ``TimeSensor`` reaches the same point in every run and the frame read back is
       a picture of the scene rather than of how long the process took to start.
       ``0`` keeps the wall clock.
   * - ``OPENGLCONTEXT_GLTF_BASELINE``
     - path
     - ``tests/reference_images``
     - Where ``oglc-gltf-regression`` finds the images it diffs against.

Recording a session, and making one repeatable
----------------------------------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Values
     - Default
     - What it does
   * - ``OPENGLCONTEXT_TELEMETRY``
     - path, or ``1``
     - unset
     - Record the whole session to that JSON-lines file: every input stamped with the
       frame that acted on it, every frame's time and phase breakdown, every
       exception with its traceback, and the developer overlay's own sections sampled
       as it ran. ``1`` writes a dated file under the user's app-data directory. Read
       it back with ``python -m OpenGLContext.telemetry <file>``. See :doc:`Session
       telemetry <telemetry>`.
   * - ``OPENGLCONTEXT_TELEMETRY_REPLAY``
     - path
     - unset
     - Run a recorded session again: the same keys and clicks in the same places on
       the same frames, with the engine's clock driven from the recorded frame times.
   * - ``OPENGLCONTEXT_TELEMETRY_MAX_MB``
     - number
     - ``128``
     - Cap on the journal. Past it, exceptions and marks still get through.
   * - ``OPENGLCONTEXT_SEED``
     - integer
     - unset
     - Fix the session's randomness. ``OpenGLContext.entropy`` owns one seed per
       session and seeds the ordinary ``random`` and ``numpy.random`` generators from
       it, so a scene that scatters vegetation or throws sparks renders the same way
       twice. It has to be in force before the first generator is drawn from.
   * - ``OPENGLCONTEXT_GLTF_HOOKS``
     - flag
     - ``1``
     - Whether a glTF's :ref:`OGLC_hook <hooks>` tags are read at all. Off, every
       tag in every file is ignored and a tagged lake loads as the flat sheet the
       file draws. It is in this table rather than left to the shell because a
       tag changes what a frame shows: a reference image captured with the
       mechanism off is a reference for a different scene.

Sound and diagnostics
---------------------

These are the exceptions to the rule above: they are not about what a frame
looks like, so ``clean_environment()`` passes them through to a subprocess
rather than dropping them. A diagnostic a subprocess silently dropped would be
no diagnostic at all.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Values
     - Default
     - What it does
   * - ``OPENGLCONTEXT_AUDIO``
     - yes/no
     - on
     - Whether the audio engine mixes at all. See :doc:`Spatial audio <audio>`.
   * - ``OPENGLCONTEXT_AUDIO_VOLUME``
     - number
     - ``1.0``
     - Master gain.
   * - ``OPENGLCONTEXT_STALL_MS``
     - milliseconds
     - unset
     - A frame longer than this is logged as a stall. See :doc:`the developer overlay
       <hud>`.
   * - ``OPENGLCONTEXT_TRACE_STALLS``
     - yes/no
     - off
     - Log where the time in a stalled frame went.
   * - ``OPENGLCONTEXT_STALL_TRACE``
     - yes/no
     - off
     - Sample stacks during the frame loop, so a stall names the code it was in.
   * - ``OPENGLCONTEXT_DEBUG_WHEEL``
     - yes/no
     - off
     - Log each scroll notch as the GLFW backend translates it.

Not ours
--------

``PYOPENGL_PLATFORM`` belongs to PyOpenGL and names the GL platform binding.
On Linux it is worth leaving unset: that platform loads both GLX and EGL and
probes for whichever owns the live context, which is what lets a GLX toolkit
and an EGL one work in the same install. Naming one pins it, which is what an
offscreen render wants (``PYOPENGL_PLATFORM=egl``, or ``osmesa`` for the
software rasteriser) and what a windowed program does not.
