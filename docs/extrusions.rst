Swept Geometry
==============

Six geometry nodes build a shape by sweeping a 2D outline along a path: a
lathe, a spiral, a screw, two kinds of tube, and VRML97's ``Extrusion``. Each
node holds the parameters and generates its vertex arrays with
`opengl_extrusions <https://github.com/mcfletch/opengl_extrusions>`__, a NumPy
geometry generator that makes no OpenGL calls.

The result is an ordinary indexed triangle mesh, so these nodes draw through
the same path as any other geometry, in both the **core and compatibility
profiles**. They are lit, shadowed, textured, pickable and depth-sorted, and
the pass can batch them with :doc:`instancing <instancing>`.

End caps are tessellated outlines, not triangle fans, so a contour with holes
gets a cap with the same holes. The caps are filled by :doc:`the tessellator
<tessellation>`, which you can also call directly.

.. figure:: images/extrusions/shapes.png
   :alt: A lathe, a spiral, a screw, a torus, a pipe elbow and a tapering elbow

   Every swept node, from ``tests/extrusions_shapes.py``. Top: a ``Lathe`` and a
   ``Spiral`` of the same parameters -- the lathe's section stays upright as it
   climbs, the spiral's tilts with the climb -- and a ``Screw``. Bottom: a
   toroid, a ``PolyCylinder`` and a ``PolyCone``.

The nodes
---------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Node
     - What it sweeps
     - Typical uses
   * - ``Lathe``
     - a contour around the z axis, its plane staying *radial*
     - screw threads, spiral ramps, washers, turned parts
   * - ``Spiral``
     - a contour along the helix itself, its plane square to the path
     - springs, coiled wire, handrails
   * - ``Screw``
     - a contour along z while turning
     - drill bits, twisted columns, augers
   * - ``PolyCylinder``
     - a circle along a path, constant radius
     - pipes, cables, rails, barriers
   * - ``PolyCone``
     - a circle along a path, a radius at every point
     - tapering pipes, tree branches, rockets
   * - ``Extrusion``
     - VRML97's cross-section along its spine
     - anything a ``.wrl`` file asks for

``Lathe``, ``Spiral`` and ``Screw`` read their contour in the **r-z plane**:
x is the distance out from the axis, added to the sweep radius, and y is
height.

.. figure:: images/extrusions/fig_lathe.png
   :alt: A lathe under six sets of parameters

   What each of a ``Lathe``'s fields does, on one square section. Top:
   ``totalAngle`` of π and of 2π, then ``deltaZ 0.6`` over two turns -- a rising
   coil. Bottom: ``deltaRadius 0.4``, which spirals outward instead; ``sides 6``,
   a hexagonal ring; and ``sides 48``, a smooth one.

.. figure:: images/extrusions/fig_spiral.png
   :alt: A lathe and a spiral as the climb steepens

   The same parameters both ways, as the climb steepens. Top row ``Lathe``,
   bottom row ``Spiral``; left to right ``deltaZ`` of 0, 0.5 and 1.4 over one
   turn. Flat, the two are identical; the steeper the climb, the further apart
   they get.

.. figure:: images/extrusions/fig_screw.png
   :alt: Screws of varying twist and length

   Top: ``totalAngle`` of 0 (a plain bar), π and 6π, all of the same square
   section over the same length. Bottom: the same twist over a short
   ``startZ``..\ ``endZ`` and over a long one, and a five-pointed star section --
   which is what makes an auger.

.. figure:: images/extrusions/fig_polycone.png
   :alt: Six radius profiles along one path

   The effect of a per-point radius. Top: a constant radius (which is
   ``PolyCylinder``), a taper to nothing, and a barrel. Bottom: a waist, a
   stepped profile, and a taper following a curved path.

.. figure:: images/extrusions/fig_contours.png
   :alt: Six contours swept the same way

   The built-in outlines, each swept along the same straight path so only the
   contour differs: a 6- and a 24-sided circle, a rectangle, a rounded rectangle,
   and two stars.

.. figure:: images/extrusions/fig_caps.png
   :alt: Cap options

   Top: ``caps TRUE``, ``caps FALSE``, and a contour with a hole -- the cap has
   the hole in it, because caps are tessellated rather than fanned. Bottom: an
   open contour, which makes a sheet with no inside and no cap; then the same
   star-section cap refined two ways.

.. figure:: images/extrusions/fig_scale_twist.png
   :alt: Per-point scale, twist and colour

   All on the same straight path, so only the per-point parameters differ. Top:
   none; a scale tapering to 0.3; a scale whose x and y differ. Bottom: a twist
   to π/2; twist and taper together; a per-point colour.

