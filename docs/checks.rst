Static checks
=============

.. rst-class:: introduction

``openglcontext-checks`` is a separate package of static checks for mistakes
that reviews of the engine and the games built on it have found repeatedly: a
document's value used unchecked, a file opened at a path a document chose, a
file written in place, GL state left changed when a draw raises, a cache keyed
on ``id()``, a GL call from ``__del__``, an environment variable read at
import, a suppression with no reason, and tests that cannot fail.
Each rule has a code, ``OGC`` and three digits, and decides from a module's
syntax tree and comments, so a run over a whole application takes a fraction
of a second. It depends on nothing but the standard library, and an
application runs it the same way the engine's own projects do.

Installing and running it
-------------------------

.. code-block:: console

   $ pip install openglcontext-checks
   $ oglc-check
   src/mygame/cache.py:41:14: OGC131 id(mesh) as a key: ...

With no arguments ``oglc-check`` checks the project's configured paths; with
paths, just those. Each finding is printed as ``path:line:column: CODE
message``. ``--statistics`` prints a count per rule instead, ``--select`` and
``--ignore`` take codes or prefixes (``OGC2``), and the exit status is 0 with
no findings, 1 with findings and 2 for a configuration error or a file that
does not parse.

Results are cached per file in ``.oglc-check-cache/`` in the project root,
keyed on the file's contents, the checker's own source and the settings that
apply to it, so a second run parses only what changed. The directory carries
its own ``.gitignore``.

Configuring it for an application
---------------------------------

The settings are a table in the application's ``pyproject.toml``:

.. code-block:: toml

   [tool.openglcontext-checks]
   paths = ["src", "tests"]
   select = ["OGC131", "OGC141", "OGC161"]

   [tool.openglcontext-checks.scopes]
   script = ["src/mygame/__main__.py", "tools/*.py", "!tools/_*.py"]
   loader = ["src/mygame/levels/**"]
   pass = ["src/mygame/render/**"]

   [tool.openglcontext-checks.sanctioned]
   OGC121 = ["mygame.files.staged_file"]

``select`` defaults to every rule, and ``paths`` to the whole project less
dot-directories and build output. The rules OGC221 to OGC223 run on the
``test`` scope, which defaults to ``tests/**``, ``**/test_*.py``,
``**/*_test.py`` and ``**/conftest.py``. The ``script`` scope names the
programs run by path, whose module level is their start-up; OGC161 does not
run on them, and it is empty until the application names them. Both are set
under ``[tool.openglcontext-checks.scopes]``, where a glob with a leading
``!`` takes paths out of a scope. The ``loader`` scope is the modules that read
values and file names out of a document (OGC101, OGC102 and OGC111 run there)
and the ``pass`` scope the modules that draw (OGC151); both are empty until the
application names them. An unknown key or rule code is an error.

OGC101, OGC102, OGC111, OGC121 and OGC151 point at the engine's API for what
they report. An application with its own names it under ``sanctioned``, by
rule code and qualified name: the size checks OGC102 counts, the staging calls
under whose files OGC121 lets a write stand, and the context managers OGC151
takes as restoring state; OGC101 and OGC111 quote them in their messages. The
module that implements such an API does what the rule reports, and a
``per-file-ignores`` entry exempts it.

A project with findings already in it can start by selecting only the rules
it is clean of and add the others as it reaches zero of each; the engine's
own projects adopt the rules that way.

A single finding is suppressed with a comment on its line that names the code
and gives the reason, in the syntax ruff uses:

.. code-block:: python

   _SEEN[id(node)] = True  # noqa: OGC131 cleared with the scene, which holds every node

A ``# noqa`` without a reason does not suppress, and OGC201 reports it.

In the test suite
-----------------

Next to the engine's own plugin (see :doc:`testing`), the checks' plugin adds
one test item per selected rule to a run of the suite:

.. code-block:: toml

   [tool.pytest.ini_options]
   addopts = "-p OpenGLContext.testing.plugin -p openglcontext_checks.pytest_plugin"

Each item, ``oglc-check[OGC131]`` and so on, fails listing its rule's
findings. A run that names its own test files leaves them out unless
``--oglc-check`` is given. Installing the package without the ``-p`` option
changes nothing.

Checked types, in mypy
----------------------

The package also ships a mypy plugin. The engine's checked types --
``ContainedPath`` and ``CheckedURL`` in ``OpenGLContext.loaders.resolver``,
``ContextKey`` in ``OpenGLContext.contextresources`` -- are values whose type
says a check was made (:ref:`checked-types`). mypy on its own accepts
``ContainedPath(name)`` written anywhere; the plugin reports it.

.. code-block:: toml

   [tool.mypy]
   plugins = ["openglcontext_checks.mypy_plugin"]

   [tool.openglcontext-checks]
   checked-types = ["mygame.levels.LevelKey"]       # your own, beside the engine's
   contained-paths = ["mygame.levels.LevelPath"]    # paths a loader may open

