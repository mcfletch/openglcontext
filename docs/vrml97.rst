Loading VRML97
==============

.. rst-class:: introduction

OpenGLContext loads `VRML97
<http://www.web3d.org/resources/vrml_ref_manual/Book.html>`__ files into its
scenegraph, renders them, and saves a scenegraph back to VRML97. The parser
and the scenegraph model come from the `PyVRML97
<https://github.com/mcfletch/pyvrml97>`__ package (``vrml``), which reads the
whole VRML97 specification. OpenGLContext renders the subset of nodes that
3D modelling tools commonly write, listed below. A file that uses other nodes
still loads; those nodes are kept in the scenegraph but are not drawn.

To open a VRML97 file and look at it, use :doc:`oglc-view <viewer>`.

Supported nodes
---------------

OpenGLContext renders or implements these VRML97 nodes, some of them only in
part:

- `Transform
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Transform>`__,
  `Group
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Group>`__,
  `Switch
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Switch>`__,
  `Billboard
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Billboard>`__,
  `Collision
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Collision>`__,
  `Inline
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Inline>`__,
  `LOD
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#LOD>`__
  (see :doc:`Levels of detail <lod>`)

- `PointLight
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PointLight>`__,
  `SpotLight
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#SpotLight>`__,
  `DirectionalLight
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#DirectionalLight>`__

- `Background
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Background>`__,
  `Fog
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Fog>`__
  (see :ref:`Fog <fog>`),
  `Viewpoint
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Viewpoint>`__

- `Shape
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Shape>`__,
  `Appearance
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Appearance>`__,
  `Material
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Material>`__,
  `ImageTexture
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#ImageTexture>`__,
  `PixelTexture
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PixelTexture>`__,
  `TextureTransform
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#TextureTransform>`__

- `IndexedFaceSet
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#IndexedFaceSet>`__,
  `IndexedLineSet
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#IndexedLineSet>`__,
  `PointSet
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PointSet>`__,
  `Box
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Box>`__,
  `Sphere
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Sphere>`__,
  `Cone
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Cone>`__,
  `Cylinder
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Cylinder>`__

- `Extrusion
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Extrusion>`__:
  a cross-section swept along a spine, with the specification's scale,
  orientation, caps, ``ccw`` and ``creaseAngle`` fields (see
  :doc:`Extrusions <extrusions>`)

- `Text
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Text>`__,
  `FontStyle
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#FontStyle>`__
  (with the FontTools package; see :doc:`Text <text>`)

- `Sound
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Sound>`__,
  `AudioClip
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#AudioClip>`__
  (see :doc:`Audio <audio>`)

- `OrientationInterpolator
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#OrientationInterpolator>`__,
  `ColorInterpolator
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#ColorInterpolator>`__,
  `ScalarInterpolator
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#ScalarInterpolator>`__,
  `PositionInterpolator
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PositionInterpolator>`__,
  `CoordinateInterpolator
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#CoordinateInterpolator>`__

- `TimeSensor
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#TimeSensor>`__

OpenGLContext also implements part of the VRML97 `NURBS extension
<http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nurbsproposal.html>`__
proposed by Blaxxun Interactive (see :doc:`NURBS <nurbs>`):

- `Polyline2D
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#Polyline2D>`__,
  `NurbsCurve2D
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#NurbsCurve2D>`__,
  `Contour2D
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#Contour2D>`__

- `NurbsSurface
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#NurbsSurface>`__,
  `TrimmedSurface
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#TrimmedSurface>`__

- `NurbsCurve
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#NurbsCurve>`__

OpenGLContext adds these nodes, which are not part of the VRML97
specification:

- :py:mod:`CubeBackground <OpenGLContext.scenegraph.cubebackground>` -- a
  background with a cubic image map only (no gradient sphere)

- :py:mod:`SphereBackground <OpenGLContext.scenegraph.spherebackground>` -- a
  background with a gradient sphere only (no cubic image map)

- :py:mod:`MMImageTexture <OpenGLContext.scenegraph.imagetexture>` -- a
  mip-mapped ImageTexture. By default, OpenGLContext uses it to implement
  ordinary ImageTexture nodes

- :py:mod:`IndexedPolygons <OpenGLContext.scenegraph.indexedpolygons>` and
  :py:mod:`ArrayGeometry <OpenGLContext.scenegraph.arraygeometry>` -- geometry
  stored as vertex arrays, the form many 3D file formats use

