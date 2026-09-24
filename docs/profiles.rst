.. _core-profile:

Core vs. Compatibility Contexts
===============================

.. rst-class:: introduction

An OpenGL context is created with one of two profiles. The **core** profile
draws with GLSL shaders on an OpenGL 3.3 or later context. The
**compatibility** profile also offers the fixed-function pipeline:
``glBegin``, the matrix stack, display lists, ``glMaterial`` and ``glLight``.
OpenGLContext renders a scene in either, and every backend can create both.

The core profile
----------------

A context uses the core profile unless the program asks for the compatibility
profile. It requests an OpenGL 3.3 core-profile context and renders through
the shader-based pass. It is the only profile on platforms such as macOS that
offer no fixed-function pipeline. The engine's own geometry requires it:
``PBRMesh`` draws only through shaders, and the glTF loader and every
generator built on it produce ``PBRMesh`` nodes. The :doc:`PBR renderer
<pbr>`, shadows, bloom and the :doc:`overlay UI <overlayui>` are drawn only in
the core profile.

The compatibility profile
-------------------------

The compatibility profile is fully supported. Use it for a program that draws
with the fixed-function pipeline: one that calls ``glBegin``,
``glVertexPointer``, ``glMaterial``, ``glLight``, the matrix stack, display
lists, or GLSL's ``gl_ModelViewProjectionMatrix`` and similar built-ins. None
of these exist in a core context. A fixed-function call made in a core context
raises ``GLError(1282)``. The render pass catches it for that node and draws
the rest of the frame, so a program run in the wrong profile keeps running and
shows nothing where that node should be.

A glTF model loaded into a compatibility-profile context is drawn with
``glMaterial`` lighting from its material factors; :doc:`Loading glTF <gltf>`
lists what that keeps and what it leaves out.

.. _choosing-profile:

Saying which profile your program needs
---------------------------------------

A program that needs a particular profile declares it on its Context class,
so the requirement stays with the code:

.. code-block:: python

   class MyContext( BaseContext ):
       profile = 'compatibility'   # this program draws with the fixed-function pipeline

To set the profile for a whole run instead, for a CI job or a one-off
comparison, use the environment variable:

.. code-block:: bash

   OPENGLCONTEXT_PROFILE=compatibility python your_script.py

``profile`` also sets the matching OpenGL version. It is applied on top of any
``contextDefinition`` the class declares, so a subclass can name its profile
and still inherit the size, buffers and rendering features from its base
class. To set more than the profile, declare the whole definition:

.. code-block:: python

   from OpenGLContext import contextdefinition

   class MyContext( BaseContext ):
       contextDefinition = contextdefinition.ContextDefinition(
           profile = 'compatibility',
           size = (800, 600),
           multisampleSamples = 4,
       )

Every backend reads either declaration before it creates the window. The
profile, the version and the buffer formats are window-creation parameters and
cannot be changed afterwards. A definition passed to the constructor takes
precedence over both. Each context gets its own copy of the class's
definition, because a context writes its size back to its definition when the
window is resized.

What differs between them
-------------------------

Both profiles render through a ``FlatPass`` (see :doc:`Flat Rendering
<flat>`). The base class in ``passes/_flat.py`` holds both code paths, and the
flag ``use_shaders`` selects one. The core pass sets ``use_shaders = True``;
the compatibility pass leaves it ``False``.

.. list-table::
   :widths: auto
   :header-rows: 1

   * -
     - Compatibility (``flatcompat.py``)
     - Core (``flatcore.py``)
   * - Selected by
     - ``profile = 'compatibility'``, or ``OPENGLCONTEXT_PROFILE=compatibility``
     - default
   * - Lighting
     - fixed-function ``glLight*``, ``glEnable(GL_LIGHTING)``
     - VRML97 lighting model in GLSL; light properties uploaded as uniforms
   * - Materials
     - ``glMaterial*``, ``glColorMaterial``
     - material uniforms set on the shader program
   * - Matrices
     - ``glMatrixMode`` / ``glLoadMatrixf`` / ``glPushMatrix``
     - node-path matrices computed on the CPU and uploaded as ``mat4`` uniforms
   * - Geometry
     - vertex pointers, display lists
     - VAOs and VBOs at fixed attribute locations
   * - Selection / picking
     - ``glColor4ubv`` back-buffer colour codes
     - object id written to a second render target (MRT), or the unlit program

.. rst-class:: technical

The dispatch is in ``passes/renderpass.py``. When the context definition has
``profile == 'core'``, the renderer creates the core ``FlatPass`` from
``passes/flatcore.py``; otherwise it creates the compatibility ``FlatPass``
from ``passes/flatcompat.py``. The choice is made once per context, not per
frame. :doc:`Core-Profile Rendering <renderpasses>` describes what the core
pass does each frame.
