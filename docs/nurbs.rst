NURBS Surfaces and Curves
=========================

A NURBS surface is a grid of control points with a knot vector along each
parametric direction. It describes a smooth shape with a few numbers instead
of thousands of triangles. ``NurbsSurface`` holds one surface,
``TrimmedSurface`` cuts pieces out of one, and ``NurbsCurve`` is the
one-dimensional case.

`opengl_extrusions <https://github.com/mcfletch/opengl_extrusions>`__, a NumPy
geometry generator, evaluates each node into an indexed triangle mesh, and
the mesh is drawn in both the **core and compatibility profiles**: lit,
shadowed, textured and pickable. Evaluation makes no GL calls, so a surface
can be built before a context exists to draw it: on a worker thread while a
scene loads, or in a test with no window.

.. figure:: images/nurbs/surfaces.jpg
   :alt: Four coloured NURBS surfaces meeting in a mound

   Four ``NurbsSurface`` patches meeting in a mound, from ``tests/molehill.py``.
   Each is a 4 by 4 control net; the shading is from the surfaces' own
   derivatives, so the seams between them are smooth.

The nodes
---------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Node
     - What it is
   * - ``NurbsSurface``
     - a control net, a knot vector each way, and optionally a weight and a colour
       per control point
   * - ``TrimmedSurface``
     - a ``surface`` plus the ``trimmingContour`` loops that bound the part of it to
       keep
   * - ``NurbsCurve``
     - a curve in space, drawn as a line strip
   * - ``Contour2D``
     - one closed trimming loop, built from joined children
   * - ``Polyline2D``
     - a straight-sided piece of a loop
   * - ``NurbsCurve2D``
     - a curved piece of a loop, in the surface's parameter square
   * - ``NurbsToleranceSample``, ``NurbsDomainDistanceSample``
     - how finely a surface is sampled — see below

The :py:mod:`Teapot <OpenGLContext.scenegraph.teapot>` uses the same code:
its 32 Bézier patches are NURBS surfaces of order 4.

.. code-block:: python

   from OpenGLContext.scenegraph.basenodes import *

   KNOT = [0, 0, 0, 0, 1, 1, 1, 1]                 # clamped cubic, 4 points
   surface = NurbsSurface(
       uDimension=4, vDimension=4,
       uKnot=KNOT, vKnot=KNOT,
       controlPoint=[[x, y, 1.0 if 0 < x < 3 and 0 < y < 3 else 0.0]
                     for y in range(4) for x in range(4)],
   )
   scene = sceneGraph(children=[Shape(geometry=surface,
                                      appearance=Appearance(material=Material()))])

A knot vector holds ``dimension + degree + 1`` non-decreasing values, and the
degree is taken from its length: a direction with 4 control points and 8 knots
is cubic. ``controlPoint`` is *v-major*: u varies fastest, as the VRML97 NURBS
proposal specifies.

Weights
-------

The ``weight`` field takes one positive number per control point. Weights
make the curve *rational*, which lets it represent a circle exactly. A quarter
circle is exact as a rational quadratic with a middle weight of √2/2, and no
polynomial represents it exactly. Equal weights give the same surface as no
weights.

.. code-block:: python

   root = 2 ** 0.5 / 2
   cylinder = NurbsSurface(
       uDimension=9, vDimension=2,
       uKnot=[0, 0, 0, .25, .25, .5, .5, .75, .75, 1, 1, 1],
       vKnot=[0, 0, 1, 1],                          # degree 1: straight up
       controlPoint=ring_points,                    # 9 around, twice
       weight=[1, root, 1, root, 1, root, 1, root, 1] * 2,
   )

A direction may be degree 1, as the cylinder's length is here. A surface that
runs straight between two rows of control points is evaluated and shaded like
any other.

Sampling: how many triangles
----------------------------

A sampling node sets a **rate**: sample intervals per unit of the surface's
knot range. Because it is a rate and not a count, two surfaces at the same
rate get triangles of the same parametric size whatever their knot ranges. A
surface whose knots run from 0 to 4 gets four times as many samples as one
whose knots run from 0 to 1.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Node
     - Field
     - Meaning
   * - ``NurbsDomainDistanceSample``
     - ``uStep``, ``vStep`` (default 100)
     - the rate itself, one for each direction
   * - ``NurbsToleranceSample``
     - ``tolerance`` (default 50)
     - a rate of 150/tolerance, held between 20 and 100

A surface with no ``sampling`` node gets a tolerance of 5, which is a rate of
30. A surface over the usual 0..1 knots then becomes a 30 by 30 lattice of
1800 triangles.

