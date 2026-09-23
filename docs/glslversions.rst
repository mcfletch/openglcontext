GLSL in OpenGLContext
=====================

.. rst-class:: introduction

Every shader OpenGLContext ships is written in **GLSL 330** and starts with
``#version 330 core``. GLSL 330 is the version that comes with OpenGL 3.3,
which the engine requests by default (see :ref:`core profile
<core-profile>`). This page lists the inputs and uniforms the engine gives a
shader you write, and how to convert a shader between GLSL 1.20 and GLSL 330.

What the engine supplies
------------------------

Vertex inputs
~~~~~~~~~~~~~

A geometry node binds its arrays to fixed attribute locations. These are
declared in ``OpenGLContext/scenegraph/vertexsemantics.py`` and listed under
:ref:`fixed-attribute-locations`.
Declare an input with the engine's name and it receives the matching array,
with nothing to configure on the node:

.. code-block:: glsl

   in vec3 aPosition;     // location 2
   in vec3 aNormal;       // location 1
   in vec2 aTexCoord;     // location 0
   in vec4 aTangent;      // location 3
   in vec4 aColor;        // location 4

To give an input a different name, add a ``ShaderInput`` to the
``GLSLObject`` naming the semantic it carries. See :ref:`shape-own-shader`.

Uniforms
~~~~~~~~

The render pass sets these uniforms on any ``GLSLObject`` that declares them,
so a shader only needs to declare the ones it uses:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Uniform
     - What it is
   * - ``mat_modelview``
     - model to eye
   * - ``mat_projection``
     - eye to clip
   * - ``mat_modelproj``
     - the two multiplied: model to clip
   * - ``inv_``, ``tps_``, ``itp_`` prefixes
     - the inverse, the transpose, and the inverse-transpose of each of the
       above

All of them are ``mat4``. The normal matrix is the upper-left 3×3 of
``itp_modelview``:

.. code-block:: glsl

   uniform mat4 itp_modelview;
   ...
   vec3 eyeNormal = mat3( itp_modelview ) * aNormal;

A shader that you compile and bind yourself, as the tutorials ``shader_1`` to
``shader_11`` do, declares and uploads its own matrices. It takes them from
the ``mode.matrix`` and ``mode.projection`` the pass passes to ``Render``.

A fragment shader on its own
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The core profile has no fixed-function vertex stage, so a ``GLSLObject`` with
only a fragment shader cannot draw anything. Pair it with
``res://simpleshader_vert_txt``, a vertex shader that transforms the position
and passes ``baseNormal``, ``texCoord`` and ``vertexColor`` to the fragment
shader:

.. code-block:: python

   GLSLObject(
       shaders = [
           GLSLShader( url="res://simpleshader_vert_txt", type="VERTEX" ),
           GLSLShader( url="./my.frag", type="FRAGMENT" ),
       ],
   )

``tests/shaderobjects.py`` uses it for three of its shaders.

Moving a GLSL 1.20 shader to 330
--------------------------------

Make these substitutions. They are listed in the order in which the compiler
usually reports them:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - GLSL 1.20
     - GLSL 330
   * - no ``#version``, or ``#version 120``
     - ``#version 330 core``, on the first line
   * - ``attribute vec3 x;``
     - ``in vec3 x;``
   * - ``varying vec4 x;``
     - ``out vec4 x;`` in the vertex shader, ``in vec4 x;`` in the fragment shader
   * - ``gl_FragColor = c;``
     - ``out vec4 fragColor;`` … ``fragColor = c;``
   * - ``texture2D(s, uv)``
     - ``texture(s, uv)``
   * - ``gl_Vertex``
     - ``vec4( aPosition, 1.0 )``
   * - ``gl_Normal``
     - ``aNormal``
   * - ``gl_MultiTexCoord0``
     - ``aTexCoord``
   * - ``gl_Color``
     - ``aColor``, or a value the vertex shader passes on
   * - ``gl_TexCoord[0]``
     - a value the vertex shader passes on
   * - ``gl_ModelViewProjectionMatrix``
     - ``mat_modelproj``
   * - ``gl_ModelViewMatrix``
     - ``mat_modelview``
   * - ``gl_NormalMatrix``
     - ``mat3( itp_modelview )``
   * - ``ftransform()``
     - ``mat_modelproj * vec4( aPosition, 1.0 )``
   * - ``gl_LightSource[0].position``
     - a ``uniform vec3`` the application sets
   * - ``gl_FrontMaterial``
     - uniforms the application sets, or a ``struct`` of them
   * - ``gl_InstanceIDARB``
     - ``gl_InstanceID``

.. rst-class:: technical

Two rows need more than a substitution. The fixed-function vertex stage filled
in ``gl_TexCoord[0]`` and ``gl_Color``, so a fragment shader that reads them
needs a vertex shader that writes them: your own, or
``res://simpleshader_vert_txt`` above. The light and material built-ins were
global GL state, so a shader that reads them needs the application to supply
the light and material as uniforms. The engine's own lit shader
(``OpenGLContext/shaders/vrml97_lighting.*``) is one example: it packs the
lights into a ``uniform vec4 lights[]`` array.

Going the other way
~~~~~~~~~~~~~~~~~~~

To run one of these shaders on a driver that offers only GLSL 1.20, reverse
the table:

- remove the ``#version`` line;

- in the vertex shader, change each input ``in`` back to ``attribute``;

- change each ``out``/``in`` pair between the stages back to ``varying``;

- write to ``gl_FragColor`` instead of a declared output;

- call ``texture2D`` instead of ``texture``;

- read ``gl_ModelViewProjectionMatrix`` and ``gl_NormalMatrix`` instead of the
  matrix uniforms.

The context must request the compatibility profile, which still has those
built-ins:

.. code-block:: python

   class MyContext( BaseContext ):
       profile = 'compatibility'

Some drivers require a vertex array object even in a compatibility profile,
so keep the ``glGenVertexArrays`` and ``glBindVertexArray`` calls.

Where the shaders are
---------------------

- ``OpenGLContext/shaders/*.vert``, ``*.frag`` -- the engine's own programs,
  and the ``_*.glsl`` files they ``#include``.

- ``OpenGLContext/resources/*.vert``, ``*.frag``, ``*.txt`` -- shaders a
  scenegraph can load by ``res://`` URL. Each has a generated ``*_vert.py`` or
  ``*_frag.py`` module beside it holding the same text. Edit the source file
  and regenerate the module.

- ``tests/resources/*.txt`` -- the sample shaders that
  ``tests/shaderobjects.py`` loads by path.

Two files in ``OpenGLContext/resources/`` remain at GLSL 1.20:
``legacy_lighting.vert.txt`` and ``lights.vert.txt``. They reimplement the
fixed-function lighting model using ``gl_LightSource`` and
``gl_FrontMaterial``, which exist only in the compatibility profile. The
engine does not load them; its lit shader is ``vrml97_lighting.*``.
