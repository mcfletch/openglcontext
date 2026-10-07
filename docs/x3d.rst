Loading X3D
===========

.. rst-class:: introduction

OpenGLContext loads X3D documents into its scenegraph and draws them with the
:doc:`PBR renderer <pbr>`. `X3D <https://www.web3d.org/standards>`__ is
VRML97's successor, standardised by the Web3D Consortium as ISO/IEC 19775. The
reading and writing are pyvrml97's ``vrml.x3d``; the engine supplies the node
implementations that draw. To open an X3D file and look at it, use
:doc:`oglc-view <viewer>`.

.. figure:: images/demos/x3d_demo.jpg
   :alt: A gallery on a checkered marble floor before a brick wall: gold, copper and steel spheres on sandstone plinths, a bronze ball in a lit alcove, a sandstone mound and a small gold vase

   ``oglc-x3d``: an X3D 4 document read by the engine.

The showcase
------------

``oglc-x3d`` opens ``OpenGLContext/bin/x3d_gallery.x3d``, an X3D 4 document,
and :doc:`tests/x3d_demo.py <tutorials/x3d_demo>` is the same scene as a
tutorial. The document's floor and back wall are an ``IndexedTriangleSet``
and an ``IndexedTriangleStripSet`` wearing ``PhysicalMaterial`` marble and
brick; three ``PhysicalMaterial`` metals stand on sandstone plinths drawn
with an X3D 4 ``Material`` and its ``diffuseTexture``; a ``TriangleFanSet``
with ``ColorRGBA`` colours and a ``LineSet`` make the medallion on the wall;
an ``ElevationGrid`` is the mound; and a glTF vase is ``Inline``\ d. The sun
casts shadows, and the alcove's lamp lights only the alcove. The textures and
the vase are written beside a copy of the document when the command starts,
in the user cache directory or ``--directory``.

Its keys: ``l`` turns the alcove lamp off and on, ``m`` hides and shows the
medallion through its ``visible`` field, and ``w`` writes the scene back as
X3D in each encoding beside the document.

Loading
-------

.. code-block:: python

   from OpenGLContext.loaders.loader import Loader

   scene = Loader.load( 'world.x3d' )
   self.sg = scene

``Loader.load`` and ``Loader.loads``, the :ref:`scene loader <scene-loader>`
and ``oglc-view`` all open these:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Encoding
     - Suffixes and content types
   * - XML
     - ``.x3d``, ``.x3dz`` (gzip), ``model/x3d+xml``
   * - ClassicVRML
     - ``.x3dv``, ``.x3dvz`` (gzip), ``model/x3d+vrml``, ``model/x3d-vrml``
   * - JSON
     - ``.x3dj``, and ``.json`` whose top-level key is ``"X3D"``
   * - Compressed binary (Fast Infoset)
     - ``.x3db``, ``.x3db.gz`` (gzip), ``model/x3d+fastinfoset``,
       ``model/x3d+binary``

A compressed binary document is read with the X3D vocabulary Web3D's own
``.x3db`` files are written with. A value given in an X3D encoder other than
delta-zlib integers is reported and left unset; pyvrml97's ``docs/x3d.rst``
gives the limits.

The result is an ``X3DScene``: a ``sceneGraph`` that also holds the
document's ``profile``, ``version``, ``components``, ``units``, ``meta`` and
the ``problems`` reading it found. Each problem is also logged at its
severity. A document with errors in it loads as far as it reads.

Versions
~~~~~~~~

Documents of X3D 3.0 to 4.1 are read, and VRML97 through the same reader. The
scenegraph holds one vocabulary, X3D 4.1's: a field an earlier version names
differently is read under its X3D 4 name, and a field an earlier version gives
another default has that default. ``UNIT`` statements scale the values they
name into metres, radians, kilograms and newtons as the document is read.

What is drawn
-------------

A node the engine implements is built from the engine's class for it; any
other is built from its X3D declaration, keeps its fields, and is not drawn,
and its type is listed once among the scene's ``problems`` at ``info``
severity. ``OpenGLContext.loaders.x3d.prototypes()`` is the map. The engine
implements these X3D nodes, by component:

