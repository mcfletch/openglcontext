Zone Internals
==============

.. rst-class:: introduction

How zones are implemented: reading them from a file, placing them each frame,
deciding what reaches each draw, weighting them per fragment, capturing their
probes, and handing their sound and gravity to the audio and physics engines.
This page is for extending zones or tracing a lighting question through the
renderer. Using zones is covered in :doc:`zones`.

The modules
-----------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Module
     - Provides
   * - ``scenegraph/zones.py``
     - The arithmetic, with no GL and no scenegraph: shape specs, placing a
       shape by a matrix, signed distances, the blend weight, classifying a
       box against a shape, and layering zones by priority.
   * - ``scenegraph/zone.py``
     - The ``Zone`` node and one node per kind of setting, and
       ``placed_zones``, which places a frame's zones.
   * - ``loaders/gltf/shapes.py``
     - The document's shape table: the 2.1 core ``shapes`` array or
       ``KHR_implicit_shapes``.
   * - ``loaders/gltf/zoning.py``
     - Reads ``OGLC_zone`` into ``Zone`` nodes through a registry of readers,
       one per extension name.
   * - ``passes/zonelayers.py``
     - What zones give one draw, one camera and one listener, and the packed
       arrays the shader reads. No GL.
   * - ``passes/zoneprobes.py``
     - When each zone is captured and which probe layer it has
       (``CaptureSchedule``, no GL), and the cube a capture is drawn into
       (``CaptureTarget``).
   * - ``passes/zonepass.py``
     - The render pass's side: placing zones each frame, applying them per
       draw, drawing captures, and the camera's visibility and mirror
       decisions.
   * - ``shaders/_zone_inc.glsl``
     - The per-fragment signed distances and layering.
   * - ``audio/areas.py``
     - ``apply_zones``: emitter gains and the reverb from the listener's
       position.
   * - ``physics/zones.py``
     - Zones as ``omi_physics`` gravity volumes.

Placing a zone
--------------

A shape is centred on its node's origin, round about +Y. ``zones.place`` takes
the node's world matrix apart into a rigid frame and a scale along each local
axis, and folds the scale into the dimensions: a box's half extents are
multiplied exactly, a sphere scaled unevenly becomes an ellipsoid, and a
capsule or cylinder takes its length from the Y scale and its radii from the
mean of the other two. What is left is a rigid world-to-shape transform, so
every distance measured in the shape's frame is a distance in metres.

The signed distances are the exact ones for a box, a sphere, a capped cone
(a cylinder whose ends may differ) and a round cone (a capsule whose ends may
differ), and the usual close approximation for an ellipsoid. The weight at a
distance ``d`` is 1 for ``d <= 0`` and ``1 - smoothstep(0, blend, d)`` beyond.

``placed_zones`` keeps each zone's placement against the matrix object the
scenegraph's transform cache handed over, which is the same object for as
long as the node has not moved, together with the zone's shape and rules and
each of its settings with a count of the times a field of that setting has
been set (``setting_version``). A still, unedited zone is placed once and
keeps its ``PlacedZone``; moving the zone, editing any field of it or of one
of its settings, or giving it other settings makes a new one, and a new
``PlacedZone`` is how the pass learns that a zone changed. A zone met at more
than one path (a ``USE``) is a placement for each.

Layering
--------

For one setting, the zones reaching a place are stacked by
``(priority, -volume)``: higher priority on top, and within a priority the
smaller zone on top. Each layer takes its weight's share of whatever the
layers above it left: the top layer takes ``w``, the next ``w' * (1 - w)``,
and so on, and what remains is the world outside every zone. A zone wholly
inside a higher one keeps nothing, and at the higher one's edge the two
cross-fade over its blend. ``zones.layers`` does this on the CPU for the
camera and for classification, and ``zoneShares`` in ``_zone_inc.glsl`` does
the same per fragment.

A setting that is not enabled keeps its layer with nothing in it: it takes its
share from the zones below and gives it to nothing, which is how a zone
switches an extension off.

What a draw is given
--------------------

``FlatPass`` gathers ``Zone`` paths with its other interesting types, and
``placeZones`` places them once a frame, before the audio and the views. For
each draw, ``applyZones`` sits beside ``applyLightGrid`` in the opaque,
transparent and transmissive loops, and ``applyZonesToGroup`` covers an
instanced group with the box around all its members.

