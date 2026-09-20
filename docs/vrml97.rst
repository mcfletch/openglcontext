Loading VRML97
==============

.. rst-class:: introduction

This document describes the (partial) VRML97 implementation provided by the
OpenGLContext and vrml packages.  The VRML97 ISO standard is a large and
complex specification, and the OpenGLContext implementation supports only a
small subset of its functionality, hopefully a useful subset.  You can load,
render and re-save scenegraph's from VRML97 files, as well as render a number
of the more common nodes.

What is Implemented?
--------------------

OpenGLContext is only a partial implementation of `VRML97
<http://www.web3d.org/resources/vrml_ref_manual/Book.html>`__.  It provides a
subset targeted at the output of common 3-D modelers. In particular, the nodes
which are implemented (at least partially) by OpenGLContext are as follows:

- `Transform
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Transform>`__,
  `Group
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Group>`__,
  `Switch
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Switch>`__

- `PointLight
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PointLight>`__,
  `SpotLight
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#SpotLight>`__,
  `DirectionalLight
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#DirectionalLight>`__

- `Background
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Background>`__

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
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Box>`__

- `Sphere
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Sphere>`__,
  `Cone
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Cone>`__,
  `Cylinder
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Cylinder>`__

- `Text
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Text>`__,
  `FontStyle
  <http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#FontStyle>`__
  (with the FontTools package)

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

In addition, OpenGLContext provides a partial implementation of the VRML97
`NURBs extension
<http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nurbsproposal.html>`__
proposal by Blaxxun Interactive:

- `Polyline2D
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#Polyline2D>`__,`NurbsCurve2D
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#NurbsCurve2D>`__,`Contour2D
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#Contour2D>`__

- `NurbsSurface
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#NurbsSurface>`__,`TrimmedSurface
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#TrimmedSurface>`__,

- `NurbsCurve
  <http://www.blaxxun.com/developer/contact/3d/nurbs/spec/nodes.htm#NurbsCurve>`__

And OpenGLContext provides a number of specialized nodes which are not part of
the VRML97 specification:

- :py:mod:`CubeBackground <OpenGLContext.scenegraph.cubebackground>` -- A
  Background node with only cubic image map support (no sphere)

- :py:mod:`SphereBackground <OpenGLContext.scenegraph.spherebackground>` -- A
  Background node with only gradient sphere support (no cubic image map)

- :py:mod:`MMImageTexture <OpenGLContext.scenegraph.imagetexture>` -- A
  mip-mapped ImageTexture node, by default this is used to implement regular
  ImageTexture nodes

- :py:mod:`IndexedPolygons <OpenGLContext.scenegraph.indexedpolygons>` and
  :py:mod:`ArrayGeometry <OpenGLContext.scenegraph.arraygeometry>` -- Array
  based geometry type suitable for rendering "vertex"-oriented geometry found in
  many 3-D file types

- :doc:`Lathe, Screw, Spiral, PolyCylinder and PolyCone <extrusions>` -- swept
  geometry, generated as vertex arrays and drawn in either profile

- :doc:`Extrusion <extrusions>` -- VRML97's own node: a cross-section swept
  along a spine, with the specification's scale, orientation, caps, ``ccw`` and
  ``creaseAngle`` fields

- :py:mod:`Shader, ShaderAttribute, GLSLShader, ShaderBuffer, FloatUniform\*,
  IntUniform\*, TextureUniform <OpenGLContext.scenegraph.shaders>` -- Shader
  (and VBO)-based geometry

- :py:mod:`Teapot <OpenGLContext.scenegraph.teapot>` -- the Utah Teapot,
  tessellated from its 32 Bezier patches by the NURBS evaluator. ``size``
  matches ``glutSolidTeapot``'s scale argument, ``lid`` and ``solid`` toggle the
  lid and the polygon mode, and ``steps`` fixes the sampling rate (larger is
  finer; 0, the default, picks it from the camera distance)

