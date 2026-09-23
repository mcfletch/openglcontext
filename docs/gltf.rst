Loading glTF
============

.. rst-class:: introduction

OpenGLContext can load glTF 2.0 and binary GLB models and render them with the
:doc:`PBR renderer <pbr>`. This document covers what the loader supports and
how to load models from your own code; to *open* one, see :doc:`oglc-view
<viewer>`, the one viewer for every format this project reads.

File parsing is handled by `pygltflib
<https://gitlab.com/dodgyville/pygltflib>`__, a core dependency; OpenGLContext
maps the parsed glTF onto its own scenegraph and PBR materials.

Opening a model
---------------

Reading glTF needs no extra: ``pygltflib`` is a core dependency and the viewer
command is registered by the base install. The ``glfw`` extra is worth adding,
because that is the backend the viewer asks for:

.. code-block:: bash

   pip install "OpenGLContext[glfw]"

Then open a model -- a local file, a URL, or via the ``GLTF`` environment
variable:

.. code-block:: bash

   oglc-view path/to/model.glb
   oglc-view https://example.com/model.glb
   GLTF=path/to/model.gltf oglc-view

Everything about the viewer itself -- what else it opens, its controls, its
library of samples, capturing a frame, embedding it -- is in :doc:`The viewer
<viewer>`. What follows here is glTF-specific.

The viewer selects the core profile, the PBR renderer, the GLFW backend and
shadows for you, so you do not need to set any environment variables. A binary
``.glb`` is self-contained, so URLs to a ``.glb`` work directly.

A model loaded into a compatibility-profile context is drawn by the
fixed-function pass. Its materials are lit through ``glMaterial`` from their
factors -- the base colour as the diffuse colour, metalness and roughness as the
highlight, the emissive colour at its strength as the emission -- and the base
colour map is drawn over them. The other maps, image-based lighting and GPU
skinning are the PBR pass's; a skinned model is posed on the CPU there.

A non-binary ``.gltf`` usually references external ``.bin`` and texture files,
by URI *relative to the document*. A URL therefore goes through
``load_gltf_url()`` (below), which keeps hold of where the document came from
and resolves those references against it, so a remote multi-file ``.gltf``
opens with its geometry and textures intact. Fetching the document by itself
could not: the base URL is gone by then and the relative references have
nowhere to resolve from.

External resources are fetched through the same hardened resolver the rest of
the loader uses — same-origin, size-capped and disk-cached — so a document
cannot pull in a reference from somewhere else. What a file you did not write
is allowed to reach, across every loader, is :doc:`Loading content you did not
write <untrusted>`.

Controls
~~~~~~~~

These are OpenGLContext's default view-platform navigation keys:

- Up / Down -- walk forward / back.

- Left / Right -- turn (yaw) left / right.

- Ctrl+Up / Ctrl+Down -- look up / down (pitch).

- Alt+Up / Alt+Down -- move up / down (fly).

- Alt+Left / Alt+Right -- strafe (slide) left / right.

- ``-`` levels the horizon.

- Right-mouse drag orbits about a point.

- PageUp / PageDown (or ``p`` / ``n``) cycle through the model's baked cameras,
  if it has any.

If the file contains no lights, the viewer adds a default sun-plus-fill rig so
the model is never in the dark.

.. _gallery:

Sample Gallery
--------------

These are Khronos glTF sample models rendered by the PBR pass. Each shows a
different part of the material model.

.. figure:: images/gltf/DamagedHelmet.jpg
   :alt: DamagedHelmet

   DamagedHelmet -- base colour, metallic/roughness, normal and emissive maps.

.. figure:: images/gltf/MetalRoughSpheres.jpg
   :alt: MetalRoughSpheres

   MetalRoughSpheres -- a sweep of metalness and roughness.

.. figure:: images/gltf/WaterBottle.jpg
   :alt: WaterBottle

   WaterBottle -- brushed metal and printed labels.

.. figure:: images/gltf/BoomBox.jpg
   :alt: BoomBox

   BoomBox -- fine metal and plastic detail at small scale.

.. figure:: images/gltf/BarramundiFish.jpg
   :alt: BarramundiFish

   BarramundiFish -- organic surface with a subtle clearcoat.

.. figure:: images/gltf/Duck.jpg
   :alt: Duck

   Duck -- a classic simple textured model.

.. figure:: images/gltf/IridescentDishWithOlives.jpg
   :alt: IridescentDishWithOlives

   IridescentDishWithOlives -- glass transmission
   (``KHR_materials_transmission``).

.. rst-class:: technical