The pass classifies each object's world box against the zones with an
environment (``ZoneTable.classify_many`` over a table of them, then
``stacked`` and ``chosen``; ``environment_layers`` is the same for one
object):

- clear of the zone and its blend band, and the zone is left out;
- wholly inside, and the zone is a constant for the draw (shader kind 0);
- crossing the surface or the band, and the zone is weighted per fragment.

The zones reaching the object are stacked, and every zone beneath the topmost
one the object is wholly inside is dropped, since that one covers the whole
object. At most four layers go to the shader. An object crossing more keeps
the zone it is wholly inside, where there is one, and gives the rest of the
layers to the zones nearest the camera, chosen again as the camera moves
``CAMERA_CELL`` (32 m).

The answer is packed into four uniform arrays (kinds, world-to-shape matrices,
dimensions, and intensity, blend and probe layer) and kept per object with the
path, the world matrix and the bounding volume it was worked out for. A still
scene pays a dictionary lookup per draw. Uploads happen only when the pack
differs from the last draw's, and draws are sorted by material, so a run of
objects in the same room uploads once. What moves an object's answer on:

- The object moving further than its slack, being scaled up, or having new
  bounds (a node's cached bounding volume is a new object when its bounds
  change). The slack is the room its bounding sphere has before it could
  cross a zone's surface or the edge of its blend band
  (``ZoneTable.sphere_slack``); only the zones within ``slack_reach`` (60 m)
  are measured, so the slack is never more than that less the sphere's
  radius.
- A zone near it coming, going, moving or being edited. Each classified
  object has a row in ``ObjectBoxes``: its world box grown to the sphere its
  slack lets it move in. When a zone's placement changes, the objects whose
  row overlaps the zone's reach where it was or where it is are marked stale
  and classified again when next drawn; the rest keep their answers.
- The pass's probe version (``_probeVersion``): a capture or an upload
  finishing, a capture starting or ending, a probe lost, the environment mode
  changing. The object's probe layers are read again, and it is packed again
  only if they differ.
- The slot version (``_slotVersion``): the lights bound in a different order.
  Only the light mask is made again.
- ``_zoneEpoch``, which lets go of every answer at once when more than
  ``KEPT_LIMIT`` objects or groups are kept, as a streamed world's objects come
  and go.

The objects that did move are classified together
(``ZoneTable.classify_many``). The boxes are taken ``chunk`` (512) at a time,
and each chunk is carried only into the frames of the zones whose world reach
overlaps one of its boxes, so the memory a call takes is bounded by the chunk
and the zones near it. The table also keeps each zone's reach in an
``omi_physics`` dynamic AABB tree, the physics engine's broad phase, which
``sphere_slack`` queries for the zones near a set of spheres.

An instanced group is kept under the group's own key, the same whichever of
its members are drawn, with the member matrices and bounds its box was made
from. The box is made again when those are other objects.

The lights are classified the same way, against a table of the zones with a
lights setting: ``light_decision`` turns what that table answers into the
lights the zones switch on for the object and whether it is wholly inside a
zone that switches them off, and ``light_mask`` turns that into the
``lightsOff`` mask of light slots to skip, read by the light loop in
``pbr.frag``. ``lights_off`` is the same for one object.
``setupShaderLights`` records which light went into which slot
(``boundLights``).

Per fragment
------------

``pbr.frag`` works out each fragment's world position from ``vPosition`` and
``eyeToWorld`` and calls ``zoneShares`` once. For a layer of kind 0 the
weight is 1; for a shape it takes the world position through the layer's
world-to-shape matrix (twelve multiply-adds) and computes the signed distance
(about eight operations for a box). The shares it leaves are read by the two
helpers every environment term goes through: ``envIrradiance`` for the
diffuse and back-lit terms and ``envRadiance`` for the specular, clearcoat,
sheen and planar-reflection sky. A draw reached by no zone has
``zoneLayers == 0`` and pays one loop test.

A layer reading the scene's environment folds into one sample of it, scaled
by the sum of those shares. A layer with a probe of its own samples that
probe's layer of the arrays.

A fill-bound frame with four zones crossing every fragment is timed against
the same frame without them in ``test_zones_cost_a_fill_bound_frame_little``.

Probes
------