Despite the small number of implemented nodes in OpenGLContext, the parser and
scenegraph structures of the vrml package support the entire VRML97
specification, so although particular nodes may not be rendered, many scenes
may be loaded which include nodes other than those in the lists above.

.. rst-class:: technical

VRML97 scenes render through the same rendering passes as the rest of
OpenGLContext: the legacy fixed-function pipeline in the compatibility
profile, and the GLSL VRML97 lighting shaders in the :doc:`core profile
<renderpasses>`. Under the :doc:`PBR renderer <pbr>`, VRML97 ``Material``
nodes are up-converted to metallic/roughness so a VRML97 scene can be lit by
the same physically based pipeline used for glTF content.

Loading VRML97 Files
--------------------

Basic operation of the VRML97 :py:mod:`loader <OpenGLContext.loaders.loader>`
is as follows:

.. code-block:: python

   from OpenGLContext.loaders.loader import Loaderscenegraph = Loader.load( myurl, baseURL=None )

The URL can be either a single or multi-value string (i.e. a list of strings).
 If the base URL is not None, then the urls in myurl will be interpreted
relative to the base URL.  If the URL is a filename, the file will be opened,
read, potentially un-gzipped, parsed, and converted to a scenegraph instance.

.. rst-class:: technical

The VRML97 parser is built on `SimpleParse
<https://github.com/mcfletch/simpleparse>`__, which is now a required
dependency of OpenGLContext and is installed automatically with it (it also
underpins `PyVRML97 <https://github.com/mcfletch/pyvrml97>`__). The grammar
uses the "cut" production to raise a ``SyntaxError`` when a file isn't
properly formed.  You can catch those, as well as ``IOError``\ s, around the
call to "load".  Note, however, that for certain resources (image textures,
inlined scenes, shader sources and HDR panoramas), the actual loading is done
on the background loader pool, which logs a message rather than raising where
a resource cannot be read. See :ref:`Loading without stopping the frame
<background-loading>` for how to wait for those to finish.

You can register a new prototype for use by the VRML97 loader by calling the
standardPrototype function in the loader module with your new prototype as an
argument:

.. code-block:: python

   vrml97.standardPrototype( myNewPrototype )

The prototype's name, as reported by vrml.protofunctions.name(prototype) will
then be bound to your prototype during loading.  Note that you can replace any
built-in prototype with this mechanism as well.

Manipulating Nodes Programmatically
-----------------------------------

Basic operations with a scenegraph...

.. code-block:: python

   # Get a particular node-instance by it's VRML DEF namemyNamedNode = scenegraph.getDEF( "My-Named-Node" )# Give an instance a new VRML DEF namescenegraph.regDefName( "My-New-Name", myNamedNode )# Get a prototype from the scenegraph's namespaceprototype = scenegraph.getProto( "Transform" )

The :py:mod:`protofunctions <vrml.protofunctions>` module provides for "safe"
manipulation and query of node and prototype structures.  Although you can
normally access a node's DEF name as node.DEF, it's root scenegraph as
node.root, and it's field definition as node.__class_\_.fieldname, it is
possible for a prototype to define a field "DEF" or "root" which shadows those
convenience properties.  And using node.__class_\_ just isn't recommended
anywhere.

.. code-block:: python

   # get the root scenegraph for a nodescenegraph = protofunctions.root( node )# get a particular field definition for a node/prototype by namefield = protofunctions.getField( node, 'name' )field = protofunctions.getField( proto, 'name' )# get all fields for a node/prototypefields = protofunctions.getFields( node )fields = protofunctions.getFields( proto )

Sample of interacting with a VRML node...

.. code-block:: python

   from OpenGLContext.scenegraph import basenodestransform = basenodes.Transform (	translation = [0, 1,0],	rotation = [0, 1,0,3.14159],	children = [		basenodes.Group ()	],)print("Transform Translation", transform.translation)transform.translation = [2,3,4]print("After Alteration", transform.translation)for child in transform.children:	print(child)

Field-type equivalents.  Note that there is coercian support...