``NurbsToleranceSample`` keeps its ``method`` and ``parametric`` fields but
does not use them: only ``tolerance`` sets the rate. A smaller tolerance gives
a finer mesh, but it does not guarantee a maximum distance between the mesh
and the surface. To get a mesh of a known size, use
``NurbsDomainDistanceSample``.

Each direction is limited to 512 intervals, so an unusually large knot range
cannot produce an oversized mesh.

Distance level of detail
~~~~~~~~~~~~~~~~~~~~~~~~

A surface far from the camera is tessellated at a coarser rate, and each
level is cached separately, so walking towards a surface rebuilds it once per
level rather than every frame. It uses the same :py:mod:`distance metric
<OpenGLContext.scenegraph.tessellationlod>` as the teapot and the quadrics.
Level 0 uses the node's own sampling, so a surface close to the camera looks
exactly as authored. The coarser levels use rates of 16, 8 and 4. Set
``OPENGLCONTEXT_LOD=off`` (see :doc:`environment`) for the same output at
every distance, for example when comparing reference images.

Trimming
--------

A trimming contour is a closed loop in the surface's parameter square. **The
area to the left of a loop is kept.** A counter-clockwise loop is therefore a
boundary, a clockwise loop inside it is a hole, and a clockwise loop on its
own keeps nothing.

.. code-block:: python

   outer = Contour2D(children=[Polyline2D(point=[[0, 0], [1, 0], [1, 1], [0, 1]])])
   hole = Contour2D(children=[
       NurbsCurve2D(knot=KNOT,
                    controlPoint=[[.25, .5], [.25, .75], [.75, .75], [.75, .5]]),
       Polyline2D(point=[[.75, .5], [.5, .25], [.25, .5]]),
   ])
   trimmed = TrimmedSurface(surface=surface, trimmingContour=[outer, hole])

.. figure:: images/nurbs/trimmed.jpg
   :alt: A curved surface shading from red to green with a cone-shaped hole cut out of it

   A ``TrimmedSurface``, from ``tests/nurbsobject.py``: a counter-clockwise
   square boundary and a clockwise loop inside it, whose top is a
   ``NurbsCurve2D`` and whose point is a ``Polyline2D``. The colours are per
   control point.

A ``Contour2D`` joins its children end to end into one loop. Where one child
ends on the point the next begins with, that point is kept once. The loop
closes from its last point back to its first. A ``NurbsCurve2D`` is evaluated
at 32 points unless its ``tessellation`` field gives another count.

Trim coordinates are in the surface's own knot ranges, in the order ``(v,
u)``.

The kept region is triangulated by the same constrained Delaunay
:doc:`tessellator <tessellation>` that fills the caps of :doc:`swept geometry
<extrusions>`, refined to the triangle size the sampling rate sets. A trimmed
surface is therefore sampled as finely across its middle as an untrimmed one,
not only along its outline. The surface is then evaluated at the resulting
vertices, so a trimmed surface follows the surface's curvature rather than
having a flat hole cut in it.

Which way a surface faces
-------------------------

A surface's normal is ``∂p/∂v × ∂p/∂u``, and its triangles are wound to
match. If a surface faces away from the camera, its two parametric directions
are the other way round. Swap ``uDimension`` with ``vDimension`` and swap the
knot vectors with them, or set ``solid=0`` so the back faces are not culled.
``ccw=0`` reverses which winding the fixed-function pipeline treats as front
facing.

``geometryType`` takes ``polygon`` (the default), or ``edge`` / ``patch``,
which draw the tessellation as its edges.

Colour
------

The ``color`` field takes one colour per control point. Colours are evaluated
with the same basis functions as the surface, so a colour follows its control
point however finely the surface is sampled. A coloured surface is drawn with
the vertex-colour program, and the material supplies everything except the
diffuse colour.

Where the code is
-----------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - What is in it
   * - ``scenegraph/nurbs.py``
     - the geometry nodes and both draw paths
   * - ``scenegraph/nurbstess.py``
     - a surface node to triangles; no GL
   * - ``scenegraph/nurbstrim.py``
     - the trimming primitives
   * - ``scenegraph/nurbssampling.py``
     - the sampling nodes
   * - ``scenegraph/teapot_nurbs.py``
     - the Utah Teapot's 32 patches

Demonstrations:

- ``tests/molehill.py`` - four surfaces meeting.
- ``tests/molehill_edit.py`` - dragging their control points; see
  :doc:`editing` for ``ControlNet``.
- ``tests/nurbsobject.py`` - a trimmed surface, animated.
- ``tests/teapot_nurbs.py`` - the Utah Teapot.