The loader knows the names of the Khronos sample models and can fetch them on
demand, which is how ``oglc-gltf-demo`` browses the whole sample set with
side-by-side reference screenshots.

What the Loader Supports
------------------------

The loader imports static meshes with their materials and textures:

- **PBR metallic-roughness** materials: base colour, metallic and roughness
  factors and textures.

- **Texture maps**: base colour, metallic-roughness, normal (with scale),
  occlusion (with strength) and emissive.

- **Alpha**: opaque, mask (with cutoff) and blend modes.

- **Cameras**: each perspective camera in the file becomes a viewpoint you can
  cycle to with PageUp / PageDown.

- **Lights**: ``KHR_lights_punctual`` directional, point and spot lights.

- **Animation**: keyframed node transforms, skinning and morph targets, plus
  ``KHR_animation_pointer`` for animating material and texture-transform
  properties, and ``KHR_node_visibility``.

- **Instancing**: ``EXT_mesh_gpu_instancing``, and repeated meshes are batched
  into one instanced draw whether or not the file says so — see :doc:`Instanced
  rendering <instancing>`.

- **Levels of detail**: ``MSFT_lod``, with ``MSFT_screencoverage`` — a node's
  coarser alternatives and how much of the window each is worth drawing at. See
  :ref:`Levels of detail <lod>` below.

- **Material extensions**: ``KHR_materials_clearcoat``, ``KHR_materials_sheen``,
  ``KHR_materials_transmission``, ``KHR_materials_volume``,
  ``KHR_materials_ior``, ``KHR_materials_specular``,
  ``KHR_materials_emissive_strength``, ``KHR_materials_unlit``,
  ``KHR_materials_iridescence``, ``KHR_materials_anisotropy``,
  ``KHR_materials_diffuse_transmission``, ``KHR_materials_dispersion``,
  ``KHR_texture_transform``, ``EXT_texture_webp``, and the legacy
  ``KHR_materials_pbrSpecularGlossiness`` (converted to metallic-roughness).

- **Baked light**: ``OGLC_materials_baked_light``, this project's own, says a
  mesh's ``COLOR_0`` is light worked out when the world was built rather than a
  tint on the surface. Its colour channels are added as emission and leave the
  material's own colour alone; its fourth channel is how much of the environment
  reaches the surface, read as occlusion rather than as transparency. What it is
  for is a surface whose lighting cannot be afforded at runtime — the lining of
  a tunnel with a lamp every twenty-five metres, see :doc:`Roads <roads>` —
  where a scene light still shades the surface on top of what was baked, so a
  headlight paints its own circle across it. Written by the writer and read back
  by the loader; a file carrying it renders correctly in a viewer that ignores
  it, as a surface tinted by its vertex colours.

- **Geometry compression**: ``KHR_draco_mesh_compression`` when the optional
  ``DracoPy`` package is installed (``pip install DracoPy``, or
  ``OpenGLContext[draco]``). Without it, a Draco-compressed primitive is skipped
  with a warning and the rest of the scene still loads.

glTF nodes become ``Transform`` nodes, meshes become ``Shape`` nodes with a
PBR mesh geometry and a PBR material, so a loaded model is a normal
OpenGLContext scenegraph you can inspect and modify.

.. _lod:

Levels of detail
~~~~~~~~~~~~~~~~

:doc:`Levels of detail <lod>` is the whole subject — how a level is chosen,
how copies at one level collapse into a single draw, authoring a chain in
Blender, and the bust-gallery demo to walk through. This is how a glTF says
it.

A model may ship several times over at decreasing detail, so a copy far from
the camera costs the triangles it is worth rather than the triangles it has.
``MSFT_lod`` is how a glTF says so: the node carrying the extension is the
finest level, its ``ids`` name the coarser ones in decreasing detail, and
``MSFT_screencoverage`` in the node's ``extras`` gives the share of the window
at which each takes over.

.. code-block:: python

   "nodes": [
       {"mesh": 0,
        "extensions": {"MSFT_lod": {"ids": [1, 2]}},
        "extras": {"MSFT_screencoverage": [0.5, 0.2, 0.01]}},
       {"mesh": 1},
       {"mesh": 2}
   ]

The loader builds one `ScreenCoverageLOD
<https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/lod.py>`__
holding a level per alternative, and the render pass chooses between them once
a frame. Reading the example: the finest level is drawn while the model covers
half the window's height or more, the next from there down to a fifth, the
coarsest from a fifth down to one per cent, and below that nothing is drawn. A
file whose coarsest level should stay on screen however small it gets ends the
list with ``0``.

