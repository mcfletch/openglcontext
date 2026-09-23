Using NumPy with OpenGLContext
==============================

.. rst-class:: introduction

OpenGLContext and PyOpenGL use `NumPy <https://numpy.org/>`__ arrays for
vertex data, matrices and images, and your own code will likely use them too.
This page covers creating NumPy arrays, the common ways of manipulating them,
and drawing geometry from them. It is about the array package more than about
PyOpenGL. You do not need it to start using OpenGLContext, but most
non-trivial PyOpenGL code uses these features.

NumPy stores large arrays of a single data type. It provides slicing across
several dimensions, functions that process every element of an array at once,
and conversion between arrays and Python sequences.

Creating Arrays
---------------

The house style is ``import numpy as np``, so that NumPy names are easy to
recognise. ``OpenGLContext.arrays`` re-exports the same names for the modules
that use them unqualified.

These are the functions most often used to create an array:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Function
     - What it does
     - Example
   * - ``zeros``, ``ones``
     - Create an array of a given shape and data type, filled with 0 or 1.
     - .. code-block:: python

          np.zeros((2, 3), 'd')
          np.ones((2, 3), 'f')
   * - ``array``, ``asarray``
     - Convert a sequence, often a nested one, into an array with the same
       structure, of the given data type or of a type NumPy chooses.
       ``asarray`` does not copy an argument that is already an array of the
       right type.
     - .. code-block:: python

          np.array([[2, 3, 4], [5, 6, 7]], 'i')
          np.asarray(might_be_array, 'f')
   * - ``identity``
     - Create an n by n identity matrix.
     - .. code-block:: python

          np.identity(4)
   * - ``arange``
     - Like Python's ``range``, but returns an array and accepts floating-point
       start, stop and step values.
     - .. code-block:: python

          np.arange(3.0, 0.0, -0.1, 'd')

You can give a data type as a NumPy dtype, as its character code, or as a
Python type. These are the types used for OpenGL work, with the GL type each
one matches:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - dtype
     - Code
     - OpenGL type
   * - ``np.float64``
     - ``'d'``
     - GL_DOUBLE
   * - ``np.float32``
     - ``'f'``
     - GL_FLOAT
   * - ``np.int32``
     - ``'i'``
     - GL_INT
   * - ``np.uint32``
     - ``'I'``
     - GL_UNSIGNED_INT
   * - ``np.int16``
     - ``'h'``
     - GL_SHORT
   * - ``np.uint16``
     - ``'H'``
     - GL_UNSIGNED_SHORT
   * - ``np.int8``
     - ``'b'``
     - GL_BYTE
   * - ``np.uint8``
     - ``'B'``
     - GL_UNSIGNED_BYTE

.. rst-class:: technical

Use the explicitly sized names. ``np.int_`` and plain ``int`` have a
platform-dependent width, so a buffer built from them can differ from one
machine to the next. Use unsigned types for indices: element-array buffers are
``np.uint16`` or ``np.uint32``, never signed.

Shape
~~~~~

An array's dimensions are a tuple, in indexing order, and the array's
``shape`` attribute holds them. ``reshape``, ``resize``, ``transpose`` and
``ravel`` return an array with different dimensions. Usually the result is a
view of the same memory rather than a copy, so writing to one changes the
other. Most NumPy functions also take an ``out=`` argument naming the array to
write the result into; the engine's inner loops use it to avoid allocating
memory every frame.

Basic Mathematics
~~~~~~~~~~~~~~~~~

Arithmetic operators work element by element on arrays, and accept a scalar
or another array as the second argument.

To multiply every element of an array by 3.0, write ``result = myarray *
3.0``. Addition, subtraction and division work the same way.

To multiply each element of one array by the matching element of another,
write ``result = firstarray * secondarray``. Most other arithmetic operators
work the same way.

Slicing
~~~~~~~

NumPy extends Python's slice notation to arrays with several dimensions:

.. code-block:: text

   [ start : stop : step, start : stop : step, ... ]

There is one ``start : stop : step`` group per dimension. You can leave out
trailing dimensions, and you can leave out the step and its colon. As with
ordinary slices, a missing start means zero and a missing stop means the end
of the array.