- :doc:`Lathe, Screw, Spiral, PolyCylinder and PolyCone <extrusions>` -- swept
  geometry, generated as vertex arrays and drawn in either profile

- :py:mod:`Shader, ShaderAttribute, GLSLShader, ShaderBuffer, FloatUniform\*,
  IntUniform\*, TextureUniform <OpenGLContext.scenegraph.shaders>` -- geometry
  drawn with your own GLSL shaders and vertex buffers

- :py:mod:`Teapot <OpenGLContext.scenegraph.teapot>` -- the Utah Teapot,
  tessellated from its 32 Bézier patches by the NURBS evaluator. ``size``
  matches ``glutSolidTeapot``'s scale argument. ``lid`` and ``solid`` turn the
  lid and the polygon mode on and off. ``steps`` sets the sampling rate
  (larger is finer); the default, 0, chooses it from the camera distance

- :doc:`ScreenCoverageLOD <lod>` -- a level-of-detail node that chooses by
  screen coverage rather than distance

.. rst-class:: technical

VRML97 scenes render through the same :doc:`rendering passes <renderpasses>`
as the rest of OpenGLContext: the fixed-function pipeline in the
compatibility profile, and GLSL shaders implementing the VRML97 lighting
model in the core profile. Under the :doc:`PBR renderer <pbr>`, VRML97
``Material`` nodes are converted to metallic/roughness materials, so a VRML97
scene is lit by the same pipeline as glTF content.

Loading VRML97 files
--------------------

Load a file with the :py:mod:`loader <OpenGLContext.loaders.loader>`:

.. code-block:: python

   from OpenGLContext.loaders.loader import Loader

   scenegraph = Loader.load( myurl, baseURL=None )

``myurl`` is a single URL or a list of URLs to try in turn. If ``baseURL`` is
not ``None``, relative URLs are resolved against it. For a file name, the
loader opens the file, reads it, decompresses it if it is gzipped, parses it
and converts it to a scenegraph.

The VRML97 parser is built on `SimpleParse
<https://github.com/mcfletch/simpleparse>`__, which is installed with
OpenGLContext. A file that is not well formed raises ``SyntaxError``. A file
that cannot be read raises ``IOError``. Catch both around the call to
``load``.

Some resources are loaded later, on the background loader pool: image
textures, inlined scenes, shader sources and HDR panoramas. A failure there
logs a message rather than raising. See :ref:`Loading without stopping the
frame <background-loading>` for how to wait for those loads to finish.
:doc:`Loading content you did not write <untrusted>` describes the limits on
what a file's ``url`` fields can reach.

Working with the scenegraph
---------------------------

Find and name nodes through the scenegraph:

.. code-block:: python

   # Get a particular node instance by its VRML DEF name
   myNamedNode = scenegraph.getDEF( "My-Named-Node" )
   # Give an instance a new VRML DEF name
   scenegraph.regDefName( "My-New-Name", myNamedNode )
   # Get a prototype from the scenegraph's namespace
   prototype = scenegraph.getProto( "Transform" )

A node has convenience properties: ``node.DEF`` for its DEF name,
``node.root`` for its root scenegraph, and ``node.__class__.fieldname`` for a
field definition. A prototype can define its own field named ``DEF`` or
``root``, which hides the property of the same name. The :py:mod:`protofunctions
<vrml.protofunctions>` module reads these values safely in every case, so use
it in code that handles arbitrary nodes:

.. code-block:: python

   from vrml import protofunctions

   # get the root scenegraph for a node
   scenegraph = protofunctions.root( node )
   # get a particular field definition for a node/prototype by name
   field = protofunctions.getField( node, 'name' )
   field = protofunctions.getField( proto, 'name' )
   # get all fields for a node/prototype
   fields = protofunctions.getFields( node )
   fields = protofunctions.getFields( proto )

Create a node and change its fields like any Python object:

.. code-block:: python

   from OpenGLContext.scenegraph import basenodes

   transform = basenodes.Transform(
       translation = [0, 1, 0],
       rotation = [0, 1, 0, 3.14159],
       children = [
           basenodes.Group(),
       ],
   )
   print("Transform Translation", transform.translation)
   transform.translation = [2, 3, 4]
   print("After Alteration", transform.translation)
   for child in transform.children:
       print(child)