**Coverage, not distance.** A level is judged by how many pixels of it the
viewer is actually looking at, so the same model holds its detail twice as far
out when it is twice the size, and further again through a narrower field of
view. The size it is measured by comes from the finest level's ``POSITION``
accessor bounds, which glTF requires a file to declare, so a level can be
sized and placed without its geometry being read. A transform above the node
counts: a model scaled up switches later.

**What else the node carries stays put.** The extension offers alternatives
for the node's own geometry; the node's children, its light and its emitters
belong to the node and are drawn at every level.

**Copies batch per level.** The levels of a chain are decoded once and shared
between every node that names them, and the pass groups a frame's draws by the
geometry and appearance they share — so two copies of a model drawing the same
level are one instanced draw, and copies at different levels are drawn
separately, which is what drawing different geometry means. See
:doc:`Instanced rendering <instancing>`.

Coverage is a hint, in the extension's own words, and a file may leave it out.
The levels are then switched on a halving series — a half, a quarter, an
eighth — ending at zero, so a threshold the *reader* guessed is never the
reason something disappears.

Making a chain is a bake, not something a game does, so it lives in
`OpenGLContext-editor <https://github.com/mcfletch/openglcontext-editor>`__:
``OpenGLContext_editor.meshlod`` decimates a mesh into levels, measures what
each one costs to look at, and writes them in this shape — the coarsest level
inside the glb and each finer one a sidecar the operating system never opens
until it is wanted. The engine reads them. ``MSFT_lod`` on a *material*, which
the extension also allows, is not read.

.. _hooks:

Engine hooks: what a material or an object *is*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A glTF carries geometry and PBR factors and nothing that says a surface is
*water*. The format has no ratified way to ask for a shader, and the one that
had it — ``KHR_techniques_webgl`` — is archived. ``OGLC_hook`` is this
project's own answer: a tag naming a **kind**, which the application looks up in
a registry and makes something of as the file loads.

Two different facts want tagging, and the tag goes on whichever carries the one
you mean. On a **material** it says *this surface is made of that substance*; on
a **node** it says *this object is a thing of that kind*. One payload, three
spellings:

.. code-block:: javascript

   // extensions -- what a tool writes
   {"OGLC_hook": {"kind": "water", "style": "choppy", "depth": 6.0}}

   // extras -- what a Blender custom property becomes
   {"OGLC_hook": {"kind": "water", "style": "choppy"}}

   // extras, shorthand: a bare string is the kind, with no parameters
   {"OGLC_hook": "water"}

The extension wins where both are present, because a file carrying one was
written by a tool that knew what it meant. A ``kind`` nothing is registered for
loads as an ordinary shape, so a file authored for another engine still loads
here.

Authoring one in Blender
^^^^^^^^^^^^^^^^^^^^^^^^

Two ways, and the loader reads both. **With no add-on:** give the material (or
the object) a custom property called ``OGLC_hook`` in the Properties editor,
holding the string ``water`` or a JSON object, and export with **Include ‣
Custom Properties** ticked. Blender writes material custom properties to
``material.extras`` and object custom properties to ``node.extras``, which is
exactly what the loader reads. Blender 4.x is enough.

**With the add-on** in ``tools/blender/oglc_hook``: an **Engine Hook** panel on
the material and object tabs, with fields for the ``water`` kind and a JSON
object for any other, writing the ``OGLC_hook`` *extension* as each material and
node is exported. It is a form rather than a typed-out string, it says under the
fields exactly what the file will carry, and no export option has to be ticked
for it. Zip the folder, install it with **Edit ‣ Preferences ‣ Add-ons ‣ Install
from Disk**, and tick it; ``tools/blender/README.md`` has the rest.

Registering a kind of your own
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from OpenGLContext.loaders.gltf import hooks

   @hooks.register( 'twigbb:teleporter', shareable=False )
   def teleporter( ctx ):
       if ctx.at == 'node':
           return (Portal( target=ctx.params['target'], children=ctx.children ), True)
       return None

The factory is called at both hook points — once per primitive of a tagged
material, once per tagged node — and ``ctx.at`` says which. At the material
point it is handed the finished ``PBRMesh``, ``PBRMaterial`` and ``Shape``, the
primitive's local ``bounds`` (writable, so a hook that changes the extent
changes the framing) and the world matrix this copy stands at; it returns
``None`` to keep the loader's ``Shape``, or a node to put in its place. At the
node point it is handed the ``Transform``, the children gathered under it and
the local and world matrices, and returns one of three things:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Return
     - What the loader does
   * - ``None``
     - Keeps its own ``Transform`` and children. The hook augmented and nothing
       else changed.
   * - ``(node, False)``
     - Puts the node inside the glTF node's ``Transform``, in place of the
       children the loader gathered. The node's TRS still places it, and the
       hook may return any node type — a ``Switch``, an ``LOD``, a node the game
       defined.
   * - ``(node, True)``
     - Puts the node in the glTF node's own slot in the parent. The
       ``Transform`` is gone and the hook owns the placement;
       ``ctx.local_matrix`` is the transform it has taken on.

