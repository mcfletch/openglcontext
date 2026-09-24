Environment Variables
=====================

.. rst-class:: introduction

Environment variables set the defaults for OpenGLContext's rendering features
and pin them for a script or a CI run. Each switchable rendering feature is a
field on the ``ContextDefinition``, and its environment variable supplies that
field's **default**. A settings screen can show the same field and change it
while the program runs. Passes read these values through
``OpenGLContext.renderoptions``, not from the environment directly.

How values are read
-------------------

Booleans
   A boolean accepts ``1``, ``on``, ``true`` or ``yes`` for true, and ``0``,
   ``off``, ``false``, ``no`` or ``none`` for false, in any capitalisation.
   An unset variable and an empty one both mean the default. Any other value
   is ignored with a logged warning, and the default applies. A mistyped
   value therefore cannot silently reverse the setting a CI run pinned. An
   unparseable number is reported the same way.

   ``OPENGLCONTEXT_PICKING``, ``OPENGLCONTEXT_INSTANCE_COLLAPSE`` and
   ``OPENGLCONTEXT_INSTANCE_CLUSTER_CULL`` are parsed separately, without the
   warning: an unrecognised value leaves the default in place, and
   ``OPENGLCONTEXT_PICKING`` set to an empty string turns picking off.

``auto``
   The three-valued options take ``auto`` to let the engine choose. For
   example, image-based lighting and transmission reduce their own cost on a
   software rasteriser when set to ``auto``.

Read once
   These are start-up settings. Each is read the first time it is needed and
   then kept, so a later change to ``os.environ`` does not change a running
   program. To change a feature while the program runs, set the
   ``ContextDefinition`` field, which takes precedence over the variable.

