Type declarations
=================

.. rst-class:: introduction

OpenGLContext ships a ``py.typed`` marker, so a type checker such as mypy or
pyright checks a project's calls into the engine. A misspelled method, a
string passed to a field that takes a number, or the wrong kind of mode passed
to a render pass is reported where it is written, before the code runs.

Turning it on
-------------

No setup is needed. The checker reads the marker from the installed package,
so a project that depends on OpenGLContext gets the declarations once the
dependency is installed:

.. code-block:: bash

   $ mypy mygame/
   mygame/level.py:88: error: "Transform" has no attribute "rotaton"  [attr-defined]
   mygame/level.py:91: error: Argument "size" to "Box" has incompatible type "str"

A project that passed its own type check against an earlier release may see
new errors. They are in calls the checker could not see into before, and the
code in question has not changed.

The node namespace
------------------

``OpenGLContext.scenegraph.basenodes`` holds every node class under the name a
scenegraph uses for it. The module fills itself from the plugin registry when
it is imported. A checker reads source without running it, so it cannot see
names created at import time. The package therefore ships ``basenodes.pyi``,
which declares them:

.. code-block:: python

   from OpenGLContext.scenegraph.basenodes import *

   sg = sceneGraph( children = [
       Transform( children = [
           Shape(
               geometry = Box( size = (1, 1, 1) ),
               appearance = Appearance( material = Material() ),
           ),
       ] ),
   ] )

Every name in this example is declared, and the star import works too: the
stub lists ``__all__`` explicitly, which a checker needs in order to expand
``import *``.

Adding a node
~~~~~~~~~~~~~

A node registered with ``OpenGLContext.plugins.Node`` in
``OpenGLContext/__init__.py`` needs an entry in the stub. A script writes the
whole stub from those registrations:

.. code-block:: bash

   python scripts/write_basenodes_stub.py            # write it
   python scripts/write_basenodes_stub.py --check    # exit non-zero if out of date

``tests/unit/test_basenodes_stub.py`` fails when the stub disagrees with the
registry, so the test suite catches a node added without regenerating the
stub. The script reads the registrations without importing the node modules,
so it runs on a machine with no GL and includes nodes whose modules cannot be
imported there.

A third party's node
~~~~~~~~~~~~~~~~~~~~

A node that an application registers from its own package is not in the stub,
so the checker types it as ``Any``. The node works the same as a built-in one;
only type checking differs. To have its own nodes checked, an application
writes a stub for its own module and imports the nodes from that module
instead of from ``basenodes``.

How the engine itself is checked
--------------------------------

The settings are in ``[tool.mypy]`` in `pyproject.toml
<https://github.com/mcfletch/openglcontext/blob/main/pyproject.toml>`__. Two of
them affect what is checked:

``check_untyped_defs = true``
   The body of a function without annotations is checked, with its parameters
   treated as ``Any``. Without this setting, mypy skips such functions
   entirely.
``warn_return_any``, off for ``OpenGLContext.physics.*``
   NumPy's stubs type array arithmetic as ``Any``, so this warning fires on
   nearly every array-returning function in the vectorised physics code and
   hides real errors. All other checks stay on for that package.

``python_version`` is set to the Python version the project is developed
against. Lowering it does not check against an older Python: NumPy's stubs use
syntax that parses only under 3.12, so mypy stops on those stubs before
checking anything.

``files`` names the package, so running ``mypy`` with no arguments in the
checkout runs the project's full check. Run it in an environment where the
stack is installed *non-editable*:

.. code-block:: bash

   tox -e typecheck

An editable install loads its package through an import hook that the checker
cannot follow. Every sibling package then resolves to ``Any``, and the run
reports thousands of ``name-defined`` errors that are unrelated to the code
being checked.

The packages underneath
-----------------------

A checker can only check an engine call as far as the packages underneath
declare their types. Each of these ships its own marker: `PyOpenGL
<https://pypi.org/project/PyOpenGL/>`__ declares the GL entry points,
`PyVRML97 <https://pypi.org/project/PyVRML97/>`__ the scenegraph model,
`PyDispatcher <https://pypi.org/project/PyDispatcher/>`__ the signal dispatch
that field changes go through, and `SimpleParse
<https://pypi.org/project/SimpleParse/>`__ the parser generator. If a package
in that chain has no marker, the checker reports no error: it treats that
package's calls as ``Any`` and checks nothing about them, and the output looks
the same as a clean run.

What is not declared
--------------------

A field on a scenegraph node is created by ``vrml.field.newField`` when the
class is defined. At run time, reading it returns the field's Python value,
not the descriptor. A checker sees the descriptor, so the type it infers for
``shape.geometry`` is the type ``newField`` declares, not the node class
stored there. Narrow the type (for example with ``isinstance``) where the
concrete class matters.

The GL entry points come from PyOpenGL. A module that uses ``from OpenGL.GL
import *`` gets only the names PyOpenGL exports explicitly. The legacy aliases,
such as ``GLerror`` for ``GLError``, exist at run time but are not exported, so
use the current spelling in new code.
