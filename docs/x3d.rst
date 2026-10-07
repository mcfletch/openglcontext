Loading X3D
===========

.. rst-class:: introduction

OpenGLContext loads X3D documents into its scenegraph and draws them with the
:doc:`PBR renderer <pbr>`. `X3D <https://www.web3d.org/standards>`__ is
VRML97's successor, standardised by the Web3D Consortium as ISO/IEC 19775. The
reading and writing are pyvrml97's ``vrml.x3d``; the engine supplies the node
implementations that draw. To open an X3D file and look at it, use
:doc:`oglc-view <viewer>`.

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

- Core - MetadataBoolean, MetadataDouble, MetadataFloat, MetadataInteger,
  MetadataSet, MetadataString, WorldInfo
- EnvironmentalEffects - Background, Fog
- EnvironmentalSensor - ProximitySensor, VisibilitySensor
- Geometry3D - Box, Cone, Cylinder, ElevationGrid, IndexedFaceSet, Sphere
- Grouping - Group, Switch, Transform
- Interpolation - ColorInterpolator, CoordinateInterpolator,
  NormalInterpolator, OrientationInterpolator, PositionInterpolator,
  ScalarInterpolator
- Lighting - DirectionalLight, PointLight, SpotLight
- Navigation - Billboard, Collision, LOD, NavigationInfo, Viewpoint
- Networking - Anchor, Inline
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