The flag is on the return rather than on the registration, because whether a
hook replaces a node is a property of what it made of *this* node. Either way
the node's DEF moves to whatever ends up in the slot, so ``getDEF`` finds the
same name it would have found.

``shareable=False`` says the hook's result carries per-node state — a box round
where this copy stands, a trigger's fired flag — so two nodes referencing one
mesh each get their own, exactly as a morphed or skinned mesh already does. The
default shares one result, as the loader always has.

What a hook records with ``ctx.collect()`` arrives on the scene as
``scene.hook_data[ kind ]``. A kind registered with an ``advance`` callable is
walked by ``scene.advance( seconds )``, which answers whether anything changed;
the viewer calls it from its idle, and a game driving its own loop calls it
itself.

What a file may ask for
^^^^^^^^^^^^^^^^^^^^^^^

**A file names a kind; it never names code.** The registry is populated by the
application, so a downloaded model can only select among what the running
program already registered — plus the kinds the engine itself ships, which are a
fixed table in ``OpenGLContext.loaders.gltf.hooks``. There is no entry-point
scan: an installed package cannot add a kind to somebody else's viewer by being
present. Setting ``OPENGLCONTEXT_GLTF_HOOKS=0`` leaves every tag in every file
unread.

The engine claims the bare lowercase names it documents and ships — ``water`` is
the only one — so an application naming its own keeps them out of that
namespace: ``glisteel:rail``, ``twigbb:teleporter``. A convention, read by
nothing, so that a kind a game invents today does not collide with one the
engine ships later.

The :doc:`writer <baking>` writes both spellings back: a material's or a
``SceneNode``'s ``extras`` pass through uninterpreted, and its ``hook`` becomes
an ``OGLC_hook`` extension block, so a world can be loaded, edited and baked
again with its tags intact.

The ``water`` kind ships registered, so a tagged file works in ``oglc-view``
with no application code at all. :ref:`Authoring water in a model <authoring>`
has its parameters and what lands on the scene.

.. _castsshadow:

A node that is not a shadow caster
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``OGLC_castsShadow`` in a node's ``extras``, set to ``0``, keeps that node's
geometry out of the shadow maps. It is still drawn and still lit, and it still
takes the shadows of everything else; what it does not do is put a shadow of
its own into the scene. The same flag on a node carrying a light gives that
light no shadow map.

.. code-block:: json

   "nodes": [
       {"mesh": 0, "name": "Ceiling", "extras": {"OGLC_castsShadow": 0}},
       {"mesh": 1, "name": "Plinth"}
   ]

What it is for is a room lit from outside itself. A hall standing under a sun
has a roof between the two, so a roof that casts shadows the whole interior and
the room renders as though the sun were not there. Marking the shell — floor,
walls, ceiling — lets the light into the room, and the busts on their plinths
still throw the shadows that give the hall its depth. The other use is a light
that stands in for light a renderer does not compute: a weak upward fill
standing in for what the floor throws back arrives from everywhere and shadows
nothing.

The flag says what one node does and does not reach that node's children, which
is how the tools that author it treat shadow visibility. It does carry to a
node's ``MSFT_lod`` alternatives, since those are the same object drawn instead
— a shadow that appeared as a viewer walked closer would be the level switch
made visible. It is ``extras`` rather than an extension, so a reader that has
never heard of it draws the node exactly as it would anyway. In Blender it is
an object custom property of that name, written by `OpenGLContext-editor
<https://github.com/mcfletch/openglcontext-editor>`__'s add-on; in the
scenegraph it arrives as :ref:`Shape.castsShadow <optout>`.

.. _omi:

OMI Extensions
~~~~~~~~~~~~~~