Reproducible renders
   To start a subprocess whose render must be reproducible, build its
   environment with ``renderoptions.clean_environment()``. It removes every
   variable in the tables below except the two marked *presentation* and those
   under :ref:`Sound and diagnostics <env-diagnostics>`, then sets the values
   you pass it. A reference image then does not depend on what the parent
   process had set.

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
     - Which OpenGL profile the context requests. ``core`` uses GLSL
       throughout; ``compatibility`` provides the fixed-function pipeline. See
       :ref:`OpenGL core profile support <core-profile>` and
       :doc:`Core-profile rendering <renderpasses>`.
   * - ``OPENGLCONTEXT_BACKEND``
     - ``glfw``, ``glut``, ``pygame``, ``tk``, ``wx``, ``qt``, ``egl``,
       ``wgl``, or the name a third-party backend registers
     - the name in ``defaultcontext.txt`` in the user's OpenGLContext
       app-data directory, otherwise ``glfw``
     - Which GUI toolkit creates the window. ``qt`` needs the separate
       ``OpenGLContext-qt`` distribution. ``egl`` (Linux and Android) and
       ``wgl`` (Windows) create no window and render offscreen; see
       :doc:`Rendering offscreen <offscreen>`. :ref:`Which backends are
       supported <backends>` describes each.
   * - ``OPENGLCONTEXT_RENDERER``
     - ``pbr``
     - unset
     - ``pbr`` selects the metallic/roughness renderer. See :doc:`PBR <pbr>`.
   * - ``OPENGLCONTEXT_MULTIVIEW``
     - ``auto``, ``vertex``, ``geometry``, ``sequential``
     - ``auto``
     - How a window with several views is drawn. ``auto`` uses the fastest
       strategy the driver supports. Naming a strategy pins it, for comparing
       them; if the driver cannot run it, a message is logged and another
       strategy is used. See :doc:`Several views on one window <multiview>`.

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
     - Percentage-closer filtering on the shadow lookup: softer edges, more
       samples per fragment.
   * - ``OPENGLCONTEXT_SHADOW_CASCADES``
     - integer 0–4
     - ``0``
     - Number of cascades for a directional light; more cascades give sharper
       shadows at a distance. ``0`` lets the pass choose from available video
       memory and frame rate. Set a fixed value when shadow output must be
       reproducible.
   * - ``OPENGLCONTEXT_MAXIMUM_LIGHTS``
     - integer 0–8
     - ``8``
     - The number of lights the shader binds in one frame. A lower value is
       faster in a scene with many lights. The shader's own maximum still
       applies.
   * - ``OPENGLCONTEXT_IBL``
     - ``auto``, ``full``, ``analytic``, ``off``
     - ``auto``
     - Image-based lighting. ``full`` uses the precomputed irradiance,
       prefilter and BRDF lookup-table probe; ``analytic`` uses a cheaper sky
       approximation. See :ref:`Environment lighting <environment-lighting>`.
   * - ``OPENGLCONTEXT_IBL_INTENSITY``
     - number
     - ``1.0``
     - Scale on the ambient light from the environment.
   * - ``OPENGLCONTEXT_ENV_HDR``
     - path or URL
     - unset
     - An equirectangular Radiance ``.hdr`` image used for lighting and
       reflections and drawn as the skybox. Takes precedence over
       ``OPENGLCONTEXT_ENV_CUBEMAP``.
   * - ``OPENGLCONTEXT_ENV_CUBEMAP``
     - face-name prefix
     - unset
     - Six cubemap faces named by a common prefix, for example
       ``/path/pimbackground_`` for the ``_UP``/``_DN`` face set. Used when no
       HDR image is given.
   * - ``OPENGLCONTEXT_BLOOM``
     - yes/no
     - off
     - The bright-pass bloom composite.
   * - ``OPENGLCONTEXT_TRANSMISSION``
     - ``auto``, ``full``, ``blend``, ``off``
     - ``auto``
     - Glass (``KHR_materials_transmission``). ``full`` captures the backdrop
       and refracts it; ``blend`` is a cheaper alpha-blended approximation.
   * - ``OPENGLCONTEXT_PLANAR_REFLECTIONS``
     - yes/no
     - on
     - Mirrors and water reflect the scene around them (:doc:`reflections`).
       Off, they reflect only the sky.
   * - ``OPENGLCONTEXT_REFLECTION_VIEWS``
     - integer
     - 0
     - The most mirror views drawn in a frame; 0 is the multi-view strategy's
       own, 16 or 2.
   * - ``OPENGLCONTEXT_REFLECTION_BOUNCES``
     - integer
     - 2
     - How many reflections deep a chain of mirrors is followed; 1 is the
       mirrors in view only.
   * - ``OPENGLCONTEXT_REFLECTION_SEPARATE_VIEWS``
     - integer
     - 4
     - Of those, the most that also draw particles and text, which a shared
       draw refuses.
   * - ``OPENGLCONTEXT_REFLECTION_ATLAS``
     - share
     - 0.5
     - The reflection atlas's size as a share of the window's pixels.
   * - ``OPENGLCONTEXT_REFLECTION_MS``
     - milliseconds
     - 0 (none)
     - A GPU time the reflections aim to stay under.

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
     - Draw repeated shapes as one instanced draw. See :doc:`Instanced
       geometry <instancing>`.
   * - ``OPENGLCONTEXT_INSTANCE_MIN``
     - integer
     - ``4``
     - The number of copies of a shape needed before the pass draws them as
       one batch instead of one at a time.
   * - ``OPENGLCONTEXT_INSTANCE_COLLAPSE``
     - yes/no
     - on
     - Group shapes that share a geometry and a compatible appearance.
   * - ``OPENGLCONTEXT_INSTANCE_CLUSTER_CULL``
     - yes/no
     - off
     - Cull a whole instance group by its combined bounds before testing each
       member.
   * - ``OPENGLCONTEXT_LOD``
     - yes/no
     - on
     - Distance level of detail for procedurally tessellated geometry: the
       teapot, the quadrics (sphere, cone, cylinder) and NURBS surfaces are
       tessellated more coarsely further from the camera. Turn it off for
       full detail at every distance, for example for reference images.
   * - ``OPENGLCONTEXT_GPU_SKINNING``
     - yes/no
     - on
     - Skin a rigged mesh in the vertex shader instead of on the CPU.
   * - ``OPENGLCONTEXT_GPU_SKELETON``
     - yes/no
     - on
     - Compute the skeleton's pose on the GPU, so a crowd needs one upload.
   * - ``OPENGLCONTEXT_GPU_BLEND``
     - yes/no
     - on
     - Blend between animation clips on the GPU.
   * - ``OPENGLCONTEXT_PICKING``
     - yes/no
     - on
     - Object-id picking. When off, the selection pass, its object-id buffer
       and its readback are skipped. Turn it off for a program that never
       picks.
   * - ``OPENGLCONTEXT_EGL_DEVICE``
     - device index
     - the first hardware device
     - The EGL device the offscreen context renders on, for a machine with
       several. ``OpenGL.EGL.devices`` lists them. An index out of range is an
       error. See :doc:`Rendering offscreen <offscreen>`.
   * - ``OPENGLCONTEXT_WGL_ANY_ACCELERATION``
     - yes/no
     - off
     - For the Windows offscreen context, accept a pixel format that does not
       report full acceleration. Some unusual or virtualised adapters offer no
       accelerated pbuffer format; with this set, the context renders slowly
       on them instead of failing. See :doc:`Rendering offscreen <offscreen>`.
   * - ``OPENGLCONTEXT_PHYSICS``
     - yes/no
     - off
     - Makes the viewer walk the scene with gravity and collision instead of
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
     - *Presentation.* Render without showing a window. A hidden window
       renders and reads back the same as a visible one, so a test suite can
       open hundreds of GL contexts without covering the desktop. Not
       supported by the Qt backend. See :doc:`Testing what you draw <testing>`.
   * - ``OPENGLCONTEXT_NO_VSYNC``
     - yes/no
     - off
     - *Presentation.* Do not wait for the compositor when swapping buffers.
   * - ``OPENGLCONTEXT_FULLSCREEN``
     - yes/no
     - off
     - Open the window filling the screen at the display's current resolution
       instead of at ``ContextDefinition.size``. This is the default for the
       ``fullscreen`` field, which a program can set and the settings screen
       offers. ``OPENGLCONTEXT_HIDDEN`` takes precedence. Supported by the
       GLFW, GLUT, Pygame and wx backends. See :ref:`Filling the screen
       <fullscreen>`.
   * - ``OPENGLCONTEXT_UI_SCALE``
     - number
     - ``1.0``
     - Multiplier on the size of the overlay interface. The window height
       already sets the font size; this scales the result. See :doc:`Overlay
       UI <overlayui>`.
   * - ``OPENGLCONTEXT_DISABLE_FPS_DISPLAY``
     - yes/no
     - off
     - Hide the frame-rate readout, which otherwise differs between two runs
       of the same capture.
   * - ``OPENGLCONTEXT_VIEW_YAW``
     - number, radians
     - ``-0.62``
     - The angle the viewer turns a model that has no camera of its own when
       it frames it, giving a three-quarter view.
   * - ``OPENGLCONTEXT_AUTO_EXIT_FRAMES``
     - integer
     - unset
     - Quit after this many frames. Together with the capture settings below,
       this takes a screenshot without anyone present.
   * - ``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR``
     - path
     - unset
     - Where the automatic capture is written.
   * - ``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME``
     - filename
     - the script's name
     - The file name of the automatic capture.
   * - ``OPENGLCONTEXT_CAPTURE_DELAY``
     - seconds
     - ``0.5``
     - How long the comparison harness waits for a scene to settle before
       reading the framebuffer.
   * - ``OPENGLCONTEXT_CAPTURE_FPS``
     - frames per second
     - ``60`` during a bounded run, otherwise off
     - How far a capture's world clock advances for each frame drawn. During
       a bounded run (``OPENGLCONTEXT_AUTO_EXIT_FRAMES``), the engine's clock
       counts frames from zero instead of reading the wall clock. A scene
       animated by a ``Timer`` or a ``TimeSensor`` then reaches the same point
       in every run, however long the process took to start. ``0`` keeps the
       wall clock. See :ref:`The clock a recording runs on <recording-clock>`.
   * - ``OPENGLCONTEXT_GLTF_BASELINE``
     - path
     - ``tests/reference_images``
     - Where ``oglc-gltf-regression`` finds the images it compares against.

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
     - Record the whole session to this JSON-lines file: every input, stamped
       with the frame that handled it; every frame's time and phase breakdown;
       every exception with its traceback; and the developer overlay's
       sections, sampled as the session runs. ``1`` writes a dated file under
       the user's app-data directory. Read it with ``python -m
       OpenGLContext.telemetry <file>``. See :doc:`Session telemetry
       <telemetry>`.
   * - ``OPENGLCONTEXT_TELEMETRY_REPLAY``
     - path
     - unset
     - Run a recorded session again: the same keys and clicks in the same
       places on the same frames, with the engine's clock driven by the
       recorded frame times.
   * - ``OPENGLCONTEXT_TELEMETRY_MAX_MB``
     - number
     - ``128``
     - Maximum size of the recording, in megabytes. Beyond it, only
       exceptions and marks are written.
   * - ``OPENGLCONTEXT_SEED``
     - integer
     - unset
     - Fix the session's randomness. ``OpenGLContext.entropy`` holds one seed
       per session and seeds the standard ``random`` and ``numpy.random``
       generators from it, so a scene that scatters vegetation or throws
       sparks renders the same way twice. It must be set before anything draws
       from a generator. See :ref:`Randomness <randomness>`.
   * - ``OPENGLCONTEXT_GLTF_HOOKS``
     - yes/no
     - ``1``
     - Whether a glTF's :ref:`OGLC_hook <hooks>` tags are read. Off, every tag
       in every file is ignored, and a tagged lake loads as the flat sheet the
       file draws. It is listed here because a tag changes what a frame shows,
       so a reference image captured with it off is of a different scene.

