Turning an outline into triangles
=================================

.. rst-class:: introduction

A filled shape reaches the GPU as triangles, and an outline — a letter, a
floor plan, a lake, the cap on the end of an extrusion — is not triangles
until something makes it so. ``tessellate()`` is that something: a
**constrained Delaunay triangulation** with exact-sign predicates, in
`opengl_extrusions <https://github.com/mcfletch/opengl_extrusions>`__, with no
OpenGL in it. It copes with outlines that cross themselves, holes, coincident
vertices and T-junctions.

.. code-block:: python

   from opengl_extrusions import tessellate

   result = tessellate([outer_ring, hole_ring], winding='odd', min_angle=30.0)
   result.points        # (V, 2)
   result.triangles     # (T, 3), counter-clockwise

Which parts come out solid is decided by a winding rule: ``odd`` (the default,
under which nested rings alternate), ``nonzero``, ``positive``, ``negative``
or ``abs_geq_two``. ``min_angle`` and ``max_area`` refine the mesh; an angle
target spends triangles only where the outline forces thin ones, while an area
target subdivides evenly throughout.

.. figure:: images/extrusions/tessellation.png
   :alt: Six tessellated faces with their triangle edges drawn

   From ``tests/extrusions_tessellation.py``; the white lines are the triangle
   edges. Top: a letter O (two rings, one a hole), a pentagram by the odd rule
   (the doubly-wound middle comes out empty), the same by the nonzero rule.
   Bottom: a rounded square plain, the same refined to a maximum triangle area,
   and a star refined to a minimum angle.

.. figure:: images/extrusions/fig_preprocessing.png
   :alt: Six awkward outlines and what preprocessing makes of them

   From ``tests/extrusions_preprocessing.py``: an outline crossing itself, two
   rings crossing, a T-junction, two shapes sharing an edge, near-duplicate
   vertices, and a ring closed by a repeated point.

Where the engine uses it
------------------------

End caps are tessellated, which is why an extrusion of a contour with holes
gets a cap with the holes in it — see :doc:`swept geometry <extrusions>`.
The polygonal and outlined :doc:`3D text <text>` nodes tessellate the glyph
outlines a font gives them, and any node that fills an authored outline —
a floor plan, a lake, a plot of land — does the same with this call.