The `Open Metaverse Interoperability group
<https://github.com/omigroup/gltf-extensions>`__ publishes the extensions that
describe a *world* rather than a model — sound, physics, sky, and the things a
player sits in or drives. Support is split across three projects: the loader
here, :doc:`omi_audio <audio>` and :doc:`omi_physics <physics>`, both of which
take the extension as their native data model rather than converting into one
of their own.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Extension
     - Status
     - Where
   * - ``KHR_audio_emitter``
     - Full — audio, sources and emitters; node and scene references; ``bufferView``,
       ``data:`` and ``uri`` audio; autoplay
     - ``omi_audio``, :doc:`docs <audio>`
   * - ``OMI_audio_ogg_vorbis``
     - Full — the Ogg entry is preferred over the MP3 fallback and decoded
     - :ref:`Codec extensions <codecs>`
   * - ``OMI_audio_opus``
     - Read, preserved and reported; **not decoded**, so the MP3 fallback plays
     - :ref:`Codec extensions <codecs>`
   * - ``OMI_physics_shape``
     - Full, read and written
     - ``omi_physics``, :doc:`docs <physics>`
   * - ``OMI_physics_body``
     - Full, read and written
     - ``omi_physics``
   * - ``OMI_physics_gravity``
     - Full, read and written — global and per-node gravity volumes
     - ``omi_physics``
   * - ``OMI_physics_joint``
     - Full, read and written
     - ``omi_physics``
   * - ``OMI_environment_sky``
     - Gradient, panorama (equirectangular and cubemap) and plain skies are drawn;
       the **physical** (atmospheric-scattering) type is read and reported but not
       yet rendered
     - :ref:`The scene's sky <sky>`
   * - ``OMI_seat``
     - Future work
     - —
   * - ``OMI_spawn_point``
     - Future work
     - —
   * - ``OMI_vehicle_body``, ``OMI_vehicle_wheel``, ``OMI_vehicle_thruster``,
       ``OMI_vehicle_hover_thruster``
     - Future work
     - —

.. _sky:

The scene's sky
~~~~~~~~~~~~~~~

``OMI_environment_sky`` does not ship a sky; it *describes* one, and three of
its four descriptions are of a background OpenGLContext already draws. The
loader reads the document's ``skies[]``, resolves the index the active scene
names, and puts the matching node in the scene, where the ordinary Background
pass finds and binds it:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Sky type
     - What it becomes
   * - ``gradient``
     - ``Background`` — the VRML97 gradient sphere. The three colours and their
       curves are baked into colour stops.
   * - ``panorama``, equirectangular
     - ``HDRBackground``, which also registers the panorama as the :doc:`IBL <pbr>`
       environment, so metals reflect the sky drawn behind them.
   * - ``panorama``, cubemap
     - ``CubeBackground``, six faces in the extension's ``+X, -X, +Y, -Y, +Z, -Z``
       order.
   * - ``plain``
     - ``SimpleBackground``.
   * - ``physical``
     - Nothing yet — the one type that is a *renderer* rather than a translation.

A scene that brought its own sky this way keeps it: the viewer adds a backdrop
only when a document has none, so ``--background`` is still how you override
one. ``GLTFScene.sky`` is the record the scene selected, whether or not
anything could draw it, so a caller can say *why* a sky is missing.

Two parts of the extension are read and kept but not yet applied. The gradient
sky's **sun tint** (``sunAngleMax``, ``sunCurve``) is a disc around the
scene's directional light and so varies with compass direction, which the
gradient sphere's elevation-only colour stops cannot express. The **ambient
contribution** (``ambientLightColor``, ``ambientSkyContribution``) is not yet
wired to the ambient term. The **physical** sky needs a genuinely new shader:
an analytic Rayleigh/Mie scattering skydome driven by the scene's directional
sun, in glTF's inverse-metre units.

.. rst-class:: technical

The extension projects an equirectangular panorama with the middle of the
texture at ``+Z`` and ``+X`` to its left, while the skybox shader puts the
middle at ``+X``. The two differ by exactly a quarter of the width, so the
loader rolls the columns once, at load — which keeps the single shared
direction-to-UV mapping that stops the drawn sky and the reflections it drives
from disagreeing.

Current Limitations
~~~~~~~~~~~~~~~~~~~

- ``KHR_texture_basisu`` (KTX2 / Basis Universal) is deliberately not read:
  there is no transcoder available under a licence this project can take, and a
  texture in that format is skipped rather than guessed at.

- ``KHR_draco_mesh_compression`` needs the optional ``DracoPy`` package; without
  it a Draco-compressed primitive is skipped with a warning and the rest of the
  scene still loads.

- Two of the harder material effects are approximations rather than the
  reference result: volumetric subsurface scattering, and transmission through
  nested transparent shells.

.. rst-class:: technical

The loader fetches remote resources with same-origin checks and blocks
link-local / metadata addresses, and caps download sizes, so pointing it at a
URL is reasonably safe.

Loading From Python
-------------------

The loader returns a small scene object carrying the scenegraph group, its
bounds and any cameras:

.. code-block:: python

   from OpenGLContext.loaders import gltf

   scene = gltf.load_gltf( "model.glb" )   # or gltf.load_gltf_url( url )
   group   = scene.group      # a scenegraph Group you can add to your own scene
   centre  = scene.center     # bounding-sphere centre, for framing
   radius  = scene.radius     # bounding-sphere radius
   low     = scene.minimum    # the corners of the box that sphere surrounds
   high    = scene.maximum
   strays  = scene.strays     # parts the file stranded outside that sphere
   cameras = scene.cameras    # list of baked camera poses

You can drop ``scene.group`` straight into a context's scenegraph, or use
``scene.center`` / ``scene.radius`` to frame the model, as the viewer does.
An orthographic view fits the box, ``scene.minimum`` / ``scene.maximum``, more
closely than it fits the sphere; :doc:`multiview` frames all four views of an
editor that way.

That sphere is fitted to the *model*, not to the file's whole extent: a part
the exporter stranded far outside the rest is left out of it, so that one
forgotten duplicate cannot push the camera hundreds of model-widths back.
``scene.strays`` counts them and ``scene.stray_reach`` says how far the
farthest goes in radii of the fitted sphere; both are 0 when the model is all
in one place. The strays are still in ``scene.group`` and still drawn — this
decides where to stand, not what to render. The rule, and the three constants
that set it, are in
``OpenGLContext.loaders.gltf.transforms.framing_bounds()``; the viewer's
:ref:`Framing a model <framing>` covers it in full.

.. _instances:

One model, many instances
~~~~~~~~~~~~~~~~~~~~~~~~~

Drawing one asset many times — a cast of the same character, a forest of one
tree — parse it once and build a scene per instance from that parse:

.. code-block:: python

   from OpenGLContext.loaders import gltf

   document = gltf.parse_gltf( "character.glb" )   # read + decode the file once
   figures  = [ gltf.load_gltf( document=document ) for _ in range( 20 ) ]

Each ``load_gltf(document=…)`` is its own independent scenegraph with its own
materials and its own deformable-mesh state, so the instances animate and
recolour independently. What they share is only what none of them changes: the
JSON parse is done once, and the immutable vertex and animation-keyframe
arrays are decoded on the first build and referenced — not copied — by every
later one. A skinned mesh deforms on its own copy, so sharing never couples
two bodies' poses. A lone ``load_gltf( "model.glb" )`` is unchanged: it
decodes its own arrays and needs no document.

.. _names:

Driving a model by name
~~~~~~~~~~~~~~~~~~~~~~~

A model an application drives — repaint this car, pose that dial, hide the
shell for the view from inside it — is addressed by the names it was authored
under, so re-exporting the art is not a change to the code. Three registries
carry them:

.. code-block:: python

   scene = gltf.load_gltf( "car.glb" )

   interior = scene.getDEF( "interior" )                     # one node, by its glTF name
   scene.materials[ "paint" ].baseColor = (0.1, 0.3, 0.6)    # one material, by its
   player = scene.player_named( "steer", loop=False )        # one animation clip, by its

``scene.materials`` maps the name a document gave a material to the
``PBRMaterial`` built for it, for the materials the scene's geometry uses. The
``Shape``, its mesh and this mapping all hold the one material object, so
repainting what it hands back repaints the model. glTF names need not be
unique: a repeated name maps to the first material in the document carrying
it, and a material the document left unnamed is drawn and not indexed. The
:ref:`writer <writing>` writes a material's ``DEF`` as its glTF name, so a
name survives a round trip.

``player_named()`` is ``player()`` asked by name instead of by index, and
returns ``None`` where no clip carries the name. ``loop=False`` clamps the
clip at its ends, which is what *posing* one wants rather than playing it — a
steering wheel turned a fraction of its travel, a lever part-way through its
throw:

.. code-block:: python

   player = scene.player_named( "steer", loop=False )
   player.evaluate( fraction * player.duration )   # 0.0 the first key, 1.0 the last

Carrying the travel in a clip rather than as an angle in code leaves the
limits of the movement with the artist: the keyframes say how far the wheel
turns, and the caller says only how far through that it is.

.. _assets:

The Models a Package Ships
--------------------------

An application's art is a table of names — this vehicle is that ``.glb``, that
pickup is this one — and everything else about loading one is the same every
time. ``OpenGLContext.loaders.assets.AssetLibrary`` is a directory of models
addressed by relative name, so the table is a table of filenames and never a
path built at each call site:

.. code-block:: python

   from OpenGLContext.loaders.assets import AssetLibrary

   ART = AssetLibrary( os.path.join( os.path.dirname( __file__ ), 'assets' ) )

   scene = ART.shared( 'cars/saloon.glb' )      # one copy, shared by every caller
   if scene is not None:
       world.children.append( scene.group )

   mine = ART.load( 'cars/saloon.glb' )         # my own copy, to change
   mine.materials[ 'paint' ].baseColor = (0.6, 0.1, 0.1)