.. x3d-implemented-start

- CADGeometry - CADAssembly, CADLayer, CADPart
- Core - MetadataBoolean, MetadataDouble, MetadataFloat, MetadataInteger,
  MetadataSet, MetadataString, WorldInfo
- EnvironmentalEffects - Background, Fog, LocalFog, TextureBackground
- EventUtilities - BooleanFilter, BooleanSequencer, BooleanToggle,
  BooleanTrigger, IntegerSequencer, IntegerTrigger, TimeTrigger
- EnvironmentalSensor - ProximitySensor, TransformSensor, VisibilitySensor
- Geometry2D - Arc2D, ArcClose2D, Circle2D, Disk2D, Polyline2D, Polypoint2D,
  Rectangle2D, TriangleSet2D
- Geometry3D - Box, Cone, Cylinder, ElevationGrid, Extrusion, IndexedFaceSet, Sphere
- Grouping - Group, Switch, Transform
- Followers - ColorChaser, ColorDamper, CoordinateChaser, CoordinateDamper,
  OrientationChaser, OrientationDamper, PositionChaser, PositionChaser2D,
  PositionDamper, PositionDamper2D, ScalarChaser, ScalarDamper,
  TexCoordChaser2D, TexCoordDamper2D
- KeyDeviceSensor - KeySensor, StringSensor
- Interpolation - ColorInterpolator, CoordinateInterpolator,
  CoordinateInterpolator2D, EaseInEaseOut, NormalInterpolator,
  OrientationInterpolator, PositionInterpolator, PositionInterpolator2D,
  ScalarInterpolator, SplinePositionInterpolator, SplinePositionInterpolator2D,
  SplineScalarInterpolator, SquadOrientationInterpolator
- Lighting - DirectionalLight, EnvironmentLight, PointLight, SpotLight
- Navigation - Billboard, Collision, LOD, NavigationInfo, OrthoViewpoint, Viewpoint,
  ViewpointGroup
- Networking - Anchor, Inline, LoadSensor
- Picking - PickableGroup
- PointingDeviceSensor - CylinderSensor, PlaneSensor, SphereSensor, TouchSensor
- Rendering - Color, ColorRGBA, Coordinate, IndexedLineSet,
  IndexedTriangleFanSet, IndexedTriangleSet, IndexedTriangleStripSet, LineSet,
  Normal, PointSet, Tangent, TriangleFanSet, TriangleSet, TriangleStripSet
- Shape - Appearance, Material, PhysicalMaterial, Shape, TwoSidedMaterial, UnlitMaterial
- Sound - AudioClip, Sound
- Text - FontStyle, Text
- Texturing - ImageTexture, MovieTexture, MultiTextureCoordinate,
  MultiTextureTransform, PixelTexture, TextureCoordinate, TextureProperties,
  TextureTransform
- Texturing3D - TextureTransformMatrix3D
- Time - TimeSensor

.. x3d-implemented-end

Geometry
~~~~~~~~

The triangle sets and ``ElevationGrid`` are drawn as the mesh their fields
build (``OpenGLContext.scenegraph.meshgeometry``): normals that are not given
are generated, smoothed across folds within ``creaseAngle`` for
``ElevationGrid`` and across every shared coordinate for the triangle sets
whose ``normalPerVertex`` is true; ``colorPerVertex`` and ``normalPerVertex``
false give one value per triangle (per quad for ``ElevationGrid``); ``ccw``
false turns the triangles round. In these and in ``IndexedFaceSet``, a
``Color`` or ``ColorRGBA`` replaces the ``Material``'s ``diffuseColor``, in
both renderers. A ``MultiTextureCoordinate``'s entries are
``TEXCOORD_0``, ``TEXCOORD_1`` and so on, and an entry's ``mapping`` label is
what a material's ``...TextureMapping`` names. The renderer reads two
coordinate sets. A ``LineSet`` is drawn as an ``IndexedLineSet``.

The Geometry2D nodes lie in the z=0 plane facing +z: ``Rectangle2D``,
``TriangleSet2D``, ``Disk2D`` and ``ArcClose2D`` as meshes with texture
coordinates across their bounds, ``Circle2D``, ``Arc2D`` and ``Polyline2D`` as
lines, and ``Polypoint2D`` as points. A curve has 48 segments to a whole turn
(``geometry2d.SEGMENTS``).

