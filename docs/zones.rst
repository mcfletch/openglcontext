Zones
=====

.. rst-class:: introduction

A zone is a region of space with settings that hold inside it: the image-based
lighting of a room instead of the sky's, a lamp that lights only its own room,
birdsong heard only in the forest, the reverb of a tunnel, gravity inside a
volume. This page shows how to use zones, from code and from a glTF file.
:doc:`zones-internals` describes how the renderer implements them, and
:doc:`extensions/OGLC_zone` is the specification of the glTF extension.

.. contents:: On this page
   :local:
   :depth: 1

What a zone does
----------------

A ``Zone`` node is a shape -- a box, sphere, capsule or cylinder -- placed by
the transforms above it, and a list of settings. Each setting applies to its
own subject:

.. list-table::
   :header-rows: 1
   :widths: 22 20 58

   * - Setting
     - Subject
     - Inside the zone
   * - ``ZoneEnvironment``
     - each drawn fragment
     - The environment (image-based) lighting is scaled by ``intensity``, or
       taken from a probe captured inside the zone.
   * - ``ZoneLights``
     - each drawn object
     - The named lights light the object. Outside every zone naming them they
       light nothing.
   * - ``ZoneAudio``
     - the camera
     - The named emitters are heard, fading out over the zone's ``blend``.
   * - ``ZoneReverb``
     - the camera
     - Everything heard carries the zone's reverb.
   * - ``ZoneVisibility``
     - the camera
     - The named nodes are drawn (``visible`` true) or hidden (false).
   * - ``ZoneMirrors``
     - the camera
     - The named mirrors draw their reflection. Not enabled, it stops every
       other mirror's reflection.
   * - ``ZoneGravity``
     - each physics body
     - The body feels the zone's gravity.

The environment is tested per fragment, so a wall that is one mesh with its
inside face in a room's zone and its outside face in the street is lit by the
room on one face and the sky on the other.

``priority`` decides between overlapping zones: the higher one wins, and a tie
goes to the smaller zone, the more specific one. ``blend`` is how many metres
beyond the shape a zone's effect takes to fade to nothing, so a doorway or a
tunnel's portal changes gradually. Each kind of setting is decided on its own,
so one zone can decide an object's lighting while another decides what the
camera hears.

A setting whose ``enabled`` is false switches its kind off inside the zone:
``ZoneLights(enabled=False)`` turns off every light for what is inside,
except a light a zone names.

Zones from code
---------------

.. code-block:: python

   from OpenGLContext.scenegraph.basenodes import (
       AudioEmitter, AudioSource, SpotLight, Transform, Zone, ZoneAudio,
       ZoneEnvironment, ZoneLights, ZoneReverb,
   )

   door_light = SpotLight(location=(22.75, 6.0, 0), direction=(-1, -0.2, 0),
                          cutOffAngle=1.2, beamWidth=0.2, castShadows=True)
   fountain = AudioEmitter(type='global', sources=[
       AudioSource(url=['sounds/fountain.ogg'], loop=True, autoplay=True)])

   hall = Transform(translation=(7.3, 6.6, 0.0), children=[
       Zone(size=(29.6, 10.2, 19.06), blend=1.0, settings=[
           ZoneEnvironment(capture=True),
           ZoneLights(lights=[door_light]),
           ZoneAudio(emitters=[fountain]),
           ZoneReverb(level=0.3, decay=2.4, damping=0.35),
       ])])

   scene.children = [hall, door_light, fountain, building]

The zone goes anywhere in the scenegraph; its transform places it. The lights
and emitters it names stay where they are in the scene. A zone moved at
runtime is placed again on the next frame.

Zones in a glTF file
--------------------

A glTF node carrying ``OGLC_zone`` loads as a ``Zone`` under that node's
``Transform``. The shape comes from the document's shape table:
``KHR_implicit_shapes`` in a glTF 2.0 file, or the core ``shapes`` array in
glTF 2.1.