All 32 fragment texture units of the PBR program are committed, so a zone's
probe cannot have units of its own. Instead, where the driver has cube-map
arrays (GL 4.0, the same condition the point-shadow cube arrays use), the
program is compiled with ``PBR_ZONE_PROBES`` and the scene's irradiance and
prefiltered maps become cube-map arrays: layer 0 is the scene's environment
and each captured zone has a layer of its own. ``IBLProbe(layers=n)`` builds
them that way; ``grow`` reallocates at the next power of two and copies the
filled layers across with ``glCopyImageSubData``, or counts them as lost
where that call is missing, and the schedule captures them again.

A capture (``renderZoneProbes``) runs after ``iblPrepare`` and before the
mirrors, so everything drawn that frame reads it. For each face it builds a
``ViewFrame`` with ``shadowmath.cube_face_view`` and a 90-degree projection,
culls the frame's walk through it with ``renderSet``, draws the background
with the face's turn, sets up the lights, shadows and environment for that
eye space, and draws the opaque records in linear HDR into a 128-pixel
``RGBA16F`` cube. Planar reflections are left out of a capture, since no
mirror was drawn for its camera. After the sixth face the cube is mip-mapped
and ``IBLProbe.convolve`` fills the zone's layer with the same irradiance and
prefilter programs the scene's probe uses.

A capture that raises while it is drawn is logged once with its traceback,
and that zone is given no more captures (``CaptureSchedule.failed``); the
other zones' layers are kept. A zone whose whole cube the probe refuses
``ATTEMPTS`` (3) times is given up the same way, with a warning. Either way
the zone reads the scene's environment until the probes are lost and made
again, when every zone is captured afresh.

While a zone is being captured for the first time, its own layer reads
``NO_ENVIRONMENT`` (probe index -2), so the first capture holds the direct
light and what is seen through the zone's openings. Outside a capture, a zone
whose probe is not ready reads the scene's environment scaled by its
intensity.

``CaptureSchedule`` asks for a zone's capture the first time
``zoneProbeLayer`` is asked for it during a draw, two captures in all, and once
more the first time the camera is inside it. It captures one zone at a time,
nearest the camera first, drawing ``zoneCaptureFaces`` faces a frame, and asks
the context for another frame while a capture waits.

The camera
----------

Audio, visibility and mirrors are decided at a camera position with
``zones.layers`` and ``named_shares``: the share of the zones naming a thing
that the point is in. ``zoneWeightsAt`` weighs every zone at a point in one
pass (``point_weights``) and keeps the answer while the zones and the point
are the same, so the questions a view asks from its camera share it.

- ``apply_zones`` sets each zone-controlled ``AudioEmitter``'s ``zoneGain``,
  which its record multiplies into the emitter's gain, and sets the engine's
  ``reverb`` (``omi_audio.reverb``: a comb-filter reverb on the whole mix)
  from the zones' levels, decays and dampings mixed by their shares.
- ``zoneHiddenAt`` gives the nodes hidden from a camera. ``prepareViews``
  sets it for each view before culling it, and ``renderSet`` leaves out a
  record with a hidden node on its path; the active view's set stands for the
  frame's other draws (shadows, mirrors, captures).
- ``mirrorAllowed`` is handed to the ``ReflectionPlanner`` as its ``allowed``
  predicate while any zone has a mirror setting, and a mirror it refuses is
  not planned.

Reading the file
----------------

``ZoneReader.zone_for`` runs for each glTF node during the scene build and
makes the ``Zone``, with its shape from the shape table and its own
``environment`` and ``reverb`` blocks. Blocks under ``extensions`` wait for
``finish``, after every node is built, since a zone may name a light or an
emitter anywhere in the document. Each is handed to the reader registered for
its name, with a ``ZoneReading`` that resolves node indices to the scenegraph
nodes built for them. A global emitter the document places nowhere else is
built at the root for the zone to play.

``fastdecode`` keeps a 2.1 document's top-level ``shapes`` array as an
attribute of the decoded document, since pygltflib's ``GLTF2`` has no field
for it.

Tests
-----

``tests/unit/test_zones.py`` (distances, classification, layering),
``test_gltf_zones.py`` (the reader, against the specification's examples),
``test_zone_layers.py`` (draw, camera and capture decisions),
``test_pbr_zones.py`` (the shader contract, the pass, audio, gravity, renders
from ``tests/helpers/_zone_capture.py`` and the fill-bound timing) and
``test_tilesterrain_zones.py`` (a streamed world's zones).
