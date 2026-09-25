OGLC_zone
=========

.. rst-class:: introduction

A glTF node extension that marks a region of space and lists the extensions
that apply inside it: dimmer or different image-based lighting in a room, lamps
that light only what is in their room, ambience heard only while the camera is
in an area, gravity inside a volume. It works in glTF 2.0 with
``KHR_implicit_shapes`` and in glTF 2.1 with the core ``shapes`` array.

This page is the specification. :doc:`../zones` is the guide to using zones in
OpenGLContext, and :doc:`../zones-internals` describes how the engine
implements them.

Status
------

Draft, implemented by OpenGLContext. Written so that it could become an
``EXT_`` extension later without a change to its JSON.

Dependencies
------------

Written against the glTF 2.0 specification and ``KHR_implicit_shapes``, and
against glTF 2.1, whose core ``shapes`` array holds the same objects.

Overview
--------

Several extensions have a block that says what applies to a whole scene:
``EXT_lights_image_based`` puts ``{"light": 0}`` on a scene, and
``KHR_audio_emitter`` puts ``{"emitters": [0, 1]}`` on a scene or a node. None
of them can say that a setting holds inside part of the scene and not
elsewhere. ``OGLC_zone`` adds that. A node carrying it names a shape, and every
block it lists applies to whatever is inside that shape, in the form that
block's extension defines.

A zone node has no content except its region. Its transform places, rotates
and scales the shape, and it may carry no mesh of its own.

Shapes
------

A zone's ``shape`` indexes the document's table of implicit shapes:

- in a glTF 2.0 document, the ``shapes`` array of the top-level
  ``KHR_implicit_shapes`` extension, which is then listed in
  ``extensionsUsed``;
- in a glTF 2.1 document (``asset.version`` 2.1 or later), the core top-level
  ``shapes`` array.

A 2.1 document that also carries ``KHR_implicit_shapes`` resolves a zone's
shape against the core array, since that is the one its version defines. A
tool moves a document from 2.0 to 2.1 by moving the array to the top level and
changing nothing in its zones.

A zone's shape is a ``box``, ``sphere``, ``capsule`` or ``cylinder``, with the
dimensions and defaults the shape specification gives it: centred on the
node's origin, with a capsule's and a cylinder's axis along +Y. A ``plane``
bounds no volume and is not a zone's shape.

A glTF 2.1 ``boundingVolume`` on a zone node, where a document carries one,
encloses the same box and is not what defines the zone.

Properties
----------

.. list-table::
   :header-rows: 1
   :widths: 16 12 10 62

   * - Property
     - Type
     - Default
     - Meaning
   * - ``shape``
     - integer
     - required
     - Index of the region's shape in the shape table.
   * - ``priority``
     - integer
     - 0
     - Where zones overlap, the higher priority's block for an extension is
       the one applied.
   * - ``blend``
     - number
     - 0
     - Metres beyond the shape's surface over which the zone's effect fades
       to nothing.
   * - ``environment``
     - object
     - none
     - The image-based lighting of what is drawn inside the zone; see
       `The environment`_.
   * - ``reverb``
     - object
     - none
     - The reverb heard while the camera is inside the zone; see
       `The reverb`_.
   * - ``extensions``
     - object
     - none
     - Extension name to that extension's block, or ``false``.

``environment`` and ``reverb`` are properties of ``OGLC_zone`` itself because
no extension defines either: none scales the environment lighting in place,
and none describes the acoustics of a space. A block under ``extensions``
always means what that extension's own specification says.

Rules
-----

1. The shape is in the node's local space, so the node's world transform
   places, rotates and scales it. A box is an oriented box.
2. A block under ``extensions`` is the form that extension takes at scene
   level. For an extension with no scene-level form, the block is the one this
   specification gives under `Subjects`_. Inside the shape the block applies
   to the extension's subject as a scene block would apply everywhere.
3. ``false`` in place of a block switches that extension off inside the
   shape: ``"KHR_lights_punctual": false`` turns off every punctual light for
   what is inside, except a light a zone names. An engine hook kind
   is addressed under ``OGLC_hook`` by kind, so ``"OGLC_hook": {"mirror":
   false}`` stops mirrors drawing their reflection for a camera inside.
4. Something a zone switches on (a light, an emitter, a mirror, a node to
   show) is controlled by zones: it is on for a subject inside a zone that
   names it, and off for a subject outside every such zone. A node no zone
   names behaves as it would in a document with no zones.
5. Where zones overlap, each extension is decided on its own. Zones are
   stacked by ``priority``, and a tie goes to the zone with the smaller shape
   volume, the more specific one. Each zone covers the ones beneath it by its
   weight (rule 6), so a zone wholly inside a higher one has no effect, and at
   the edge of the higher one the two cross-fade. Two extensions may be
   decided by different zones for the same subject.
6. A zone's weight at a point is 1 on and inside its shape's surface and
   falls to 0 at ``blend`` metres outside it, as a smoothstep of the signed
   distance to the surface. With a ``blend`` of 0 the edge is hard.
7. An extension name no reader is registered for is ignored, and the zone's
   other blocks still apply. A document names extensions; which code handles
   each is decided by the engine and the application.
8. ``OGLC_zone`` goes in ``extensionsUsed`` and never in
   ``extensionsRequired``, so a viewer that does not read it loads the
   document and shows it without zones.

Subjects
--------

Each extension decides what is tested against the zone. There are three kinds
of subject: what is drawn, the camera, and physics bodies.