Examples make the notation clearer:

.. code-block:: pycon

   >>> m = np.array([[1,2,3,4],[5,6,7,8],[9,10,11,12],[13,14,15,16]], 'd')
   >>> m
   array([[ 1.,  2.,  3.,  4.],
          [ 5.,  6.,  7.,  8.],
          [ 9., 10., 11., 12.],
          [13., 14., 15., 16.]])

   >>> # item 0 in the first dimension
   >>> m[0]
   array([1., 2., 3., 4.])

   >>> # item 1 in the first dimension
   >>> m[1]
   array([5., 6., 7., 8.])

   >>> # item 0 in the second dimension
   >>> m[:,0]
   array([ 1.,  5.,  9., 13.])

   >>> # item 1 in the second dimension
   >>> m[:,1]
   array([ 2.,  6., 10., 14.])

   >>> # every second item in the first dimension
   >>> m[::2]
   array([[ 1.,  2.,  3.,  4.],
          [ 9., 10., 11., 12.]])

   >>> # as above, then item 1 in the second dimension of each row
   >>> m[::2,1]
   array([ 2., 10.])

   >>> # as above, but starting at item 1 of the first dimension
   >>> # (rows 1 and 3 instead of 0 and 2)
   >>> m[1::2,1]
   array([ 6., 14.])

Slices you will see often:

.. code-block:: python

   # x and y coordinates of an N×3 array of points
   xes = points[:,0]
   yes = points[:,1]

   # the first, second, ... points of each triangle in an N×3 array
   # of triangle vertices
   firstPoints = trianglePoints[::3]
   secondPoints = trianglePoints[1::3]

   # red and green channels of an X×Y×3 RGB image
   reds = image[:,:,0]
   greens = image[:,:,1]

Multiplication
~~~~~~~~~~~~~~

OpenGLContext uses three kinds of multiplication. Element-wise multiplication
is described under Basic Mathematics above. NumPy also provides the dot
product and the cross product:

.. code-block:: python

   result = np.dot(first, second)
   result = np.cross(first, second)

``np.cross`` takes 3-item vectors, or whole arrays of them.
``OpenGLContext.utilities.crossProduct`` takes two 3-item vectors and returns
the result as a 4-item list with a ``w`` of 0:

.. code-block:: python

   from OpenGLContext.utilities import crossProduct
   result = crossProduct((ux, uy, uz), (vx, vy, vz))

For arrays of vectors, use ``OpenGLContext.vectorutilities.crossProduct``,
which processes the whole array in one call instead of one Python call per
vector.

Array Functions
---------------

Slicing selects the part of an array to work on; the array functions do most
of the calculation. The groups below list the functions this project uses
most. The `NumPy routine reference
<https://numpy.org/doc/stable/reference/routines.html>`__ describes each one.

Universal (math) functions
~~~~~~~~~~~~~~~~~~~~~~~~~~

These apply a mathematical operation to every element, and accept scalars and
arrays of different types:

``absolute, add, arccos, arcsin, arctan, arctan2, bitwise_and, bitwise_or,
bitwise_xor, ceil, conjugate, cos, cosh, divide, equal, exp, fabs, floor,
fmod, greater, greater_equal, hypot, invert, left_shift, less, less_equal,
log, log10, logical_and, logical_not, logical_or, logical_xor, maximum,
minimum, multiply, negative, not_equal, power, remainder, right_shift, sin,
sinh, sqrt, subtract, tan, tanh``

Index array functions
~~~~~~~~~~~~~~~~~~~~~

These produce or use arrays of indices into another array. They avoid copying
the array being processed. For example,
``OpenGLContext.scenegraph.polygonsort`` uses ``argsort`` to produce the
indices for drawing transparent triangles back to front, without rearranging
the vertex array.

``argmax, argmin, argsort, choose, take, where, put, putmask, compress``

Functions of two arrays
~~~~~~~~~~~~~~~~~~~~~~~

These combine the values of two arrays into a new array. ``dot`` is the one
used most often.

``convolve, correlate, dot, matmul, outer, inner``

Reductions
~~~~~~~~~~