An ``IndexedFaceSet`` or a triangle set with no ``texCoord`` takes X3D's
default texture coordinates: s from 0 to 1 along the largest dimension of
its coordinates' bounding box, t along the second largest in the same units
(``composedgeometry.default_texcoords``).

A composed geometry's first texture coordinate set may come from a
``TextureCoordinateGenerator``: the PBR vertex shader makes it in the
generator's ``mode`` (``OpenGLContext.scenegraph.texgen``), from the
vertex's own or camera-space position or normal. A generator for a later
set is reported once and not drawn, and the fixed-function and VRML97
shader paths do not generate coordinates.

A grouping node or shape whose ``visible`` is false is not drawn, picked or
shadowed, nor is anything under it; setting it takes effect on the next frame.

Materials and appearance
~~~~~~~~~~~~~~~~~~~~~~~~

The :doc:`PBR renderer <pbr>` page describes ``PhysicalMaterial``,
``UnlitMaterial`` and ``Material`` with their texture fields and mapping
labels, ``Appearance.alphaMode`` and ``alphaCutoff``, and
``MultiTextureTransform``. A ``Material``'s ``diffuseTexture``,
``emissiveTexture``, ``normalTexture`` and ``occlusionTexture`` are its base
colour, emissive, normal and occlusion maps, and its ``normalScale`` and
``occlusionStrength`` are read; without a ``diffuseTexture``, the
appearance's ``texture`` is the base colour map. In the same way it is a
``PhysicalMaterial``'s base map without a ``baseTexture``, and an
``UnlitMaterial``'s emissive map without an ``emissiveTexture``, in drawing
and in a glTF written from the scene. ``ambientTexture``,
``shininessTexture`` and ``specularTexture`` are kept and not drawn.
A geometry that is not ``solid`` draws its back faces with
``Appearance.backMaterial``, or with a ``TwoSidedMaterial``'s ``back...``
fields where its ``separateBackColor`` is true, through the PBR program: the
shape is drawn a side at a time and is not batched with others. The alpha
mode is the front material's, and the fixed-function path draws both sides
with the front material.

Lighting
~~~~~~~~

A ``DirectionalLight`` whose ``global`` is false (X3D's default) lights only
the descendants of its parent grouping node; point and spot lights, global by
default, light everything. A light casts shadows where its ``shadows`` is
true, and ``shadowIntensity`` sets how dark they are; ``Shape.castShadow``
false leaves a shape out of the shadow maps. See :doc:`Shadows <shadows>`.
The engine's lights made in code are global and cast shadows by default.

An ``EnvironmentLight`` with ``diffuseCoefficients`` (glTF's
``irradianceCoefficients``: nine RGB spherical-harmonic coefficients,
multiplied by its ``color``) lights the scene as its image-based light, where
the scene has no glTF image-based light of its own, with its ``intensity``
and ``rotation`` (``OpenGLContext.scenegraph.environmentlight``). Its one
specular level is made from the same coefficients, so smooth surfaces
reflect a blurred environment; the cube-map textures, ``origin`` and
``global`` are not read. It needs full image-based lighting
(``ContextDefinition.ibl``).

A document is lit by its own lights and its headlight: the PBR pass's
built-in studio environment, which lights a scene built in code, is off for it,
and an environment it supplies is kept (``ibl.scene_mode``). A ``PointLight``
or ``SpotLight`` falls off by X3D's ``1 / max(attenuation[0] +
attenuation[1] d + attenuation[2] d², 1)``, so it never lights a surface
more than its intensity; a glTF light falls off inverse-square.

In a document, an ``Appearance`` with no ``material`` is unlit: the shape is
its texture's colour, or white; a ``Shape`` with no ``appearance`` is unlit
white. A scene built in code draws either in a lit neutral grey. A
``PhysicalMaterial`` is drawn by the PBR pass's metallic/roughness BRDF, as
glTF's materials are. A document's ``Material`` is drawn by X3D's Phong
equation in both renderers (:doc:`pbr`), each light adding its
``ambientIntensity``; a document has no other ambient light. The PBR pass
draws a ``Material`` in a scene built in code as an equivalent
metallic/roughness material. ``oglc-x3d-regression --renderer vrml97`` draws
the corpus with the VRML97 pass.