.. code-block:: json

   {"name": "naos-interior", "translation": [7.3, 6.6, 0.0],
    "extensions": {"OGLC_zone": {
      "shape": 0, "blend": 1.0,
      "environment": {"capture": true},
      "reverb": {"level": 0.3, "decay": 2.4},
      "extensions": {"KHR_lights_punctual": {"nodes": [5]}}}}}

Each entry of ``extensions`` is that extension's scene-level block, or
``false`` to switch the extension off inside the zone. The loaded scene lists
its zones in ``GLTFScene.zones``. The specification, with complete 2.0 and 2.1
examples, is :doc:`extensions/OGLC_zone`.

The extensions the loader reads in a zone are ``KHR_lights_punctual``,
``KHR_audio_emitter``, ``KHR_node_visibility``, ``OGLC_hook`` (the ``mirror``
kind), ``OMI_physics_gravity`` and ``EXT_lights_image_based``. A name nothing reads is logged once and the
zone's other settings still apply. An application reads another extension in
zones by registering a reader:

.. code-block:: python

   from OpenGLContext.loaders.gltf import zoning
   from OpenGLContext.scenegraph.zone import ZoneReverb

   @zoning.register_scoped('GAME_acoustics')
   def acoustics(block, reading):
       return ZoneReverb(level=float(block.get('wet', 0.4)))

A reader returns a setting node, or None. ``reading`` gives it the document,
the zone, and the scenegraph nodes built for the document's node, light and
emitter indices. ``reading.values`` is a
``loaders.documentvalues.DocumentValues`` for reading the block's numbers,
flags and vectors: a value it cannot use is logged once for the document and
the reader's default is used. An exception out of a reader is logged and that
extension is left out of the zone.

A value in the zone's own block that is no number of the right kind is logged
once and left at its default -- ``priority`` 0, ``blend`` 0, an
``environment`` ``intensity`` of 1, the reverb's 0.4, 1.5 s and 0.4 -- and a
value outside its range is the nearer end of it: a ``blend`` or an
``intensity`` below 0 is 0, and a reverb ``level`` or ``damping`` is held
between 0 and 1. A shape that is not a zone's -- a box without three sizes, a
negative or non-finite dimension -- is logged, and the node is no zone. The
document loads either way.

Environment lighting
--------------------

``ZoneEnvironment(intensity=0.12)`` scales the scene's environment inside the
zone. It is the cheap way to darken a roofed room, and it works with any
environment mode, including ``analytic`` and ``off`` (where it scales the flat
ambient).

