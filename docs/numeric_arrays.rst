Using Numpy with OpenGLContext
==============================

.. rst-class:: introduction

In this document you will learn to

- create NumPy arrays

- perform common manipulations of NumPy arrays

- draw geometry using data from a NumPy array

Array math is used throughout the OpenGLContext project, and you will likely
want to make use of it in your own code.  This document focuses primarily on
the array package itself, rather than on PyOpenGL.  Mastering the features
shown here will be useful when doing non-trivial programming in PyOpenGL, but
it's not necessary to know this material before you start playing with
OpenGLContext.

`NumPy <https://numpy.org/>`__ makes it easy to work with (potentially large)
homogenous arrays of a given data type.  It provides extended slicing
semantics for dealing with multidimensional arrays, utility functions for
processing all elements of an array, and mechanisms for storing and converting
to/from arrays and native Python data structures.

Creating Arrays
---------------

The house style is ``import numpy as np``, so that a reader can see at a
glance which names are the array package's. ``OpenGLContext.arrays``
re-exports the same names for the modules that use them unqualified.

Creating an array is done with one of a set of functions, each of which has a
particular purpose (note, these are just the commonly used functions):

.. list-table::
   :widths: auto

   * - zeros, ones
     - Generate an array filled with either 0 or 1 values of a given size and data
       type.
     - .. code-block:: python

          np.zeros((2, 3), 'd')np.ones((2, 3), 'f')
   * - array, asarray
     - Convert a sequence (often a nested sequence) into an equivalently structured
       array of a given data type (or of an automatically determined type if none is
       specified).

       asarray skips copying if the passed argument is already an array of the
       appropriate type.
     - .. code-block:: python

          np.array([[2, 3, 4], [5, 6, 7]], 'i')np.asarray(might_be_array, 'f')
   * - identity
     - Generate an x by x integer identity matrix for the given x.
     - .. code-block:: python

          np.identity(4)
   * - arange
     - An advanced form of the standard Python range, allowing for floating point
       ranges as well as integer ranges, generating an array as the result.
     - .. code-block:: python

          np.arange(3.0, 0.0, -0.1, 'd')

A data type can be given as a NumPy dtype, as its character code, or as a
Python type. For OpenGL work these are the ones that matter, with the GL type
each corresponds to:

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

Prefer the explicitly sized names. ``np.int_`` and plain ``int`` are
platform-width and are not the same type on every machine, so a buffer built
from one is a different buffer on the next machine. Unsigned indices
matter in particular: element-array buffers are ``np.uint16`` or
``np.uint32``, never signed.

Array dimensions are specified as tuples, in the order of indexing.  The
current shape of an array is its ``shape`` attribute.  You can use
``reshape``, ``resize``, ``transpose`` and ``ravel`` to get an array with
different dimensions — usually a view onto the same memory rather than a copy,
so writing through one changes the other. Most NumPy functions also take an
``out=`` argument naming where to put the result, which is how the inner loops
in this project avoid allocating per frame.

Basic Mathematics
~~~~~~~~~~~~~~~~~

Mathematical operators tend to work element-wise for arrays, and allow for a
fairly wide variety of second arguments.

For instance, to multiply an entire array by 3.0, you would write ``result =
myarray * 3.0`` with similar approaches for addition, subtraction, and
division.

If, instead, you wanted to multiply each element in one array by the
corresponding element in another array, you would write ``result = firstarray
* secondarray`` again, with the same approach working for most basic math
operations.

Slicing
~~~~~~~

NumPy uses an extended slicing notation, which allows for flexible and
powerful manipulation of multidimensional arrays (though at the price of
making the slice specifications somewhat less intuitive looking).

The syntax for the extended slicing notation goes like this:

[ start : stop *: step*, start : stop *: step*, ... ]

with one start, stop, step set allowed (but not required beyond the first) for
each dimension of the array. The step argument and the preceding colon can be
left off unless actually needed.  As with standard slicing notation, if you
leave off a start value, zero is assumed, and if you leave off a stop value,
the end of the array is assumed.

Generally it is easiest to understand the slicing notation through examples.
Consider this interactive session:

.. code-block:: python

   >>> m = array( [[1,2,3,4],[5,6,7,8],[9,10,11,12],[13,14,15,16]], 'd')>>> marray([[  1.,   2.,   3.,   4.],       [  5.,   6.,   7.,   8.],       [  9.,  10.,  11.,  12.],       [ 13.,  14.,  15.,  16.]])

