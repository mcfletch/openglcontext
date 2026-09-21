Type declarations
=================

.. rst-class:: introduction

OpenGLContext ships a ``py.typed`` marker, so a project built on the engine
has its calls into the engine checked. A misspelled method, a field given a
string where it takes a number, a render pass handed the wrong kind of mode —
all of these are reported where they are written rather than at the frame that
runs them.

Turning it on
-------------

Nothing to turn on. A checker reads the marker from the installed package, so
mypy or pyright in a project that depends on OpenGLContext picks the
declarations up as soon as the dependency is installed:

.. code-block:: bash

   $ mypy mygame/
   mygame/level.py:88: error: "Transform" has no attribute "rotaton"  [attr-defined]
   mygame/level.py:91: error: Argument "size" to "Box" has incompatible type "str"

A project that was already passing its own typecheck may start reporting
errors the first time it picks up a release that carries the marker. Those are
calls that were never checked before, not new mistakes.

The node namespace
------------------

``OpenGLContext.scenegraph.basenodes`` is where every node class lives under
the name a scenegraph uses for it, and it fills itself from the plugin
registry as it loads. Names created at import time are invisible to a checker,
which reads source rather than running it, so the package ships
``basenodes.pyi`` declaring them:

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

Every one of those names is declared, and so is the star import: the stub
spells out ``__all__``, which is the only form a checker can expand ``import
*`` against.

Adding a node
~~~~~~~~~~~~~

A node registered with ``OpenGLContext.plugins.Node`` in
``OpenGLContext/__init__.py`` needs a line in the stub, and the script writes
the whole file from those registrations:

.. code-block:: bash

   python scripts/write_basenodes_stub.py            # write it
   python scripts/write_basenodes_stub.py --check    # exit non-zero if out of date

``tests/unit/test_basenodes_stub.py`` fails while the file on disk disagrees
with the registry, so a node added without regenerating is caught by the
suite. The generator reads the registrations without importing them, so it
runs on a machine with no GL and covers a node whose implementation module
will not import there.

A third party's node
~~~~~~~~~~~~~~~~~~~~

A node an application registers from its own package is not in the stub and
resolves as ``Any`` — a checker has no declaration for a class it was never
shown. The node works exactly as a built-in one does; only the checking of it
differs. An application wanting its own nodes declared can write a stub for
its own module and reach them through it rather than through ``basenodes``.

What the engine is checked under
--------------------------------

The settings are in ``[tool.mypy]`` in `pyproject.toml
<https://github.com/mcfletch/openglcontext/blob/main/pyproject.toml>`__. Two
are worth knowing about:

``check_untyped_defs = true``
   The body of a function with no annotations is checked, with its parameters
   taken as ``Any``. Without this a checker skips such a function entirely, which
   is where most of a long-lived codebase's unchecked lines sit.
``warn_return_any``, off for ``OpenGLContext.physics.*``
   numpy's own stubs type array arithmetic as ``Any``, so the warning fires on
   nearly every array-returning function in the vectorised physics core and
   buries the genuine reports. Every other check stays on there.

The version pinned as ``python_version`` matches the interpreter the project
is developed against. It is not a way to check an older Python: numpy's
shipped stubs use syntax that parses only under 3.12, so a lower value aborts
on those stubs before checking anything at all.

``files`` names the package, so ``mypy`` with no arguments in the checkout
runs the same check the project holds itself to. Run it against an environment
with the stack installed *non-editable*:

.. code-block:: bash

   tox -e typecheck

An editable install reaches its package through an import hook a checker
cannot follow, so every sibling resolves to ``Any`` in such an environment and
the run reports thousands of ``name-defined`` errors that say nothing about
this code.

The stack below
---------------

What a checker can say about an engine call is limited by what the packages
under it declare, and each of those ships its own marker: `PyOpenGL
<https://pypi.org/project/PyOpenGL/>`__ declares the GL entry points,
`PyVRML97 <https://pypi.org/project/PyVRML97/>`__ the scenegraph model,
`PyDispatcher <https://pypi.org/project/PyDispatcher/>`__ the observer
mechanism every field change travels through, and `SimpleParse
<https://pypi.org/project/SimpleParse/>`__ the parser generator. A package in
that chain without a marker is not an error — a checker reads its calls as
``Any`` and reports nothing about them, which looks the same as a clean run.

What is not declared
--------------------

A field on a scenegraph node is created by ``vrml.field.newField`` at
class-definition time, and reads back as the field's Python type rather than
as the descriptor. A checker follows the descriptor, so the type it infers for
``shape.geometry`` is the declaration ``newField`` carries rather than the
node class stored there; narrow it where the concrete class matters.

The GL entry points come from PyOpenGL, and a module written ``from OpenGL.GL
import *`` gets only the names PyOpenGL exports explicitly. The legacy aliases
— ``GLerror`` for ``GLError`` and its kin — exist at run time but are not
among them, so new code should use the modern spelling.