These reduce an array to a single value, such as whether every element is
true, or the sum of all elements. ``cumsum`` and ``cumprod`` return the running
sum and product as an array.

``all, any, sum, prod, trace, cumsum, cumprod``

Modified copies
~~~~~~~~~~~~~~~

These return a copy of an array with each value changed, or with its order
changed.

``around, clip, sign, sort``

The OpenGLContext Utility Modules
---------------------------------

``OpenGLContext.utilities`` provides common vector operations, one vector at
a time:

``rotMatrix((x, y, z, a))``
   Given a rotation as a unit axis x, y, z and an angle a in radians, return
   the 4×4 rotation matrix.
``normalise(vector)``
   Given a 3- or 4-item vector, return a 3-item unit vector.
``crossProduct(first, second)``
   Given two 3-item vectors, return the cross product as a 4-item vector
   with a ``w`` of 0. ``np.cross`` returns the 3-item form.
``magnitude(vector)``
   Given a 3- or 4-item vector, return its magnitude.

``OpenGLContext.vectorutilities`` provides the same operations over a whole
*array* of vectors at once: ``crossProduct``, ``crossProduct4`` (for vectors
stored as 4 items), ``normalise``, ``magnitude``, ``orientToXYZR`` and
``colinear``. Use these instead of a Python loop: each does the work in one
array operation instead of one Python call per vector.

Array-based Geometry
--------------------

OpenGL can take geometry as arrays. The program passes a pointer to each
array of data, and one call then draws thousands of vertices, with the
implementation reading the arrays itself.

In C, drawing with one call per vertex is often fast enough. In Python, the
overhead of each call is large compared with the work the call does, so draw
from arrays.

.. rst-class:: technical

The rest of this section describes the *compatibility-profile* client-array
calls, which the fixed-function tutorials use. The core profile has no client
arrays: the data goes into a vertex buffer object and is described to a
vertex array object. The NumPy array is the same in both cases; only the call
that passes it to OpenGL differs. See :doc:`Core-Profile Rendering
<renderpasses>`.

First set a pointer for each type of array you use: vertices, colours,
normals and texture coordinates. With multi-texturing there can be one texture
coordinate array per texture unit.

.. code-block:: python

   glVertexPointerd( self.verticies )
   glColorPointerd ( self.colours )
   glNormalPointerd ( self.normals )
   glTexCoordPointerd( self.textures )

These calls make the arrays the active arrays for their types. Each type has
one active array, except texture coordinates, which have one per texture
unit.

Then enable each array type you want to draw with. Use
``glEnableClientState``, not ``glEnable``: the array switches are client
state, and ``glEnable`` does not change them.

.. code-block:: python

   glEnableClientState( GL_VERTEX_ARRAY )
   glEnableClientState( GL_COLOR_ARRAY )
   glEnableClientState( GL_NORMAL_ARRAY )
   glEnableClientState( GL_TEXTURE_COORD_ARRAY )

Finally, call an array drawing function such as ``glDrawArrays`` or
``glDrawElements`` in place of a ``glBegin``/``glEnd`` block and the
``glVertex``, ``glColor``, ``glNormal`` and ``glTexCoord`` calls inside it.
The call takes the primitive type (the same values as ``glBegin``) and which
elements to draw: a start position and a count, or a list of indices into the
arrays.

.. code-block:: python

   glDrawArrays( GL_TRIANGLES, 0, 32 )
   glDrawElementsui( GL_TRIANGLES, indices )

Further Reading
---------------

- The `NumPy documentation <https://numpy.org/doc/stable/>`__ and the `NumPy
  beginner's guide
  <https://numpy.org/doc/stable/user/absolute_beginners.html>`__.

- :py:mod:`OpenGLContext.scenegraph.arraygeometry`, a simple implementation of
  array-based geometry rendering.

- :py:mod:`OpenGLContext.vectorutilities` and
  :py:mod:`OpenGLContext.triangleutilities`, for examples of array
  manipulation.

- These programs in the ``tests`` directory draw with arrays: ``gldrawarrays``,
  ``gldrawarrays_string``, ``gldrawelements``, ``glarrayelement`` and
  ``glinterleavedarrays``.
