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
- EnvironmentalEffects - Background, Fog
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
- Lighting - DirectionalLight, PointLight, SpotLight
- Navigation - Billboard, Collision, LOD, NavigationInfo, OrthoViewpoint, Viewpoint,
  ViewpointGroup
- Networking - Anchor, Inline, LoadSensor
- Picking - PickableGroup
- PointingDeviceSensor - CylinderSensor, PlaneSensor, SphereSensor, TouchSensor
- Rendering - Color, ColorRGBA, Coordinate, IndexedLineSet,
  IndexedTriangleFanSet, IndexedTriangleSet, IndexedTriangleStripSet, LineSet,
  Normal, PointSet, Tangent, TriangleFanSet, TriangleSet, TriangleStripSet
- Shape - Appearance, Material, PhysicalMaterial, Shape, UnlitMaterial
- Sound - AudioClip, Sound
- Text - FontStyle, Text
- Texturing - ImageTexture, MovieTexture, MultiTextureCoordinate,
  MultiTextureTransform, PixelTexture, TextureCoordinate, TextureProperties,
  TextureTransform
- Texturing3D - TextureTransformMatrix3D
- Time - TimeSensor

.. x3d-implemented-end

The triangle sets and ``ElevationGrid`` are drawn as the mesh their fields
build (``OpenGLContext.scenegraph.meshgeometry``): normals that are not given
are generated, smoothed across folds within ``creaseAngle`` for
``ElevationGrid`` and across every shared coordinate for the triangle sets
whose ``normalPerVertex`` is true; ``colorPerVertex`` and ``normalPerVertex``
false give one value per triangle (per quad for ``ElevationGrid``); ``ccw``
false turns the triangles round. A ``MultiTextureCoordinate``'s entries are
``TEXCOORD_0``, ``TEXCOORD_1`` and so on, and an entry's ``mapping`` label is
what a material's ``...TextureMapping`` names. The renderer reads two
coordinate sets. A ``LineSet`` is drawn as an ``IndexedLineSet``.

The Geometry2D nodes lie in the z=0 plane facing +z: ``Rectangle2D``,
``TriangleSet2D``, ``Disk2D`` and ``ArcClose2D`` as meshes with texture
coordinates across their bounds, ``Circle2D``, ``Arc2D`` and ``Polyline2D`` as
lines, and ``Polypoint2D`` as points. A curve has 48 segments to a whole turn
(``geometry2d.SEGMENTS``).

Materials and appearance are described with the :doc:`PBR renderer <pbr>`:
``PhysicalMaterial``, ``UnlitMaterial`` and ``Material`` with their texture
fields and mapping labels, ``Appearance.alphaMode`` and ``alphaCutoff``, and
``MultiTextureTransform``. A ``Material``'s ``diffuseTexture``,
``emissiveTexture``, ``normalTexture`` and ``occlusionTexture`` are its base
colour, emissive, normal and occlusion maps, and its ``normalScale`` and
``occlusionStrength`` are read; without a ``diffuseTexture``, the
appearance's ``texture`` is the base colour map. ``ambientTexture``,
``shininessTexture`` and ``specularTexture`` are kept and not drawn.
``TwoSidedMaterial`` and ``Appearance.backMaterial`` are kept and not drawn.

A grouping node or shape whose ``visible`` is false is not drawn, picked or
shadowed, nor is anything under it; setting it takes effect on the next frame.

