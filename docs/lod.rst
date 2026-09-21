Levels of detail
================

.. rst-class:: introduction

LODs reduce the detail of a particular model based on distance or screen area,
swapping a lower-detail mesh into the scene below a given threshold. Often an
*impostor* mesh, such as a billboard or an octahedron, will be the
lowest-detail level of the LOD. OpenGLContext supports both distance-based
LODs (used in VRML97) and screen-coverage LODs (used in glTF's ``MSFT_lod``
extension).

.. _lod-demo:

Walk through it
---------------

.. code-block:: bash

   oglc-view https://github.com/mcfletch/openglcontext/releases/download/content-v1/gallery-world.tar.gz

.. figure:: images/demos/gallery.jpg
   :alt: A long hall of marble busts on plinths, two rows receding to a far wall under dark ceiling beams, on a parquet floor

   The gallery from the near end of the hall. The busts by the camera are
   drawn at 17,456 triangles each and the ones at the far end at 544, and the
   switch between the six levels of the chain is what this page is about.

A hall of a hundred and twenty marble busts on plinths. Each bust is a
six-level chain — 17,456 triangles down to 544 — declared with ``MSFT_lod``,
in a room with a polished parquet floor, white plaster walls and dark beams
overhead. The world is CC0 art published as a :doc:`content pack
<contentpacks>`; the viewer unpacks the archive once into a per-user directory
and opens the world inside it, so the second run downloads nothing. The
archive holds one scene, so nothing has to say which —
``...tar.gz#gallery.glb`` names it where an archive holds several.

The hall is lit by a pair of suns leaning in across it from above the roof,
with a weak upward light standing in for what the floor throws back. The shell
— floor, walls, ceiling — is marked as :ref:`no shadow caster <castsshadow>`,
so the light reaches the room while the plinths and the busts still throw the
shadows that give the hall its depth. Its lights are stated at the illuminance
the engine reads as neutral, so it needs no exposure flag and looks the same
with or without a sky behind its walls.

Walk down the hall with the arrow keys. The busts near you are at their finest
level and the ones at the far end at their coarsest, and because the level is
settled from how much of the window each one covers, the switch happens in the
middle distance — where you can walk back and forth over it and watch it
happen. ``PageUp``/``PageDown`` jumps between the two cameras the world
carries: down the hall, and up against one bust.

What it costs is the point. From the far end, with a hundred and eight busts
on screen across four levels, the frame is **eleven draw calls**: one per
level in use, one for the plinths, one for the beams, and the handful of room
surfaces. Not one per bust.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - On screen
     - Levels in use
     - Draws for the busts
     - Draws in the frame
   * - 108 busts
     - 4
     - 4
     - 11

It is an ordinary glTF file — the chains as ``MSFT_lod``, the polished floor
as ``KHR_materials_clearcoat``, the lamps as ``KHR_lights_punctual`` — so any
glTF viewer opens it, and one that has never heard of ``MSFT_lod`` draws every
bust at its finest level, which is the correct thing for it to do.

**Record the walk.** The world carries the two cameras the walk is between, so
a recording of it is one command:

.. code-block:: bash

   oglc-view <the archive> \
       --capture-video walk.mp4 --fly-through --video-seconds 16

See :ref:`Recording a video <video>`.

.. _lod-choosing:

How a level is chosen
---------------------

By **screen coverage**: the share of the window's *height* the object's
bounding sphere spans, which is ``radius / (distance × tan(fov/2))``, clamped
to one. A model twice the size holds its detail twice as far out, and so does
the same model seen through a narrower field of view — because both are the
same question about how many pixels the viewer is actually looking at.

Each level names the coverage at which it takes over, decreasing. Level *i* is
drawn from its own threshold up to the one before it, and below the last value
nothing is drawn at all — so a chain that should stay on screen however small
it gets ends its list with ``0``.

The decision is made once a frame, before the scene is walked, by
``FlatPass.selectLevels``: a level change replaces a subtree, and the
flattened scenegraph the pass draws from has to be told about the new one
before it walks it. Only the camera decides — a shadow pass draws the same
scene from a lamp, and choosing detail by how far a *light* is from a figure
would swap levels as the sun moved.

.. _choosing-cost:

What choosing costs
~~~~~~~~~~~~~~~~~~~

A frame decides this for every level-of-detail node in the scene, so the
decision is made for the whole set at once. The nodes' world matrices are
stacked and put through the camera in one product, and the distances and the
scales come out of two array expressions — because each decision on its own is
a handful of four-by-four operations, and at that size a numpy call costs more
than the arithmetic in it. What is left per node is the part that is that
node's own: ``selectAt(distance, scale, tangent)`` asks which of its
thresholds the coverage falls in, and announces a change only where there is
one. ``selectFor(modelview, tangent)`` is the same decision for a single node,
for a caller that has one to place.