Field types
~~~~~~~~~~~

Setting a field converts the value to the field's type, so a list becomes a
NumPy array where the field holds one. Each VRML97 field type has these Python
types:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - VRML field type
     - SF (single value)
     - MF (multiple values)
   * - [SF/MF]Int32
     - int
     - NumPy int32 array
   * - [SF/MF]Float
     - float
     - NumPy float array
   * - [SF/MF]String
     - str
     - list of str
   * - [SF/MF]Time
     - float (seconds, as from the ``time`` module)
     - NumPy float array
   * - SFBool
     - int (0/1)
     -
   * - [SF/MF]Vec2f
     - 2-item NumPy float array
     - (n, 2) NumPy float array
   * - [SF/MF]Color, [SF/MF]Vec3f
     - 3-item NumPy float array
     - (n, 3) NumPy float array
   * - [SF/MF]Rotation
     - 4-item NumPy float array
     - (n, 4) NumPy float array
   * - SFImage
     - NumPy int array
     -

The scenegraph cache
--------------------

Most rendering nodes in OpenGLContext store expensive intermediate results in
the scenegraph cache: a tessellation, a vertex buffer, a display list. Each
cached item records the fields it depends on. When one of those fields
changes, the cache drops the item and the node rebuilds it on the next frame.
A node can have any number of cached items.

To write your own rendering node, see ``IndexedLineSet``
(``OpenGLContext.scenegraph.indexedlineset``) for an example. It caches its
vertex buffers and its display list with ``mode.cache.holder()``, and makes
each depend on several fields of the line set and of its ``Coordinate`` and
``Color`` nodes.

Creating new prototypes
-----------------------

To create a new node type (a prototype), declare a VRML97 ``PROTO`` or write a
Python class. A Python prototype is a class that inherits from
``vrml.node.Node``. It usually also inherits from one of the marker classes in
``vrml.vrml97.nodetypes``, which tell the scenegraph which roles the node can
play (for example, geometry or a child node).

``OpenGLContext.scenegraph.extrusions`` is a short example: it defines the
swept-geometry node types listed above.

To make a node type available to the VRML97 loader, register it:

.. code-block:: python

   from OpenGLContext.loaders import vrml97

   vrml97.standardPrototype( MyNewNode, 'MyNewNode' )

VRML97 files can then use the node as if it were built in, without a
``PROTO`` declaration. The name registered is the prototype's own name, as
``vrml.protofunctions.name(prototype)`` returns it. The second argument is
the name you expect; the loader logs a warning if the two differ. Registering
a name that already exists replaces the built-in prototype.

The ``OpenGLContext.scenegraph`` package has many more node classes to use as
examples. Questions can go to `Mike <mailto:mcfletch@vrplumber.com>`__ or to
the `issue tracker <https://github.com/mcfletch/openglcontext/issues>`__.

Event model
-----------

OpenGLContext's :doc:`event model <eventmodel>` supports a subset of VRML97
events. It supports routing, setting and reading events, and handlers for
events. It does not implement VRML97's non-deterministic event behaviour.

Each field on each node sends a `PyDispatcher
<https://github.com/mcfletch/pydispatcher>`__ signal when it is set, deleted,
or set by a route. Fields and events are Python descriptors. They also
support copying a node and generating prototype descriptions. The optional C
accelerator package ``vrml_accelerate`` speeds up reading field values;
without it, field access is slower.

To run code when an event (not a field) is set, define a method named
``on_eventname`` on the node, where ``eventname`` is the event's name. The
method is called with the new value before the value is stored. The
interpolators in ``OpenGLContext.scenegraph.interpolators`` use this for
``set_fraction``.

Create a ROUTE in a VRML97 file or in Python. A ROUTE is an ordinary node with
four fields: ``source``, ``sourceField``, ``destination`` and
``destinationField``. It starts routing from source to destination when it
is created.

.. rst-class:: technical

A ROUTE does not set its destination field in the ordinary way. It stores the
value and sends a ``('route', destinationField)`` signal instead of a
``('set', destinationField)`` signal. Code can then tell a value set directly
from a value set by an event cascade. The ROUTE machinery listens for
``('route', destinationField)`` signals to forward the value along further
routes.