``ZoneEnvironment(capture=True)`` lights the zone by what can be seen from
inside it. The renderer draws the scene into a cube from ``captureCentre``
(in the zone's own frame, its centre by default) and convolves it into a probe,
which replaces the scene's environment inside the zone. A room lit through one
door is then dark with a bright doorway, and its metals and water reflect the
room rather than the sky. ``intensity`` scales the captured probe.

A captured zone is drawn:

- when something it lights is first drawn, twice: the first capture draws the
  zone's own surfaces with no environment light, only direct light and what is
  seen through its openings, and the second draws them lit by the first, one
  bounce more;
- once more the first time the camera is inside it, since a streamed world may
  not have loaded what surrounds a zone until the camera is near it.

At most one zone is captured a frame, nearest to the camera first. Each
capture is six draws of the scene into a 128-pixel cube; ``zoneCaptureFaces``
(``OPENGLCONTEXT_ZONE_CAPTURE_FACES``) spreads one capture over several
frames, from 6 faces a frame down to 1.

Captures need the ``full`` environment probe and a GL 4.0 driver (or
``ARB_texture_cube_map_array``), since a zone's probe is a layer of the
cube-map array the scene's probe is kept in. Elsewhere a capturing zone scales
the scene's environment by its ``intensity`` instead.

A zone can also be lit by a probe the file ships already convolved: an
``EXT_lights_image_based`` light, named in the zone's ``extensions`` block as
``{"light": n}`` (``ZoneEnvironment(light=...)`` from code). It is uploaded
into its layer the first time the zone is needed and nothing is drawn, which
is how a baked world should carry its places' environments. A scene's own
``{"light": n}`` lights everything no zone covers. A four-channel PNG face is
read as RGBD HDR, other images as the values they hold.

Lightmaps and light grids are not scaled by a zone: a bake already holds its
own occlusion.

Lights
------

A light a ``ZoneLights`` names lights an object only where the object is
inside or crossing a zone that names it, so a room's lamp does not light the
far side of its wall. The decision is per object: a floor that runs from one
room into another is lit by both rooms' lights.

Sound
-----

An emitter a ``ZoneAudio`` names is heard only while the camera is in a zone
naming it, and fades out over the zone's ``blend``. Several zones can name one
emitter -- birdsong in every stretch of forest along a road -- and it plays at
the share of those zones the camera is in. An emitter no zone names is heard
as it would be in a scene with no zones.

``ZoneReverb`` gives everything heard the reverb of the place: ``level`` from
0 to 1, ``decay`` in seconds (the time a sound takes to fall by 60 dB) and
``damping`` from 0 to 1. A car in a tunnel hears its own engine and tyres come
back off the walls. The reverb fades in over the zone's ``blend``; see
:ref:`audio-areas` for background sound in general, and
``omi_audio.reverb`` for the reverb itself.

Visibility and mirrors
----------------------

``ZoneVisibility(nodes=[...], visible=True)`` draws the nodes only for a
camera inside the zone: the contents of a room nobody can see from outside.
With ``visible`` false the nodes are hidden from a camera inside. Each view
decides for its own camera.

``ZoneMirrors(nodes=[...])`` lets the named mirrors draw their reflection
only for a camera inside the zone, which saves a mirror's scene draw while no
one can see it. ``ZoneMirrors(enabled=False)`` stops every other mirror's
reflection for a camera inside. A mirror seen in another mirror is judged by
where the viewer stands, not by the reflected camera behind the mirror. A
mirror with no reflection reflects the environment probe. See
:doc:`reflections`.

Gravity
-------

A ``ZoneGravity`` is an ``OMI_physics_gravity`` volume over the zone's shape:
``type`` ``directional`` (along ``direction``) or ``point`` (towards
``center``), both in the zone's own frame, with ``gravity`` in metres per
second squared and ``replace`` and ``stop`` as the extension defines them.
:func:`~OpenGLContext.physics.gltf_world.collision_world_from_scene` adds a
volume for every such zone to the physics world it builds, and
:func:`OpenGLContext.physics.zones.gravity_volumes` gives them to a world
built another way.

Zones in a streamed world
-------------------------

A 3D Tiles world carries its zones as a glTF document beside its tileset,
named in the tileset's extras:

.. code-block:: json

   "extras": {"zones": {"document": "zones.gltf"}}

``TilesTerrain`` loads the document once and keeps it mounted beside the
tiles, so a zone that runs through many tiles is never unloaded with one of
them. The name must resolve under the tileset's directory, or on its origin
for a served world. A document that is outside that reach, or does not load,
is logged as a warning and the world is built without zones. ``TilesTerrain.zones`` is the loaded scene. ``OpenGLContext_editor``'s
``ZonesLayer`` writes the document when a world is baked; see :doc:`baking`.

Limits
------

- One object can be reached by at most four zones' environments at once (the
  one it is wholly inside, and three whose edges it crosses). A larger object
  keeps the zones nearest the camera, and says so once in the log at
  ``INFO``. Split a model at a zone boundary where that matters.
- A sphere under an uneven scale becomes an ellipsoid. A capsule or cylinder
  takes its length from the scale along its axis and its radii from the mean of
  the other two scales. An uneven zone is best authored as a box.
- A zone's lights are decided per object, and its environment per fragment.
- The environment of a zone applies to the PBR renderer. The splat terrain,
  vegetation and water shaders have environment lighting of their own and are
  not changed by zones.
- Audio has one listener, at the main view's camera.

Examples
--------

The Parthenon model (``parthenon/`` in the workspace) has a zone in each room
of the cella: a captured environment, the room's door light and a stone
reverb. Glisteel's baked worlds carry a zone for every tunnel, causeway, bridge
and wooded stretch of their circuit, each with a captured environment, and
birdsong, surf or a tunnel's reverb; see :doc:`glisteel`.