.. code-block:: python

   from OpenGLContext.scenegraph.basenodes import Appearance, Material, Shape
   from OpenGLContext.scenegraph.extrusions import Lathe

   washer = Shape(
       geometry=Lathe(
           contour=[(0, -0.1), (0.3, -0.1), (0.3, 0.1), (0, 0.1)],
           startRadius=1.0, sides=48,
       ),
       appearance=Appearance(material=Material(diffuseColor=(0.8, 0.6, 0.2))),
   )

Shared fields
~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Default
     - What it does
   * - ``normals``
     - ``'edge'``
     - ``'facet'`` for flat faces and hard edges, ``'edge'`` for smooth around the
       contour and creased across each ring, ``'path_edge'`` for smooth both ways --
       see below
   * - ``texture``
     - ``'normalized'``
     - 0..1 both ways, ``'arc_length'`` for model units, or ``''`` for no texture
       coordinates
   * - ``solid``
     - ``TRUE``
     - whether the back faces may be culled

The generated mesh is cached on the scenegraph cache and rebuilt when a field
it depends on changes, so a slider driving ``sides`` costs one regeneration
per move rather than one per frame.

What ``normals`` does
~~~~~~~~~~~~~~~~~~~~~

.. figure:: images/extrusions/normals.png
   :alt: A hexagonal tube and a bent tube, each shaded three ways

   From ``tests/extrusions_normals.py``. Left to right in each row: ``facet``,
   ``edge``, ``path_edge``. The geometry is identical; only the normals differ.

Top, a hexagonal tube: ``facet`` gives six flat faces and six hard edges,
``edge`` blends them so a six-sided tube shades like a cylinder while its
silhouette stays a hexagon, and on a straight run ``path_edge`` has nothing
further to smooth. Bottom, a round tube round a corner: ``facet`` reads as a
stack of rings, ``edge`` stays smooth around the tube and creased at the
corner -- which is what a mitred pipe joint should look like -- and
``path_edge`` rounds the corner off visually as well, for something meant to
bend smoothly.

``edge`` is the default. It keeps curves in the outline smooth and corners in
the path sharp, which suits most shapes.

Corners
-------

.. figure:: images/extrusions/joins.png
   :alt: Four join styles round the same corner

   From ``tests/extrusions_joins.py``. Clockwise from top left: ``raw`` (the runs
   come apart), ``angle`` (a mitre, with the seam where its two surfaces meet),
   ``round`` (an elbow) and ``cut`` (a bevel). The purple hairpin is a mitre at a
   corner sharp enough that ``miterLimit`` turns it into a bevel.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - ``join``
     - At a corner
   * - ``'raw'``
     - each run swept on its own, ending square -- the tube comes apart. For a chain
       of separate objects; never for a pipe.
   * - ``'angle'``
     - a mitre, in the plane bisecting the corner, with the outside stretched to
       reach it. Continuous, and the default.
   * - ``'cut'``
     - a bevel: each run ends square and one flat band joins them. Does not reach as
       far past the corner as a mitre, and the band is shaded as the facet it is.
   * - ``'round'``
     - an elbow: the ring is turned through the bend over ``roundSegments`` steps
       (default 4), so the corner is the tube itself rotated and the contour keeps
       its size.

``PolyCylinder`` and ``PolyCone`` take a ``join`` field. ``miterLimit``
(default 4) limits how far a mitre may stretch, as a multiple of the tube's
own radius. Past the limit the mitre becomes a bevel; without a limit, the
outside of a nearly reversed corner would stretch into a spike.

Following a curve
-----------------

.. figure:: images/extrusions/curves.png
   :alt: Splines, a vertical loop and a trefoil knot

   From ``tests/extrusions_curves.py``. A Catmull-Rom sampled coarsely and
   finely, a Bézier, a B-spline, a loop through the vertical, and a trefoil knot
   swept as a closed path.

A list of points fixes how many samples a path has and where they are.
``opengl_extrusions.curves`` samples a curve to a *chord-error tolerance*
instead, which places more samples where the curve bends more:

.. code-block:: python

   from opengl_extrusions import catmull_rom
   from OpenGLContext.scenegraph.basenodes import PolyCylinder

   path = catmull_rom([(0, 0, 0), (2, 1, 0), (4, 0, 1)], tolerance=1e-3)
   rail = PolyCylinder(path=path, radius=0.1, frames='rmf')

``frames``: ``'up'`` or ``'rmf'``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``PolyCylinder`` and ``PolyCone`` orient the contour along the path in one of
two ways, set by their ``frames`` field:

- ``'up'`` keeps the contour aligned to the fixed direction in the ``up``
  field (default ``(0, 1, 0)``). It is simple and predictable; use it for a
  road or a railing. Where the path runs *parallel* to ``up`` there is no
  direction to align to, and the node reports an error instead of producing a
  frame that spins.
- ``'rmf'`` (rotation-minimizing frames, the default) carries each frame from
  the one before by the smallest rotation that turns the old direction onto the
  new one. It uses no reference direction, so it works for any path direction.
  Use it for a cable, a knot, a loop, or any path that may point anywhere.

VRML97's Extrusion
------------------

.. figure:: images/extrusions/vrml97.png
   :alt: Six VRML97 extrusions

   From ``tests/extrusions_vrml97.py``. Scale along the spine, a taper, an
   orientation turning as it travels, a curved spine, a tube with no caps, and a
   closed spine.

``Extrusion`` has the fields of ISO/IEC 14772-1:1997 clause 6.23: ``crossSection``,
``spine``, ``scale``, ``orientation``, ``beginCap``, ``endCap``, ``ccw``,
``convex`` and ``creaseAngle``.

The cross-section is read in the **x-z** plane, as the specification writes
it, and is oriented at each spine point by that specification's Spine-aligned
Cross-section Plane -- axes taken from the spine's own neighbours rather than
from any reference direction. A ``crossSection`` or ``spine`` whose last point
repeats its first is *closed*: the surface has no seam there, and a closed
spine has no ends to cap.

Texture coordinates
-------------------

.. figure:: images/extrusions/fig_texture_parameter.png
   :alt: A checkerboard on six different sweeps

   The same checkerboard on six sweeps, from ``tests/extrusions_gallery.py
   texture_parameter``. Where the squares stretch is where the mapping stretches.

The ``texture`` field takes two kinds of value. ``'normalized'`` and
``'arc_length'`` follow the sweep's own parameters: around the contour and
along the path, in 0..1 or in model units. The other twelve are the
*generated* modes of the GLE tubing library, named ``vertex`` or ``normal``,
optionally ``model``, then ``flat``, ``cyl`` or ``sph``:

.. figure:: images/extrusions/fig_texture_modes.png
   :alt: Twelve texture modes on one tube

   All twelve on one tube. ``normal_sph`` and ``normal_model_sph`` come out
   plain: on a straight tube every normal lies in the contour plane, so v is
   constant.

.. figure:: images/extrusions/fig_texture_caps.png
   :alt: Textured end caps

   End caps are mapped from the outline's own bounding box, so a texture lies
   flat across the face whatever its shape -- including one with a hole, and
   refined ones.

Generated geometry into the scenegraph
--------------------------------------

``OpenGLContext.scenegraph.frommesh`` turns any mesh with glTF-named vertex
arrays into scenegraph nodes, with no file or parsing in between:

.. code-block:: python

   from opengl_extrusions import extrude, circle
   from OpenGLContext.scenegraph.frommesh import shape_from_mesh

   pipe = extrude(circle(0.1, 16), [(0, 0, 0), (0, 1, 0), (1, 2, 0)])
   scene.children.append(shape_from_mesh(pipe, appearance=steel))

The result is a ``PBRMesh``, the same node the :doc:`glTF loader <gltf>`
builds for each primitive of a ``.glb`` file. Attribute names, component
types, index type and memory layout all match, so generated and loaded
geometry reach the render pass in the same form, and are shadowed, instanced,
picked and sorted by the same code.

No data is copied. ``PBRMesh`` converts attributes with
``asarray(..., float32)`` and ``ascontiguousarray``, and indices with
``asarray(..., uint32)``. Each of these returns its input unchanged when the
array already has that dtype and layout, and ``opengl_extrusions`` produces
arrays that do. The array the generator fills is the array uploaded to the
VBO.

``shape_from_mesh`` accepts any object with ``attributes`` and ``indices``,
not only meshes from ``opengl_extrusions``: a procedural tool, an editor or
your own script can supply one.

Demonstrations
--------------

- ``tests/extrusions_shapes.py`` -- every swept node side by side

- ``tests/extrusions_joins.py`` -- the four join styles, and the miter limit

- ``tests/extrusions_curves.py`` -- splines, adaptive sampling, closed loops

- ``tests/extrusions_vrml97.py`` -- the VRML97 node's fields

- ``tests/extrusions_normals.py`` -- the three shading modes on two subjects

- ``tests/extrusions_gallery.py`` -- one figure per parameter; the figures on
  this page are captured from it. Run ``python tests/extrusions_gallery.py
  --list`` for the list, then run it with a name to show that figure.