Which of these rules applies is the context definition's ``lighting`` field
(``OPENGLCONTEXT_LIGHTING``, ``OpenGLContext.lighting``): ``auto``, the
default, applies X3D's rules to a scene loaded from a document and the
engine's to one built in code; ``x3d`` and ``engine`` apply one set to every
scene.

A point or spot light's ``radius`` is how far it reaches in its own
coordinates: nothing past it is lit, in the shader paths. A light a document
builds has VRML97's and X3D's 100 unless the document sets another; one made
in code reaches everywhere unless given one; a glTF light's is its ``range``.
The fixed-function path has no such cut-off.

Fog and backgrounds
~~~~~~~~~~~~~~~~~~~

A ``Fog`` or ``LocalFog`` fades the colour as it is displayed, after tone
mapping, by X3D's equation: a ``LINEAR`` fog leaves an object
``(visibilityRange - distance) / visibilityRange`` of its own colour.

An enabled ``LocalFog`` fogs the siblings in its parent group and their
descendants in place of the bound ``Fog`` (``OpenGLContext.passes.localfog``);
where LocalFogs nest, the deepest group's fogs what is in it. An instanced
group of shapes takes the LocalFog of the first of them.

A ``Background``'s sky and ground colours are drawn on a sphere. One
``groundColor`` with no ``groundAngle`` is a ground of that colour from the
nadir to the horizon, as one ``skyColor`` with no ``skyAngle`` is a sky all
over. Each of its six images is drawn over them, turned as X3D turns it, once
that image has loaded; a side with no image, or a transparent part of one,
shows the sky and ground. A ``TextureBackground`` is drawn the same way from
its six ``...Texture`` sides. A side is an ``ImageTexture`` or a
``PixelTexture``; ``transparency`` is not read.

Collision
~~~~~~~~~

Walking (:doc:`physics`) collides with what X3D's ``Collision`` groups say:
a disabled group's children are walked through, a ``proxy`` collides in
place of the children, and each enabled group's geometry is a body of its
own in the walk's world (``gltf_world.collision_groups``). As the avatar
touches it the group sends ``isActive TRUE`` and ``collideTime``, as does
each enabled group around it, and ``isActive FALSE`` when the touch ends
(``OpenGLContext.physics.x3dcollision``).

Inline
~~~~~~

An ``Inline`` reads any format a registered reader opens: another X3D or
VRML97 world, an OBJ model or a glTF model. Its scene is read on the loader
pool and drawn from the frame after it arrives. See :ref:`x3d-worlds`.

Time
~~~~

The event utilities, sequencers, followers and interpolators are pyvrml97's
behaviours (``vrml.x3d.runtime``, ``vrml.x3d.followers``). In the engine:

- A scene's time is the engine's (``systemtime.systemTime``, which a capture
  steps a frame at a time): ``SceneGraph.clock`` is what pyvrml97's timed
  nodes read, and the engine's own timed classes read it in no scene too.
- A ``TimeTrigger`` sends the engine's time.
- A ``TimeSensor`` (``vrml.x3d.timesensor``) is polled by each context it is
  bound to on every pass of the event cascade, at the engine's time, and runs
  as X3D says from ``startTime`` to ``stopTime``, pausing at ``pauseTime``
  and resuming at ``resumeTime``. ``pause()`` and ``resume()`` set those two
  to the engine's time. ``rate`` sets how fast its cycles run against the engine's
  clock, and can be changed while it runs. ``getTimer(context)`` answers a Timer-style
  handle on it: ``pause()``, ``resume()``, ``internal.multiplier`` (the
  rate) and ``addEventHandler('fraction' or 'cycle', function)``.
- A ``LoadSensor`` is polled in the same way. ``Inline`` and ``ImageTexture``
  record their load state as they read (``vrml.x3d.loadsensor``); other url
  nodes record none and are not waited for.
