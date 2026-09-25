OGLC_hook
=========

.. rst-class:: introduction

A glTF material and node extension that names a *kind* - water, a mirror, a
fire - which the loading application makes something of. A material tagged
``water`` loads as a moving water surface; an object tagged ``fire`` loads
with a flame standing where it stands. The same payload may be written as a
custom property in ``extras``, which is what a Blender custom property
exports as.

This page is the specification: where the tag goes, how it is read, and every
kind OpenGLContext ships with its parameters. :ref:`Engine hooks <hooks>` on
the glTF page is the guide to using and registering kinds, and the pages for
:doc:`water <../water>`, :doc:`reflections <../reflections>` and
:doc:`particles <../particles>` describe what each kind draws.

Status
------

Vendor extension, implemented by OpenGLContext. A kind is a name an
application registers; the kinds below are the ones the engine registers
itself.

Where the tag goes
------------------

On a **material**, the tag says every surface drawn with that material is of
the kind: water, or a mirror. It is called once for each primitive using the
material.

On a **node**, the tag says the object is of the kind: a fire, or an object
that shows only its reflection. It is called once for the node.

Each kind below says which of the two it reads. A kind tagged in a place it
does not read loads as it stands.

Spellings
---------

The value is an object with a ``kind`` and that kind's parameters, or a string
that is the kind alone with every parameter at its default:

.. code-block:: javascript

   // in the holder's extensions -- what a tool writes
   "extensions": {"OGLC_hook": {"kind": "water", "style": "choppy", "depth": 6.0}}

   // in the holder's extras -- what a Blender custom property exports as
   "extras": {"OGLC_hook": {"kind": "water", "style": "choppy"}}

   // either place, the kind alone
   "extras": {"OGLC_hook": "water"}

Where a holder carries both, the ``extensions`` block is read and ``extras``
is not. An object with no ``kind``, or an empty string, is no tag. A document
using the ``extensions`` form lists ``OGLC_hook`` in ``extensionsUsed``; it
does not need to list it in ``extensionsRequired``, since a reader that does
not know it loads the holder as ordinary geometry.

Reading a tag
-------------

- A ``kind`` nothing is registered for loads as ordinary geometry.
- A document names a kind and never names code: an application chooses which
  kinds exist, and the engine's own are a fixed table of names.
  ``OPENGLCONTEXT_GLTF_HOOKS=0`` leaves every tag unread.
- A parameter that is not a finite number where a number is wanted, or is not
  one of a parameter's names, is reported once for the document and takes its
  default. A number outside its range is reported and is the nearer end of
  the range. A misspelled parameter never stops a document loading.
- A kind that fails while loading is logged with the holder it was loading,
  and that holder loads as ordinary geometry; the rest of the document loads.

``water``
---------

Read on a material. Every primitive drawn with the material becomes a surface
whose waves move with the engine clock, and bounds a volume a camera can be
inside. See :doc:`../water`.

.. list-table::
   :header-rows: 1
   :widths: 16 16 14 54

   * - Parameter
     - Type
     - Default
     - Meaning
   * - ``style``
     - string or object
     - ``"still"``
     - ``still``, ``breeze``, ``flowing``, ``choppy`` or ``lake``; or an
       object with ``style`` naming one of those and any of ``amplitude``
       (metres, at least 0), ``wavelength`` (metres, at least 0.01),
       ``speed`` (metres a second), ``steepness`` (at least 0), ``ripple``
       (metres, at least 0.01) and ``flow`` (two numbers, the drift in
       metres a second along x and z) over it. An unknown name is ``still``.
   * - ``material``
     - string
     - ``"keep"``
     - ``keep`` shades the surface with the document's material; ``engine``
       replaces it with the engine's water material.
   * - ``medium``
     - string
     - ``"water"``
     - What being inside the volume is like: ``water``, ``slime`` or
       ``lava``.
   * - ``depth``
     - number
     - 0
     - Metres below the surface's lowest point that the volume reaches; at
       least 0.

``mirror``
----------

Read on a material and on a node. On a material, every surface drawn with it
is a planar mirror in its own plane, shaded by the material. On a node, every
surface of the object shows only the reflection. A surface reflects the scene
only where it is flat to within 1% of its size. See :doc:`../reflections`.

.. list-table::
   :header-rows: 1
   :widths: 16 12 12 60

   * - Parameter
     - Type
     - Default
     - Meaning
   * - ``scale``
     - number
     - 0.5
     - Resolution as a share of the mirror's rectangle on screen, each way;
       0.05 to 1.
   * - ``interval``
     - integer
     - 3
     - The most frames the reflection goes without being drawn again; at
       least 1.
   * - ``priority``
     - number
     - 1
     - Weight against the other mirrors in view when a frame's budget is
       short; at least 0.
   * - ``distortion``
     - number
     - 0
     - Offset per unit of the surface normal's tilt from the plane, in widths
       (and heights) of the mirror's view, which is how far a normal map
       breaks the reflection up; 0 to 1.
   * - ``reflectance``
     - number
     - 0.97
     - The share of the light the mirror reflects; 0 to 1.
   * - ``replace``
     - boolean
     - false on a material, true on a node
     - Whether the surface shows only the reflection.

``fire``, ``smoke`` and ``sparks``
----------------------------------

Read on a node. A particle emitter stands where the object stands, beside the
object's own content, started from the engine's preset of the same name; an
authored ``sparks`` is a steady fountain rather than the preset's single
burst. See :doc:`../particles`.

.. list-table::
   :header-rows: 1
   :widths: 18 14 12 56

   * - Parameter
     - Type
     - Default
     - Meaning
   * - ``scale``
     - number
     - 1
     - Multiplies every length: particle size at birth and death, speed and
       gravity. The node's own scale multiplies it too. At least 0 and at
       most 100, the node's scale included.
   * - ``density``
     - number
     - 1
     - Multiplies the particles emitted a second, the burst and the particle
       budget; at least 0, at most 100.
   * - ``texture``
     - string
     - none
     - A sprite image, as a URI relative to the document. Read only for a
       document loaded from a directory, and refused if it names a file
       outside that directory; otherwise the particles are soft dots.
   * - any emitter field
     - as the field
     - the preset's
     - ``rate``, ``maxParticles``, ``lifetime``, ``lifetimeVariation``,
       ``speed``, ``speedVariation``, ``spread``, ``drag``, ``size``,
       ``endSize``, ``sizeVariation``, ``spin``, ``spinVariation``,
       ``alpha``, ``endAlpha``, ``burst``, ``seed``, ``direction``,
       ``gravity``, ``color``, ``endColor``, ``worldSpace``, ``enabled``,
       ``burstOnStart`` and ``blending`` (``additive`` or ``alpha``), set
       before ``scale`` and
       ``density`` apply. Each number is held to the field's range after
       both multiply it, so ``maxParticles`` is at most 20000.

JSON schema
-----------

The schema describes the value in either place, with the parameters of every
kind above:

.. literalinclude:: schema/OGLC_hook.schema.json
   :language: json

:download:`OGLC_hook.schema.json <schema/OGLC_hook.schema.json>`

Authoring
---------

In Blender, give a material or an object a custom property called
``OGLC_hook`` holding the kind, or a JSON object, and export with custom
properties included. The add-on in ``tools/blender/oglc_hook``, in a checkout
of the OpenGLContext repository, adds an Engine Hook panel that writes the
``extensions`` form; :ref:`Engine hooks <hooks>` describes both.