A frame in which neither the camera nor any of those nodes has moved chooses
what it chose last frame, so it does not choose again. The scenegraph's
transform cache is what makes that cheap to establish: it hands back the same
matrix object while a node is unmoved, so the question is one identity
comparison per node. On the gallery above, a still camera leaves 120 nodes
costing 0.40 ms a frame instead of 1.20; with the camera moving every frame,
where the shortcut never applies, it is 0.93.

.. _nodes:

The nodes
~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Node
     - Chooses by
     - Fields
   * - ``LOD``
     - Distance — VRML97's own
     - ``level``, ``range``, ``center``
   * - ``ScreenCoverageLOD``
     - Screen coverage — what ``MSFT_lod`` asks for
     - ``level``, ``screenCoverage``, ``center``, ``radius``

Both live in ``OpenGLContext.scenegraph.lod`` and announce a change on the
same signal a ``Switch`` uses. ``center`` is the point in the node's own
coordinates that distance is measured to, so a figure's distance is measured
to the figure and not to the world origin; ``radius`` is what its coverage is
judged by, and the glTF loader takes it from the finest level's ``POSITION``
accessor bounds — which the format requires a file to declare, so a level can
be sized and placed without its geometry being read.

.. _placement:

Where a level is drawn
~~~~~~~~~~~~~~~~~~~~~~

Every level of a chain is drawn where the node carrying the extension is. An
alternative named in ``ids`` stands *in place of* that node, so whatever
transform it states is in the same parent space rather than underneath —
applying both would put a bust two metres down a hall four metres down it, and
with a rotation in play somewhere else entirely. An alternative that asks to
stand somewhere of its own is drawn at the node's place and a warning says so,
because the extension offers another version of a node rather than another
place for it.

.. _instancing:

Copies batch per level
----------------------

The levels of a chain are decoded once and shared by every node that names
them, and the pass groups a frame's draws by the geometry and appearance they
share. So a field of copies of one model costs one instanced draw *per level
in use*: the copies drawing their finest level are one draw, the copies at the
coarsest are another, and a copy at a level of its own is drawn on its own.
Nothing has to be declared for this — it follows from the levels being shared.
See :doc:`Instanced rendering <instancing>`.

.. rst-class:: technical

A group smaller than eight is drawn one shape at a time: instancing has a
fixed per-batch cost, and a pair of shapes is cheaper drawn as a pair.

.. _impostors:

Where a mesh stops being worth it
---------------------------------

A chain's coarsest level is still a mesh, and past a certain distance a mesh
is the wrong thing entirely: a bust twenty pixels tall spends five hundred
triangles on a silhouette a picture would draw exactly. An **octahedral
impostor** is that picture — one view of the model per direction, folded onto
a single square texture, drawn on a card turned to the viewer that shows
whichever view matches where they are standing.

The fold is what makes it fit. Inflate an octahedron to the sphere of
directions, cut it along its equator and unfold it flat, and every direction
has a place on a unit square, with directions near each other in space landing
near each other on it. ``OpenGLContext.scenegraph.octahedral`` is that
arithmetic and holds no GL; ``pbr.vert`` is the same fold in GLSL, and the two
are held to each other by a test that paints each tile with its own address
and reads back which one the shader chose.

A material declares it, which is also what makes a field of them batch — they
share a material, so they share a draw:

.. code-block:: python

   "materials": [
     {"pbrMetallicRoughness": {"baseColorTexture": {"index": 4}},
      "alphaMode": "MASK",
      "extras": {"octahedralViews": 8, "octahedralHemi": true}}
   ]

``extras`` rather than an extension, because that is where the format puts
what an application knows and a reader that does not is meant to step over —
and only a reader that understood ``MSFT_lod`` reaches an impostor at all,
since it is a chain's coarsest level and a reader without the extension draws
the finest.

**hemi** holds the upper hemisphere and spends the whole square on it, which
is what a thing standing on the ground wants: nobody walks under a bust, and
the lower half would be half the resolution spent on views nobody takes.
``"octahedralHemi": false`` holds the whole sphere, for something seen from
any side.

.. _impostor-size:

How big the atlas has to be
~~~~~~~~~~~~~~~~~~~~~~~~~~~

A question about how small the model will be on screen when the impostor takes
over, and nothing else. At a threshold of three per cent of a 720-line window
the model is twenty-odd pixels tall, so a **256-pixel atlas at eight views a
side** — thirty-two pixels a view — covers it with room to spare. Twice as
many views is four times the texture for angles a distant object does not
resolve.