- A follower moves a step each frame on the engine's clock while it is
  moving, queued on its window's render queue.

.. _x3d-binding:

Binding, viewpoints and navigation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- The background, fog and viewpoint the pass uses are the bound ones, on
  X3D's bind stacks (``vrml.x3d.binding``): of the nodes the scene draws, the
  topmost on its stack, and with none bound the first. ``set_bind``, sent by
  a route or set from Python, chooses another, and ``isBound`` and
  ``bindTime`` are sent as X3D says. The engine's own backgrounds
  (``SimpleBackground``, ``SphereBackground``, ``CubeBackground``,
  ``HDRBackground``) are bindable in the same way, and they and ``Fog`` also
  have a ``bound`` field: with none of a kind bound, the first drawn with
  ``bound`` set is used before the first drawn. The next-viewpoint key
  binds the viewpoint after the bound one
  (``viewpointbinding.next_viewpoint``).
- A viewpoint's ``fieldOfView`` spans the smaller of the window's width and
  height, so in a portrait window it is the horizontal angle
  (``ViewPlatform.setFrustum(..., across='smaller')``). A document that binds
  no viewpoint is seen through X3D's default one, ``fieldOfView`` 0.7854,
  from the context's starting position, which is X3D's default (0, 0, 10)
  unless the application sets another
  (``viewpointbinding.default_viewpoint``). A scene built in code keeps the
  engine's camera, 60 degrees vertically.
- A bound viewpoint's ``nearDistance`` and ``farDistance`` set the clip
  planes where positive. An ``OrthoViewpoint`` projects orthographically
  through its ``fieldOfView`` window (minimum x, minimum y, maximum x,
  maximum y), widened along one axis to the shape of the window it is drawn
  in (``ViewPlatform.setOrthographic``); a perspective viewpoint bound after
  it ends the orthographic projection.
- The bound ``NavigationInfo`` (``OpenGLContext.move.navigationinfo``):
  ``headlight`` true adds a headlight to the scene's lights and false leaves
  it off. A document with no NavigationInfo has X3D's default one: the
  headlight, and ``EXAMINE`` as its type. A scene built in code with none
  has the headlight only where it has no lights. When one is bound, or its
  ``type`` changes, the first of its ``type`` values the context's declared
  movement modes offer is selected: ``WALK`` is ``walk`` or ``fps``, ``FLY``
  is ``fly``, and ``EXAMINE``, ``LOOKAT`` and ``EXPLORE`` are ``examine``. A
  context with no declared modes keeps its own navigation. A positive
  ``visibilityLimit`` is the far clipping distance. ``speed`` scales the
  declared modes' speeds relative to X3D's default of 1 (2 doubles them),
  and ``avatarSize`` (radius, eye height, step height) sizes the walking
  avatar in the world's own units. These are applied again whenever they
  change.
- A viewpoint bound after the first is moved to as the bound NavigationInfo's
  ``transitionType`` and ``transitionTime`` say: ``LINEAR`` straight at a
  steady pace, ``ANIMATE`` easing in and out, ``TELEPORT`` at once; with no
  NavigationInfo, ``LINEAR`` over a second. ``transitionComplete`` is sent on
  arrival (``viewpointbinding.ViewpointTransition``).
- A viewpoint with ``viewAll`` places the camera, looking the viewpoint's
  way, where the whole scene's bounding sphere is in view. One with
  ``retainUserOffsets`` returns, when bound again, to where the user had
  moved to from it. Where the document sets the bound viewpoint's
  ``centerOfRotation``, the examine gestures turn about it when the pointer
  is on nothing.
- A ``ViewpointGroup``'s viewpoints are the scene's; the next-viewpoint key
  passes over those of a group that is not ``displayed``, or that has a
  ``size`` and the viewer is outside the box of that size about its
  ``center``.
- An ``Anchor`` draws its children as a group, and a click released over
  them calls ``Context.OnAnchor(anchor, url, parameter)``. The context binds
  the viewpoint a ``#name`` url names; opening any other url is left to an
  application that overrides ``OnAnchor``.