.. code-block:: python

   # item 0 of the array in first dimension>>> m[0] array([ 1.,  2.,  3.,  4.])

.. code-block:: python

   # item 1 of the array in first dimension>>> m[1] array([ 5.,  6.,  7.,  8.])

.. code-block:: python

   # item 0 of the array in second dimension>>> m[:,0] array([  1.,   5.,   9.,  13.])

.. code-block:: python

   # item 1 of the array in second dimension>>> m[:,1] array([  2.,   6.,  10.,  14.])

.. code-block:: python

   # all items in first dimension taking every # second item>>> m[::2] array([[  1.,   2.,   3.,   4.],       [  9.,  10.,  11.,  12.]])

.. code-block:: python

   # as previous, but now take item 1 in the # second dimension for each row>>> m[::2,1] array([  2.,  10.])

.. code-block:: python

   # as previous, but starting the slice of first dimension # at the second item (i.e. take 1 and 3 instead of 0 and 2)>>> m[1::2,1] array([  6.,  14.])>>> 

Common slices you'll see include:

.. code-block:: python

   # x-coordinate of an i*3 arrayxes = points[:,0]yes = points[:,1]

.. code-block:: python

   # first points of i*3 set of points describing trianglesfirstPoints = trianglePoints[::3]secondPoints = trianglePoints[1::3]

.. code-block:: python

   # r-values of an x*y*3 r,g,b imagereds = image[:,:,0]greens = image[:,:,1]

Multiplication
~~~~~~~~~~~~~~

There are three different types of multiplication commonly used in
OpenGLContext. Element-wise multiplication was covered in Basic Mathematics
above.  The other two common multiplication types are dot product and cross
product.  NumPy provides both:

.. code-block:: python

   result = np.dot(first, second)
   result = np.cross(first, second)

``np.cross`` takes 3-item vectors, and takes whole arrays of them at once.
OpenGLContext's own ``OpenGLContext.utilities.crossProduct`` is the 4-item
homogeneous form, which is what the scenegraph's vectors are:

.. code-block:: python

   from OpenGLContext.utilities import crossProductresult = crossProduct((ux, uy, uz, uw), (vx, vy, vz, vw))

When working with arrays of vectors, use
``OpenGLContext.vectorutilities.crossProduct``, which processes the whole
array at once rather than calling a Python function per vector.

Array Processing Functions
~~~~~~~~~~~~~~~~~~~~~~~~~~

The basic manipulations above are primarily useful for selecting a particular
subset of an array for processing, while the array processing functions do the
bulk of the calculations in most algorithms.  There are far too many to list;
the groups below are the ones that come up in this project, and the `NumPy
routine reference <https://numpy.org/doc/stable/reference/routines.html>`__
describes each in full.

Universal (Math) Functions
~~~~~~~~~~~~~~~~~~~~~~~~~~

These function-like objects provide for extremely flexible application of
common mathematical operations on arguments of varying type.

``absolute, add, arccos, arcsin, arctan, arctan2, bitwise_and, bitwise_or,
bitwise_xor, ceil, conjugate, cos, cosh, divide, equal, exp, fabs, floor,
fmod, greater, greater_equal, hypot, invert, left_shift, less, less_equal,
log, log10, logical_and, logical_not, logical_or, logical_xor, maximum,
minimum, multiply, negative, not_equal, power, remainder, right_shift, sin,
sinh, sqrt, subtract, tan, tanh``

Index(ed)-Array Functions
~~~~~~~~~~~~~~~~~~~~~~~~~

These functions deal with index arrays or indexed arrays, that is, arrays
which refer to other arrays, either by having equivalent structure, or
including actual indices into the other array. These functions can provide
efficient operation by not requiring you to copy the arrays being processed. 
For an example, see OpenGLContext.scenegraph.polygonsort's use of argsort to
generate the indices required for rendering sorted transparent geometry
without needing to copying/rearranging the point array.

``argmax, argmin, argsort, choose, take, where, put, putmask, compress``

Binary Operator Functions
~~~~~~~~~~~~~~~~~~~~~~~~~

These functions deal with two "data arrays", combining their values in some
way to create a new array.  The most commonly used function of this group is
dot.

``convolve, correlate, dot, matmul, outer, inner, sum``

Array Value
~~~~~~~~~~~

These functions produce single value outputs from an entire array, checking,
for instance, that the entire array is true, or calculating the sum of the
entire array.

``all, any, cumprod, cumsum, prod, trace``

Altered Array Values
~~~~~~~~~~~~~~~~~~~~