**Ask for a shared copy to draw, and a load to change.** ``shared()`` reads
the file once and hands the same subtree to every caller, which is what a
scenegraph's ``USE`` has always meant: the same model mounted in as many
places as it is wanted. ``load()`` reads the file again and hands back a scene
nobody else holds, for a caller that will repaint or pose what it gets.

**A crowd in a handful of colours wants neither.** A road full of traffic, a
team in strip, a rank of soldiers: ``shared()`` cannot be repainted without
repainting all of it, and ``load()`` costs a file read and a parse *per member
of the crowd*, on the frame that member appears. ``variant()`` is one copy per
version — prepared once, then shared by everything asking for that version,
which is also what lets the renderer draw the crowd as one batch:

.. code-block:: python

   from OpenGLContext.loaders.assets import recolour

   scene = ART.variant( 'cars/saloon.glb', paint,
                        prepare=lambda one: recolour( one.group, paint ) )

The key names the version — the colour, the team, the season — and ``prepare``
is called once, the first time that key is asked for. Since the scene is then
shared, a caller that changes it afterwards changes it for every other holder,
which is the same contract ``shared()`` has.

**A model that will not load is not an error.** Both calls return ``None`` for
a file that is missing or will not parse, and log a warning with its
traceback; ``shared()`` remembers the absence, so a missing file is read for
once rather than once a frame. What that leaves is a hand empty or a car
undrawn, and a caller with a fallback can use it — a level that fails to start
over one corrupt file has failed worse than one with an invisible car in it.

``recolour( node, colour )`` paints every material in a subtree one colour and
``brighten( node, glow )`` lights each one in its own, for art that differs
only in colour: a family of pickups is then one model painted
several ways rather than one file each. Both change what they are given, so
they belong to a subtree from ``load()``. A model with several materials that
must stay apart — paint, glass, bright trim — is repainted through
``scene.materials`` instead, which touches the one material named and leaves
the glass glass.

``bounds( node )`` is the box a subtree occupies, as ``(minimum, maximum)`` in
the space its own root sits in, with every ``Transform`` on the way down
applied and no GL context needed — for cutting a collider from a model, or
checking one is the size it was meant to be. Geometry that carries its shape
as numbers rather than as a vertex array (a VRML ``Cone``, a ``Sphere``) is
measured by the box it declares, so a subtree of primitives measures like one
of meshes.

``seated( node, sink=0 )`` is that measurement put to its commonest use.
Placing a model puts *its origin* where the caller asked, which reads as "on
the ground" only for art authored with its feet there — and a VRML primitive
is centred on its origin, while an exported model sits wherever its author
left it. ``seated`` wraps a subtree so that its underside is at the wrapper's
origin, which makes that origin the point the thing stands on; ``sink``
settles it that far back into the ground, for a root flare or a boulder base
that should meet the ground rather than perch on it. The wrapper is a new node
and the original is untouched, so one model seats into as many placements as a
caller likes. Scattered vegetation goes through it — see :ref:`Where a plant
meets the ground <footing>`.

.. _gltf-embedding:

Embedding the Viewer
--------------------

Everything the viewer does — loading without freezing the window, the default
light rig, auto-framing, the model's own cameras and animations, the caption,
screenshots, the library, walking — is the reusable ``OpenGLContext.viewer``
package, not the script. An application gets all of it by subclassing
``ViewerContext`` and saying what it wants with a ``ViewerOptions``. There is
no command line involved (:ref:`the full account is here <viewer-embedding>`):

.. code-block:: python

   from OpenGLContext.viewer import ViewerContext, ViewerOptions

   class MyViewer( ViewerContext ):
       options = ViewerOptions(
           source = 'model.glb',       # a path or an http(s) URL
           physics = True,             # walk it, rather than fly around it
           background = 'sky',
       )

   MyViewer.ContextMainLoop()

``ViewerOptions`` is a dataclass holding every knob the viewer has, and it is
the *same* object the command line fills in — ``argparse`` populates one as
its namespace — so the defaults are written once and a flag can never mean
something different from the field. The fields are grouped as: the source; the
cameras (``camera``, ``no_cameras``); auto-framing (``yaw``, ``margin``,
``elevation``, ``tilt``, ``eye``, ``look_at``); lighting and environment
(``lights``, ``shadows``, ``ibl_intensity``, ``environment``, ``background``);
animation (``animate``, ``animation``, ``anim_time``, ``turntable``,
``no_rotate``); ``physics``; and the window and frame (``size``, ``capture``,
``capture_delay``, ``frames``).