- A ``Billboard`` is turned toward the camera of a frame's first view once a
  frame, before the frame is drawn (``FlatPass.faceBillboards``): about its
  ``axisOfRotation``, or with ``0 0 0`` facing the camera with its +Y along the
  camera's up. Shadows are cast as it faces the camera.

Sensors
~~~~~~~

- The environmental sensors are told once a frame what they sense
  (``OpenGLContext.scenegraph.x3dsensors``): a ``ProximitySensor`` the
  active view's camera, a ``TransformSensor`` its ``targetObject`` where the
  scene draws it, and a ``VisibilitySensor`` whether its box is within any
  view's frustum.
- The pointing-device sensors (``TouchSensor``, ``PlaneSensor``,
  ``CylinderSensor``, ``SphereSensor``) are told of their context's picked
  pointer (``OpenGLContext.scenegraph.x3dpointing``). The sensors reached are
  the enabled ones beside the geometry under the pointer, in the lowest group
  on its path that has any; the primary button presses them, and a drag
  continues on or off their geometry until it is released. The scene's and
  the application's own handlers receive the same events. The hit is the picked point, with no
  normal or texture coordinate. Picking (``ContextDefinition.pickEnabled``)
  has to be on.
- A ``KeySensor`` hears every key its window receives, including keys a
  program has bound itself: ``keyPress`` for a character, ``actionKeyPress``
  for the function, arrow and page keys, and ``shiftKey``, ``controlKey`` and
  ``altKey`` while those are held.
- A ``StringSensor`` hears every character typed into its window.

``Context.observeEvents`` is how the sensors listen.

Kept and not drawn
~~~~~~~~~~~~~~~~~~

- ``Script`` nodes are read, kept and written, and never run.
- ``CoordinateDouble`` is kept and not drawn.
- ``FogCoordinate`` and the ``attrib`` vertex attributes are kept and not
  drawn.
- The NURBS component's nodes are X3D's own declarations; the engine's NURBS
  nodes (:doc:`NURBS <nurbs>`) are the VRML97 extension's, with other fields.

Comparing renders with Web3D's examples
---------------------------------------

``oglc-x3d-regression`` draws every ``.x3d`` document of Web3D's example
archives (``vrml.x3d.corpus``) as its author wrote it -- from its bound
viewpoint, against its own Background or black, once the textures and
Inlines it names have arrived -- and compares each render with a blessed
baseline in ``tests/reference_images/x3d_baseline``. The report shows a
reference render beside ours, and how much ours differs from it:

- ``--reference x_ite`` (the default): the document drawn by X_ITE, the MIT
  JavaScript X3D browser Web3D publishes its examples with, read from
  ``tests/reference_images/x3d_xite`` (``--reference-root`` names another
  folder). A document with no X_ITE render there is shown beside Web3D's.
- ``--reference web3d``: the render Web3D publishes of the same viewpoint.

The X_ITE renders are drawn by ``scripts/x3d_xite_references.py`` in a source
checkout, not by the installed engine:

.. code-block:: bash

   uv run scripts/x3d_xite_references.py                  # each document with no render yet
   uv run scripts/x3d_xite_references.py --only Background --refresh

``uv run`` gives the script Playwright for that run. The script installs
Playwright's headless Chromium where it is missing, and draws with WebGL in
software (SwiftShader), so a render does not depend on the machine's GPU.
X_ITE is downloaded from npm once, at a pinned version checked by its
SHA-256, and served with the documents from 127.0.0.1. Each document is
captured half a second after X_ITE reports it loaded; its ``<slug>.json``
records the X_ITE and Chromium versions and the errors the page reported.

The difference counts pixels more than 32 apart in a channel. It is for the
reader of the report and fails no run. X_ITE draws a document at the
browser's clock, and ours at a fixed time in 2000 (below), so an animated
document is at a different point of its animation in the two.

.. code-block:: bash

   oglc-x3d-regression --fetch          # the corpus with its images, once (about 550 MB)
   oglc-x3d-regression                  # exit 1 if a render differs from its baseline or fails
   oglc-x3d-regression --bless          # the renders reviewed in the report become baselines
   oglc-x3d-regression --only Geometry/Box --jobs 8