.. list-table::
   :widths: auto
   :header-rows: 1

   * - VRML FieldType
     - SFField Python Data Type
     - MFField Python Data Type
   * - [SF/MF]Int32
     - int
     - NumPy int array
   * - [SF/MF]Float
     - float
     - NumPy double array
   * - [SF/MF]String
     - string (interpreted as UTF-8 unicode)
     - list of strings
   * - [SF/MF]Time
     - float (time-module float)
     - NumPy double array
   * - SFBool
     - int (0/1)
     - 
   * - [SF/MF]Vec2f
     - 2-item NumPy double array
     - x\*2 NumPy double array
   * - [SF/MF]Color, [SF/MF]Vec3f
     - 3-item NumPy double array
     - x\*3 NumPy double array
   * - [SF/MF]Rotation
     - 4-item NumPy double array
     - x\*4 NumPy double array
   * - SFImage
     - NumPy int array
     - 

The Scenegraph Cache
--------------------

Most rendering nodes in OpenGLContext are written to take advantage of the
built-in scenegraph cache.  The cache is used to store partial rendering
solutions (for example, tessellations of vertex-based geometry) in order to
allow per-frame operations to proceed as quickly as possible.  The cache
operates by watching for changes to fields on nodes to invalidate the cached
data.  Each node can have any number of cached pieces of data.

If you are wanting to write your own rendering node, the IndexedLineSet node
provides a good example of using the cache for storing a display-list where
the cache should be invalidated based on a number of different fields of two
different nodes.

Creating New Prototypes
-----------------------

If you would like to create a new node-type (prototype), you can either define
the prototype using a VRML97 prototype or create it directly in Python. 
Prototypes are implemented as Python classes inheriting from the
vrml.node.Node class.  Normally you will also want to inherit from one of the
marker classes in vrml.vrml97.nodetypes, which is what tells the scenegraph
what roles your node can play in the graph.

You can find a very straightforward example of defining new node-types in
OpenGLContext.scenegraph.extrusions, where three (non-standard) geometric
node-types are added to the system.

To make your new node-type available to the VRML97 loader, you can call
OpenGLContext.loaders.vrml97.standardPrototype( cls ) on your prototype
class.  This allows nodes in your VRML97 files to reference the nodes as
built-ins.

There is a lot of sample code for creating your own scenegraph nodes in the
scenegraph sub-package. Difficulties with it can go to
`Mike <mailto:mcfletch@vrplumber.com>`__ or to the `issue tracker
<https://github.com/mcfletch/openglcontext/issues>`__.

Event Model
-----------

OpenGLContext has a more limited :doc:`event model <eventmodel>` than that
specified in VRML97.  It allows for routing, and provides basic event
setting/getting with the ability to define handlers for the events, but it
does not attempt to implement the non-deterministic VRML behaviour.

Each field on each node sends a PyDispatcher event on setting, deletion or
routing to an event.  The field and event classes are both descriptors.  They
provide all sorts of support machinery for working with the field, including
support for copying the node, and generating prototype descriptions.  The
field class has a very small C accelerator function which replaces the fget
method (when available), without this performance will noticeably suffer.

You can define a method to be called before an event (but not a field) is set
simply by defining a method named on\_fieldname where fieldname is the name of
the field.  There are few examples of this in OpenGLContext, as this is a new
feature in version 2.0.0 final.  You will see it in the
OpenGLContext.scenegraph.interpolators module.

ROUTE objects can be constructed either in VRML97 files, or by constructing
the routes directly.  ROUTEs are just regular nodes with 4 fields, source,
sourceField, destination, and destinationField.  On creation they are bound
(i.e. they start routing between the source and destination).

.. rst-class:: technical

Note that a ROUTE does not do a regular set on a field to which it is routed. 
It sets the value, but instead of sending a ('set',destinationField) message,
it sends a ('route',destinationField) message.  This allows code to
distinguish between a user sending a message by setting a field and an event
cascade setting the field.  The ROUTE machinery watches for the
('route',destinationField) messages in order to do continued forwarding.