The seams worth overriding
~~~~~~~~~~~~~~~~~~~~~~~~~~

A viewer that shows something other than one file overrides these. This is how
``oglc-gltf-demo`` browses a whole downloaded catalogue while sharing every
other behaviour:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it decides
   * - ``prepareSource()``
     - Where the model comes from. A browser with no single source overrides this to
       do nothing.
   * - ``loadScene()``
     - Produce the scene. **Runs on a worker thread, so it must not touch GL** — that
       is what keeps the window drawing through a download.
   * - ``requestInitialScene()``
     - What to load first.
   * - ``buildScenegraph( scene )``
     - Turn a loaded scene into ``self.sg``. Called again for each new model, which
       is what makes swapping models possible.
   * - ``onSceneReady()``
     - Just after a scene is built, on the render thread.
   * - ``drawExtraOverlay( shader )``
     - Draw over the finished frame.
   * - ``buildPhysicsWorld()``
     - Where the collision world comes from, if not cooked from ``self.sg`` — see
       :ref:`walking <walking>`.

The parts, separately
~~~~~~~~~~~~~~~~~~~~~

The package is assembled from pieces that are useful on their own, so a
context that is not a glTF viewer can still take the one it needs:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - What it gives you
   * - ``viewer.options``
     - ``ViewerOptions``: the configuration, shared with the CLI.
   * - ``viewer.asyncscene``
     - ``AsyncSceneMixin``: load a scene off the render thread and apply it on it.
       Format-neutral — it does not know what a scene is.
   * - ``viewer.framing``
     - ``fit_sphere()`` and ``look_from()``: where to put a camera to see a thing.
       Pure arithmetic, no GL.
   * - ``viewer.environment``
     - The gradient sky, and the skybox matching whatever the IBL probe loaded, so
       the visible backdrop and the reflections agree.
   * - ``viewer.caption``
     - ``CaptionMixin`` and ``CaptionLayer``: what the viewer says over the frame — a
       :doc:`HUD <hud>` layer like any other, so it takes the skin and the interface
       scale for free.
   * - ``viewer.debug``
     - The viewer's own section on the developer overlay (``Alt+F``): which adapter
       read the source, how big it turned out, which camera is bound. One overlay,
       not a second one.
   * - ``viewer.capture``
     - ``SettleCaptureMixin``: render one settled frame to a file and quit, which is
       what ``--capture`` is.

.. rst-class:: technical

Walking is deliberately *not* in this package: it is a capability of every
interactive context. See :ref:`Walking any scene <walking>`.

A Worked Example: the Parthenon
-------------------------------

The sibling `Parthenon project <https://github.com/mcfletch/openglcontext>`__
builds a metre-scale glTF model of the temple and bakes a set of cameras into
it -- a walking tour from the eastern approach, up the steps, through the
pronaos door and into the naos. Loading it in ``oglc-view`` and pressing
PageDown steps through these cameras. The shots below are one per baked
camera.

.. figure:: images/parthenon/1-east-approach.jpg
   :alt: east approach

   1 — east approach

.. figure:: images/parthenon/2-steps-foot.jpg
   :alt: foot of the steps

   2 — foot of the steps

.. figure:: images/parthenon/3-steps-top.jpg
   :alt: top of the steps

   3 — top of the steps

.. figure:: images/parthenon/4-pronaos-door.jpg
   :alt: pronaos door

   4 — pronaos door

.. figure:: images/parthenon/5-naos-entering.jpg
   :alt: entering the naos

   5 — entering the naos

.. figure:: images/parthenon/6-naos-look-out.jpg
   :alt: naos looking out

   6 — naos, looking out

.. figure:: images/parthenon/7-west-chamber.jpg
   :alt: west chamber

   7 — west chamber

.. figure:: images/parthenon/8-north-flank.jpg
   :alt: north flank

   8 — north flank

.. figure:: images/parthenon/9-ne-corner.jpg
   :alt: north-east corner

   9 — north-east corner

.. figure:: images/parthenon/10-aerial.jpg
   :alt: aerial

   10 — aerial

Regenerating These Images
-------------------------

The images on this page are produced by a script in the source tree so they
can be refreshed whenever the renderer changes:

.. code-block:: bash

   python scripts/generate_doc_images.py             # gallery + Parthenon
   python scripts/generate_doc_images.py --gltf-only

It downloads the sample models on demand, renders one shot of each with the
PBR pass, and writes the results into ``docs/images/``. It renders each model
in its own process, so it needs a display or an offscreen GL platform (for
example ``PYOPENGL_PLATFORM=egl``).