- The archives are ConformanceNist and Vrml2Sourcebook unless ``--archive``
  names others; the corpus is kept in pyvrml97's corpus directory
  (``PYVRML97_X3D_CORPUS``, else the user's cache) unless ``--corpus``
  names another. ``--fetch`` also fetches the archives whose files their
  scenes name (X3dForWebAuthors), into the same tree.
- Each document is drawn in a process of its own at 792x465, the size of
  Web3D's renders; ``--jobs`` sets how many at a time.
- Its frames are counted on the capture clock once its loads have arrived, so
  an animated scene is drawn at the same moment in every run. The clock starts
  at 2000-01-01 (``OPENGLCONTEXT_CAPTURE_START``), as X3D's times are seconds
  since 1970: a TimeSensor with ``startTime 0`` has finished by then. A document's
  loads are waited for 30 seconds at most, and its record says when that
  was not enough.
- The folder of every archive's examples is a content root
  (:ref:`untrusted-content-roots`): the examples name images and Inlines in
  folders above their own, and in other archives.
- What reading the document reported is in each row of the report.
- A render differs where more than 2% of its pixels differ by more than 8 in
  a channel (``--tolerance``, ``--diff-threshold``), as in
  ``oglc-gltf-regression``.
- A render fails where its process writes no image, or exits with a status
  other than 0 or by a signal, even after writing one; its row is an error
  naming the status and the last line the process wrote to stderr. A failed
  render is not blessed.
- ``--bless`` draws nothing: it makes the renders already in the output
  directory, as the report shows them, the baselines, with their records --
  every one, or those whose name contains a ``PART`` -- and leaves a render
  that failed.
- The exit status counts only the documents drawn in that run; a row left
  from an earlier run is shown as not drawn. ``--report-only`` counts every
  row.
- Only the XML encoding is drawn; pyvrml97's corpus tests hold the other
  encodings to the same scene graph. Scripts are not run, so a scene a
  Script builds is drawn as the document leaves it.

.. list-table:: ``oglc-x3d-regression`` options
   :widths: auto
   :header-rows: 1

   * - Option
     - What it does
   * - ``--fetch``
     - download and extract the archives, with their images and Web3D's
       renders, before drawing
   * - ``--archive NAME``
     - an archive to draw (repeatable; ConformanceNist and Vrml2Sourcebook
       where none is named)
   * - ``--corpus DIR``
     - the corpus directory (pyvrml97's where not given)
   * - ``--only PART``
     - draw only the documents whose name contains ``PART`` (repeatable)
   * - ``--bless [PART ...]``
     - make the renders already drawn the baselines, as above
   * - ``--report-only``
     - rebuild the report from the renders already drawn
   * - ``--jobs N``
     - documents drawn at a time (the processor count)
   * - ``--size WxH``
     - the render size (792x465)
   * - ``--frames N``
     - frames drawn once the loads have arrived
   * - ``--renderer pbr|vrml97``
     - the pass the documents are drawn with (``pbr``)
   * - ``--reference x_ite|web3d``
     - the reference each render is shown beside (``x_ite``)
   * - ``--reference-root DIR``
     - X_ITE's renders (``tests/reference_images/x3d_xite``)
   * - ``--baseline-root DIR``
     - the baselines (``tests/reference_images/x3d_baseline``, or
       ``OPENGLCONTEXT_X3D_BASELINE``)
   * - ``--out-dir DIR``
     - the renders, records and differences
       (``tests/x3d_regression/renders``)
   * - ``--report HTML``
     - where the report is written
   * - ``--tolerance PCT``, ``--diff-threshold N``
     - the percent of pixels that may differ (2), and by how much in a
       channel a pixel must (8)

Writing
-------

``vrml.x3d.dump(scene, path)`` writes a scene in the encoding the suffix
names, and ``vrml.x3d.dumps(scene, encoding='xml')`` returns the text. A
material's fields that X3D's node lacks are written in a ``MetadataSet``, and
an image held in memory as an ``ImageTexture`` with a ``data:`` URL; see
:doc:`PBR materials <pbr>`. pyvrml97's ``vrml.x3d`` documentation covers
writing in full.