.. _impostor-cost:

What it buys, and when it buys nothing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An impostor lets a chain **stop decimating early**: four mesh levels and a
card carry a model further than six mesh levels do. On the gallery from its
far end, with a hundred and eight busts on screen, that is 62% of the
triangles and one draw call fewer:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Chain
     - Triangles in the busts
     - Draws
     - ms a frame, 1280×720
   * - 6 mesh levels
     - 103,536
     - 11
     - 4.96
   * - 6 mesh levels + an impostor
     - 90,620
     - 12
     - —
   * - 4 mesh levels + an impostor
     - 39,460
     - 10
     - 4.93

**And it makes that scene no faster at all.** Two hundred frames a second
either way, on a discrete-class GPU, because the frame is not waiting on
geometry: it is waiting on the engine. The same world renders in the same 5 ms
at 640×360 and at 1920×1080, and a four-object scene renders in 0.59 ms where
this three-hundred-object one takes 5.06 — about fifteen microseconds of
processor time per object per frame, whatever is in it. Triangles are not what
this costs.

**Where it does pay is where geometry is the bottleneck.** The same two worlds
on a software rasteriser, which is what a weak integrated part behaves like:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Chain
     - ms a frame (llvmpipe, 640×360)
   * - 6 mesh levels
     - 46.8
   * - 4 mesh levels + an impostor
     - **19.1**

Two and a half times faster, from the same change that bought nothing on the
discrete card. That is the rule to take away: an impostor is worth reaching
for when a frame is spending its time on vertices and fragments, and worth
nothing when it is spending it somewhere else. Measure which before baking
one.

.. rst-class:: technical

On the gallery the largest single item is not geometry either: **shadows cost
1.8 ms of the 4.96**, most of it gathering the casters. ``--no-shadows`` takes
the same scene from 202 to 316 frames a second.

.. _lod-authoring:

Authoring a chain
-----------------

Two routes, and they meet in the same file.

.. _blender:

In Blender
~~~~~~~~~~

It bakes the impostor too: ``--impostor 8`` renders the finest level from each
of the atlas's directions in Blender and makes the card the chain's last
level. The add-on in `openglcontext-editor
<https://github.com/mcfletch/openglcontext-editor>`__
(``OpenGLContext_editor/blender/openglcontext_lod``) adds an operator that
cuts a chain from the selected mesh with Blender's own Decimate modifier, and
a glTF export extension that writes the chain as ``MSFT_lod``. The ordinary
*File > Export > glTF 2.0* then produces a file this engine switches levels
in. That is how the gallery world is made, so what ships is what the add-on
produces rather than a second path that might disagree with it.

.. _baking:

As a bake
~~~~~~~~~

Making a chain is not something a game does at startup, so the measured route
lives in the editor too: ``OpenGLContext_editor.meshlod`` decimates a mesh
into levels, *measures* what each one costs to look at, and writes them with
the coarsest level inside the glb and each finer one a sidecar the operating
system never opens until it is wanted. Thresholds derived from measurement are
better than a halving series, and this is where they come from.

.. _format:

In the file
-----------

.. code-block:: python

   "nodes": [
       {"mesh": 0,
        "extensions": {"MSFT_lod": {"ids": [1, 2]}},
        "extras": {"MSFT_screencoverage": [0.5, 0.2, 0.01]}},
       {"mesh": 1},
       {"mesh": 2}
   ]

Coverage is a hint in the extension's own words, and a file may leave it out;
the levels are then switched on a halving series ending at zero, so a
threshold the *reader* guessed is never the reason something disappears. The
full reading, including what the node's children and lights do, is in
:ref:`glTF support <lod>`.

.. _lod-limits:

Limits
------

- **Every level is decoded at load.** A chain in one glb costs all of its levels
  in memory, whichever are on screen. The sidecar layout the baking tools write
  is what a streaming reader would need; the engine does not yet defer a level's
  decode.

- **The switch is a pop.** There is no geomorphing between levels yet, so a
  change of level is visible as one if you are looking for it. The
  correspondence a morph needs is already recorded by the decimator.

- **An impostor shows its nearest view, not a blend of the nearest few.**
  Turning past the angle between two baked views swaps one picture for another.
  At the sizes an impostor is drawn at that is hard to catch; blending the three
  nearest views is what would remove it.

- **An impostor is lit as it was baked.** The card carries the lighting the bake
  had -- an even white surround -- and does not respond to the lights around it.
  A model that walks from daylight into a cellar keeps its daylight at the
  distance the impostor takes over.

- ``MSFT_lod`` on a *material*, which the extension also allows, is not read.