.. list-table::
   :header-rows: 1
   :widths: 22 30 14 34

   * - Extension
     - Block in a zone
     - Subject
     - Effect inside
   * - ``environment`` (own)
     - ``{"intensity": n, "capture": ...}``
     - each drawn fragment
     - the image-based lighting is scaled, or taken from a probe captured
       inside the zone
   * - ``EXT_lights_image_based``
     - ``{"light": n}``, its scene form
     - each drawn fragment
     - the image-based light ``n`` lights what is inside, scaled by
       ``environment.intensity``
   * - ``KHR_lights_punctual``
     - ``{"nodes": [i, ...]}``, naming nodes that carry lights
     - each drawn object
     - the named lights light the object
   * - ``KHR_audio_emitter``
     - ``{"emitters": [i, ...]}``, its scene form
     - the camera
     - the named emitters are heard, their gain scaled by the zone's weight
   * - ``reverb`` (own)
     - ``{"level": l, "decay": s, "damping": d}``
     - the camera
     - everything heard carries the zone's reverb
   * - ``KHR_node_visibility``
     - ``{"nodes": [i, ...], "visible": true}``
     - the camera
     - the named nodes are drawn (``visible`` true) or hidden (false)
   * - ``OGLC_hook``
     - ``{"mirror": false}`` or ``{"mirror": {"nodes": [i, ...]}}``
     - the camera
     - the named mirrors draw their reflection; ``false`` stops every other
       mirror's
   * - ``OMI_physics_gravity``
     - a gravity volume's block
     - each physics body's centre
     - the block's field applies to the body

What is drawn is tested per fragment for the environment, so a wall that is
one mesh with a face inside the zone and a face outside it is lit differently
on its two faces, and per object for lights. The camera is the position of the
view being drawn; audio has one listener, at the main view's camera.

``KHR_audio_emitter`` emitters a zone names are the document's own: an emitter
placed on a node plays from there, and a global emitter the document places
nowhere else plays for the zone. A zone's weight multiplies an emitter's gain,
so a room's ambience fades out over ``blend`` as the camera leaves it.

In a gravity volume's block, ``direction`` and ``center`` are in the zone
node's frame. The volume's priority is the zone's.

The environment
---------------

.. list-table::
   :header-rows: 1
   :widths: 16 12 10 62

   * - Property
     - Type
     - Default
     - Meaning
   * - ``intensity``
     - number
     - 1
     - Multiplies the environment's diffuse and specular light.
   * - ``capture``
     - boolean or object
     - false
     - Captures an environment probe inside the zone: ``true`` from the
       shape's centre, ``{"position": [x, y, z]}`` from a point in the node's
       frame.

Without a capture, the zone scales the scene's environment by ``intensity``.
With one, the probe captured inside the zone replaces the scene's environment
there, scaled by ``intensity``: a room is lit by its own walls and doorway
rather than by the sky. Baked lighting (lightmaps and light grids) is not
scaled, since a bake already records its own occlusion.

A capture is a render of the scene into the six faces of a cube from the
capture position, convolved as the scene's environment probe is. An
implementation captures when the zone is first needed and may capture again,
each capture drawing the zone's surfaces lit by the one before. The first
capture draws them with no environment light, so a room's probe is built from
the direct light reaching it and what is seen through its openings.

The reverb
----------

.. list-table::
   :header-rows: 1
   :widths: 16 12 10 62

   * - Property
     - Type
     - Default
     - Meaning
   * - ``level``
     - number, 0 to 1
     - 0.4
     - How loud the reverb is against the dry sound.
   * - ``decay``
     - number, seconds
     - 1.5
     - The time a sound takes to fall by 60 dB.
   * - ``damping``
     - number, 0 to 1
     - 0.4
     - How much of the high frequencies each return loses.

The reverb applies to everything the listener hears while the camera is
inside the zone. Its level is scaled by the zone's weight, and where zones
overlap the decay and damping are the zones' weighted mean.

Example: glTF 2.0
-----------------

The two rooms of a temple's cella. The eastern room's door light lights only
what is in it, and the western room plays a room tone and has a reverb.

.. literalinclude:: examples/OGLC_zone-2.0.gltf
   :language: json

:download:`OGLC_zone-2.0.gltf <examples/OGLC_zone-2.0.gltf>`

Example: glTF 2.1
-----------------

The same zones. The shapes are the core array, and ``KHR_implicit_shapes`` is
not used.

.. literalinclude:: examples/OGLC_zone-2.1.gltf
   :language: json

:download:`OGLC_zone-2.1.gltf <examples/OGLC_zone-2.1.gltf>`

JSON schema
-----------

.. literalinclude:: schema/node.OGLC_zone.schema.json
   :language: json

:download:`node.OGLC_zone.schema.json <schema/node.OGLC_zone.schema.json>`

Implementation notes
--------------------

A renderer need not weigh every zone for every fragment. Classifying each
object against each zone first leaves three cases: the object is clear of the
zone and its blend band, and the zone is left out; it is wholly inside, and
the zone is a constant for the whole draw; or it crosses the surface or the
band, and only then is the zone weighted per fragment. The signed distance to
a box is a handful of arithmetic operations once the fragment's world position
is in the box's frame.

A zone whose shape is scaled unevenly keeps its box exact. A sphere becomes an
ellipsoid; OpenGLContext measures a capsule or cylinder with its length scaled
along +Y and its radii by the mean of the other two scales, and a zone meant
to be flattened is best authored as a box.

Known implementations
---------------------

- OpenGLContext: every subject above. An ``EXT_lights_image_based`` light
  named by a zone is uploaded into a layer of the probe arrays when the zone
  is first needed, with nothing drawn; a scene's own light fills the scene's
  layer. See :doc:`../zones`.