These functions produce a copy of an array with each value modified by the
given function, or the array's ordering/contents modified as dictated by the
function's rules of operation.

``around, clip, sign, sort, compress``

The OpenGLContext Utility Modules
---------------------------------

A few operations on the scenegraph's own vector conventions are common enough
to be worth having by name. ``OpenGLContext.utilities`` works on one vector at
a time:

``rotMatrix((x, y, z, a))``
   Given a rotation as x, y, z, a (a in radians), return the rotation matrix.
``normalise(vector)``
   Given a 3- or 4-item vector, return a 3-item unit vector.
``crossProduct(first, second)``
   Given two 4-item vectors, return the cross product as a 4-item vector.
   ``np.cross`` is the 3-item form.
``magnitude(vector)``
   Given a 3- or 4-item vector, return its magnitude.

``OpenGLContext.vectorutilities`` is the same operations over a whole *array*
of vectors at once — ``crossProduct``, ``crossProduct4``, ``normalise``,
``magnitude``, ``orientToXYZR``, ``colinear``. Reach for these rather than
looping: they do the work in one array operation instead of one Python call
per vector, which is what the array package is for.

Array-based Geometry
--------------------

OpenGL 1.1 introduced a number of geometry-specification mechanisms based on
specifying pointers to arrays of data values.  The OpenGL implementation was
passed the entire array of data, then would loop through the array (normally
at hardware speed) dispatching a command for each of those values in the array
which were indicated.  The user-side code need only make a single call to have
potentially thousands of data values passed rendering pipeline.

With C code, the difference between the array-based code and individual calls
to transfer data values was noticeable, but it is still quite practical to use
the individual calls in many instances.  With Python code, however, it is
generally impractical to use individual data transfer calls, as the overhead
for the API call is enormous compared to the actual work being done with such
low level functions.

Approach
~~~~~~~~

.. rst-class:: technical

What follows is the *compatibility-profile* client-array path, which is what
the fixed-function tutorials use. A core profile has no client arrays: the
same data goes into a vertex buffer object and is described to a vertex array
object, and the array you build in NumPy is identical either way — only the
call that hands it over differs. See :doc:`Core-Profile Rendering
<renderpasses>`.

The basic approach of the array-based geometry is to specify a pointer for a
number of different array types: vertex, color, normal and textureCoordinate
(potentially multiple coordinates if using multi-texturing).

.. code-block:: python

   glVertexPointerd( self.verticies )glColorPointerd ( self.colours )glNormalPointerd ( self.normals )glTexCoordPointerd( self.textures )

This tells the OpenGL engine that these are the active arrays for each of
these types.  For all of the arrays save texture coordinates, only one active
array is possible.  Where multi-texturing is enabled (multi-texturing is an
OpenGL extension not available on all platforms), you can specify one active
texture coordinate array for each texture engine.

Once you have specified the active arrays, you enable or disable each array
type you wish to use for a given call. Note ``glEnableClientState``, not
``glEnable``: the array switches are client state, and ``glEnable`` will not
touch them.

.. code-block:: python

   glEnableClientState( GL_VERTEX_ARRAY )glEnableClientState( GL_COLOR_ARRAY )glEnableClientState( GL_NORMAL_ARRAY )glEnableClientState( GL_TEXTURE_COORD_ARRAY )

The array drawing calls such as glDrawArrays and glDrawElements are called in
place of a glBegin, glEnd construct (including the glVertex, glColor,
glNormal, glTexCoord, etc. calls that normally go between them).  The array
drawing call will specify the primitive type to draw (the same values as for
glBegin), and potentially a subset of the arrays which is to be drawn (for
instance, a start position, a count of items to draw, or a list of indices
into the arrays which are to be drawn).

.. code-block:: python

   glDrawArrays( GL_TRIANGLES, 0, 32 )glDrawElementsui( GL_TRIANGLES, indices )

Further Reading
---------------

For the current array package, see the `NumPy documentation
<https://numpy.org/doc/stable/>`__ and the `NumPy beginner's guide
<https://numpy.org/doc/stable/user/absolute_beginners.html>`__.

OpenGLContext.scenegraph.arraygeometry module for a simple implementation of
array-based geometry rendering.

OpenGLContext.vectorutilities, OpenGLContext.triangleutilities for examples of
array manipulation.

The following programs in the tests directory test array geometry
functionality (and therefore include example drawing code): gldrawarrays,
gldrawarrays_string, gldrawelements, glarrayelement, glinterleavedarrays.