It reports, with the error code ``checked-construction``, a checked type made
or subclassed outside the module that defines it; the engine's are reported
in every project. In a module of the ``loader`` scope it reports, with the
code ``unchecked-open``, a file opened (``open``, ``io.open``,
``PIL.Image.open``, ``numpy.load`` and the other openers OGC111 reads) at a
path whose type is not a contained path: a ``str``, ``bytes``, a
``pathlib.Path`` or a value typed ``Any``. A string literal, a ``Literal``
type, a file descriptor and an open file are accepted. Where mypy has a hook
of its own for one of these calls, it still decides the call's type.

The engine enables the plugin, so ``tools/preflight.py``'s typecheck of
``openglcontext`` runs it. mypy imports the plugin, so
``openglcontext-checks`` has to be installed where mypy runs.

The rules and what to use instead
---------------------------------

``OGC101`` -- a document's value converted with a bare ``float``, ``int`` or ``bool``, in loaders
   ``float(extras['depth'])``, ``bool(params.get('hemi'))``: a misspelt value
   aborts the load, ``1e999`` and ``nan`` pass, and ``bool('false')`` is true.
   Read it through ``OpenGLContext.loaders.documentvalues.DocumentValues``
   (``number``, ``integer``, ``flag``, ``vector``), which reports it once and
   answers the default or the nearer bound.

``OGC102`` -- a decode or allocation sized by a document before a size check, in loaders
   ``base64.b64decode``, the ``decompress`` functions, ``DracoPy.decode``, and a
   ``numpy`` array sized by a document's field, with no comparison of that size
   earlier in the function. Check it first with ``loaders.resolver.check_size``.

``OGC111`` -- a file opened at a path joined from a name nothing contained, in loaders
   ``open(os.path.join(base, species['card']))``: a name a document gives can
   lead outside its directory. Resolve it with ``loaders.resolver.Resolver`` or
   ``loaders.tiles3d.fetch.beside``.

``OGC121`` -- a file written in place
   ``open(path, 'w')``, ``Path.write_text``, ``shutil.copyfile`` and the like
   outside the test scope: a write cut short is taken for the whole file by the
   next reader. Write through ``OpenGLContext.atomicfiles`` (``write_text``,
   ``write_bytes``, ``copy_file``, ``staged_file``, ``staged_directory``), or
   beside the path followed by ``os.replace``. A stream opened to append is not
   reported.

``OGC151`` -- GL state left changed, in passes
   ``glEnable``, ``glDisable``, ``glBindFramebuffer``, ``glScissor``,
   ``glUseProgram`` or ``glCullFace`` that no ``finally`` in the same function
   restores: a draw that raises leaves the state for the next view or frame.
   Restore it in a ``finally``, or through a context manager named in
   ``sanctioned``.

``OGC131`` -- ``id()`` as a key
   ``id(x)`` as a subscript, dict or set key, ``in`` operand, ``get``/
   ``setdefault``/``pop`` key or stored attribute, where the statement does
   not also hold ``x``. An id is reused once its object is collected. Key on
   the object, with a ``WeakKeyDictionary`` where the table should not keep
   it alive; per-context tables use ``OpenGLContext.contextresources``.

``OGC141`` -- a GL call in ``__del__``
   A call into ``OpenGL.GL`` or ``OpenGL.GLES*`` from a finaliser, which runs
   on whichever thread collects the object with whatever context is current.
   Release GL objects from the owning context: a render pass through the
   disposal chain in ``OpenGLContext.passes.disposal``, a node through its
   ``dispose()``.

``OGC161`` -- configuration or I/O at import
   ``os.environ``, ``sys.argv``, ``os.getenv``, ``locale.setlocale``,
   ``open``, file-system changes, ``shutil`` and ``subprocess`` at module or
   class level. A value read at import is fixed before an application or test
   can set it. Read it on first use; the engine's own switches go through
   ``renderoptions.env_flag_once``, ``env_number_once`` and their siblings
   (see :doc:`environment`). A command whose console-script entry point imports
   the module and calls ``main()`` sets its defaults in ``main()``; a program
   run by path is named in the ``script`` scope.

``OGC201`` -- a suppression without a reason
   A ``# noqa`` or ``# type: ignore`` that names no code, or gives no reason
   after its codes.

``OGC221`` -- a skip inside an ``except``, in tests
   ``pytest.skip``, ``xfail`` or ``importorskip`` in an exception handler,
   which reports the failure it caught as a skip. For a GL context, ask for
   the fixtures in :doc:`testing`, which skip on a machine with no GL target
   before the test runs.

``OGC222`` -- a test with no assertion
   A test function with no ``assert``, ``pytest.raises`` or call named
   ``assert*``/``check*``/``expect*``/``verify*``, which passes whatever the
   code does.

``OGC223`` -- ``pass`` in a test's exception handler
   A handler inside a test whose body is only ``pass``, which lets the test
   pass whether or not the exception happened.

The package's README gives each rule's full definition with examples, and
``plans/DEFECT-PREVENTION.md`` the rules planned next.
