GLSL in OpenGLContext
=====================

Every shader OpenGLContext ships is written in **GLSL 330** and begins with
``#version 330 core``. That is the version OpenGL 3.3 brings, which is what
the engine asks for by default (:ref:`core profile <core-profile>`) and what
every desktop driver of the last decade or so provides.

This page is for two readers: someone writing a shader for the engine, who
wants to know what the engine will hand them; and someone with an older shader
that no longer compiles, who wants to know what to change.

What the engine supplies
------------------------

Vertex inputs
~~~~~~~~~~~~~

A geometry node writes its arrays to fixed attribute locations, declared once
in ``OpenGLContext/scenegraph/vertexsemantics.py`` and listed under
:doc:`Fixed Attribute Locations <renderpasses>`. Spell an input with the
engine's own name and it arrives with nothing declared on the node:

.. code-block:: python

   in vec3 aPosition;     // location 2
   in vec3 aNormal;       // location 1
   in vec2 aTexCoord;     // location 0
   in vec4 aTangent;      // location 3
   in vec4 aColor;        // location 4

To call an input something else, name the semantic it carries with a
``ShaderInput`` on the ``GLSLObject`` — see :doc:`A Shape whose appearance
brings its own shader <renderpasses>`.

Uniforms
~~~~~~~~

The render pass sets these on any ``GLSLObject`` that declares one, so naming
it is all that is needed:

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
     - the inverse, the transpose, and the inverse-transpose of each

All are ``mat4``. The normal matrix is the upper-left 3×3 of
``itp_modelview``:

.. code-block:: python

   uniform mat4 itp_modelview;
   ...
   vec3 eyeNormal = mat3( itp_modelview ) * aNormal;

A shader compiled and bound by hand — as the tutorials from ``shader_1`` to
``shader_11`` do — declares and uploads its own matrices instead, from the
``mode.matrix`` and ``mode.projection`` the pass hands to ``Render``.

A fragment shader on its own
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A core profile has no fixed-function vertex stage, so a ``GLSLObject``
carrying only a fragment shader has nothing to draw with.
``res://simpleshader_vert_txt`` is the vertex shader for that case: it
transforms the position and passes on ``baseNormal``, ``texCoord`` and
``vertexColor``.

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

The substitutions, in the order they usually bite:

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

Two of these are not substitutions but decisions. ``gl_TexCoord[0]`` and
``gl_Color`` were filled in by the fixed-function vertex stage, so a fragment
shader reading them needs a vertex shader that writes them — either your own
or ``res://simpleshader_vert_txt`` above. And the light and material built-ins
were global GL state, so a shader reading them needs the application to say
what the light and the material are; the engine's own lit shader
(``OpenGLContext/shaders/vrml97_lighting.*``) shows one way, packing the
lights into a ``uniform vec4 lights[]`` array.

Going the other way
~~~~~~~~~~~~~~~~~~~

To run one of these shaders on a driver that offers only GLSL 1.20, reverse
the table: drop the ``#version`` line, turn each ``in`` in a vertex shader
back into ``attribute`` and each ``in``/ ``out`` pair between the stages back
into ``varying``, write to ``gl_FragColor`` instead of a declared output, call
``texture2D``, and read ``gl_ModelViewProjectionMatrix`` and
``gl_NormalMatrix`` in place of the matrix uniforms. The context has to ask
for the profile that still has them:

.. code-block:: python

   class MyContext( BaseContext ):
       profile = 'compatibility'

A vertex array object is still required by some drivers even under a
compatibility profile, so leave the ``glGenVertexArrays`` /
``glBindVertexArray`` pair in place.

Where the shaders are
---------------------

- ``OpenGLContext/shaders/*.vert``, ``*.frag`` — the engine's own programs, plus
  the ``_*.glsl`` files they ``#include``.

- ``OpenGLContext/resources/*.vert``, ``*.frag``, ``*.txt`` — shaders reachable
  by ``res://`` URL from a scenegraph. Each has a generated ``*_vert.py`` /
  ``*_frag.py`` beside it holding the same bytes; edit the source and regenerate
  the module.

- ``tests/resources/*.txt`` — the sample shaders ``tests/shaderobjects.py``
  loads by path.

Two files in that resources directory stay at GLSL 1.20:
``legacy_lighting.vert.txt`` and ``lights.vert.txt``. They reimplement the
fixed-function lighting model in terms of ``gl_LightSource`` and
``gl_FrontMaterial``, which is a description of that pipeline rather than a
shader for this one; nothing loads them, and the engine's own
``vrml97_lighting.*`` is the lit shader it uses.