.. _env-diagnostics:

Sound and diagnostics
---------------------

These variables do not change what a frame looks like, so
``clean_environment()`` passes them to a subprocess unchanged. A diagnostic
switched on for a run therefore also applies to the subprocesses it starts.

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
     - unset (threshold 50)
     - Log a main-loop iteration longer than this as a stall. Setting it also
       turns stall logging on. See :ref:`the developer overlay <hud-loop>`.
   * - ``OPENGLCONTEXT_TRACE_STALLS``
     - yes/no
     - off
     - Log each stall's phase breakdown, at the default 50 ms threshold.
   * - ``OPENGLCONTEXT_STALL_TRACE``
     - path
     - unset
     - Write each slow period to this JSON-lines file, with the main thread's
       Python stack sampled during the stall. Read it with ``python -m
       OpenGLContext.stalltrace <file>``. See :ref:`Recording a slow period
       <stalltrace>`.
   * - ``OPENGLCONTEXT_DEBUG_WHEEL``
     - yes/no
     - off
     - Log each scroll notch as the GLFW backend translates it.

PyOpenGL's variable
-------------------

``PYOPENGL_PLATFORM`` belongs to PyOpenGL and selects the GL platform binding.
On Linux, leave it unset for a windowed program: PyOpenGL then loads both GLX
and EGL and uses whichever owns the current context, so a GLX toolkit and an
EGL toolkit both work in one install. Set it for an offscreen render
(``PYOPENGL_PLATFORM=egl``, or ``osmesa`` for the software rasteriser), where
there is no toolkit context to detect.