A ``DirectionalLight`` whose ``global`` is false (X3D's default) lights only
the descendants of its parent grouping node; point and spot lights, global by
default, light everything. A light casts shadows where its ``shadows`` is
true, and ``shadowIntensity`` sets how dark they are; ``Shape.castShadow``
false leaves a shape out of the shadow maps. See :doc:`Shadows <shadows>`.
The engine's lights made in code are global and cast shadows by default.

.. _x3d-binding:

The event utilities, sequencers, followers and the interpolators X3D adds to
VRML97's are pyvrml97's behaviours (``vrml.x3d.runtime``,
``vrml.x3d.followers``). In the engine:

- A scene's time is the engine's (``systemtime.systemTime``, which a capture
  steps a frame at a time): ``SceneGraph.clock`` is what pyvrml97's timed
  nodes read, and the engine's own timed classes read it in no scene too.
- A ``TimeTrigger`` sends the engine's time.
- A ``TimeSensor`` (``vrml.x3d.timesensor``) is polled by each context it is
  bound to on every pass of the event cascade, at the engine's time, and runs
  as X3D says from ``startTime`` to ``stopTime``, pausing at ``pauseTime``
  and resuming at ``resumeTime``. ``pause()`` and ``resume()`` set those two
  to the engine's time. ``rate`` sets how fast its cycles run against the engine's
  clock, and can be changed while it runs.
- A ``LoadSensor`` is polled in the same way. ``Inline`` and ``ImageTexture``
  record their load state as they read (``vrml.x3d.loadsensor``); other url
  nodes record none and are not waited for.
- The background, fog and viewpoint the pass uses are the bound ones, on
  X3D's bind stacks (``vrml.x3d.binding``): of the nodes the scene draws, the
  topmost on its stack, and with none bound the first. ``set_bind``, sent by
  a route or set from Python, chooses another, and ``isBound`` and
  ``bindTime`` are sent as X3D says. The engine's own backgrounds
  (``SimpleBackground``, ``SphereBackground``, ``CubeBackground``,
  ``HDRBackground``) are bindable in the same way. The next-viewpoint key
  binds the viewpoint after the bound one
  (``viewpointbinding.next_viewpoint``).
- A bound viewpoint's ``nearDistance`` and ``farDistance`` set the clip
  planes where positive. An ``OrthoViewpoint`` projects orthographically
  through its ``fieldOfView`` window (minimum x, minimum y, maximum x,
  maximum y), widened along one axis to the shape of the window it is drawn
  in (``ViewPlatform.setOrthographic``); a perspective viewpoint bound after
  it ends the orthographic projection.
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
- An ``Anchor`` draws its children as a group, and a click released over
  them calls ``Context.OnAnchor(anchor, url, parameter)``. The context binds
  the viewpoint a ``#name`` url names; opening any other url is left to an
  application that overrides ``OnAnchor``.
- The bound ``NavigationInfo`` (``OpenGLContext.move.navigationinfo``):
  ``headlight`` true adds a headlight to the scene's lights and false leaves
  it off; a scene with no NavigationInfo has the headlight only where it has
  no lights. When one is bound, the first of its ``type`` values the
  context's declared movement modes offer is selected: ``WALK`` is ``walk``
  or ``fps``, ``FLY`` is ``fly``, and ``EXAMINE``, ``LOOKAT`` and
  ``EXPLORE`` are ``examine``. A context with no declared modes keeps its
  own navigation. A positive ``visibilityLimit`` is the far clipping
  distance from the time it is bound. ``speed``, ``avatarSize`` and the
  transition fields are not read.
- A ``ViewpointGroup``'s viewpoints are the scene's; the next-viewpoint key
  passes over those of a group that is not ``displayed``, or that has a
  ``size`` and the viewer is outside the box of that size about its
  ``center``.
- A follower moves a step each frame on the engine's clock while it is
  moving, queued on its window's render queue.
- A ``KeySensor`` hears every key its window receives, including keys a
  program has bound itself: ``keyPress`` for a character, ``actionKeyPress``
  for the function, arrow and page keys, and ``shiftKey``, ``controlKey`` and
  ``altKey`` while those are held.
- A ``StringSensor`` hears every character typed into its window.

``Context.observeEvents`` is how the sensors listen.

An ``Inline`` reads any format a registered reader opens: another X3D or
VRML97 world, an OBJ model or a glTF model. Its scene is read on the loader
pool and drawn from the frame after it arrives. See :ref:`x3d-worlds`.

Kept and not drawn
~~~~~~~~~~~~~~~~~~

- ``Script`` nodes are read, kept and written, and never run.
- ``TextureCoordinateGenerator``, ``FogCoordinate`` and the ``attrib`` vertex
  attributes are kept; a set whose texture coordinates come from a generator
  is reported once.
- ``CoordinateDouble`` is kept and not drawn.
- The NURBS component's nodes are X3D's own declarations; the engine's NURBS
  nodes (:doc:`NURBS <nurbs>`) are the VRML97 extension's, with other fields.

Writing
-------

``vrml.x3d.dump(scene, path)`` writes a scene in the encoding the suffix
names, and ``vrml.x3d.dumps(scene, encoding='xml')`` returns the text. A
material's fields that X3D's node lacks are written in a ``MetadataSet``, and
an image held in memory as an ``ImageTexture`` with a ``data:`` URL; see
:doc:`PBR materials <pbr>`. pyvrml97's ``vrml.x3d`` documentation covers
writing in full.
