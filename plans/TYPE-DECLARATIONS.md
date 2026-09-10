# Type declarations across the engine

**Status: landed.** The engine is checked with `check_untyped_defs`, ships
`py.typed` and a generated stub for the node namespace, and the seven projects
built on it now have their calls into the engine checked.

## What this was for

Two gaps, both invisible from inside the project.

**Bodies nothing checked.** mypy does not look inside a function with no
annotations. 30% of the engine's ~5000 definitions had none, so their bodies
were never read by the checker at all — and a long-lived codebase's oldest,
least-exercised code is exactly where those functions are. Turning
`check_untyped_defs = true` on took the count from 148 errors to 692.

**A surface nothing could see.** OpenGLContext shipped no `py.typed`, so every
downstream project resolved the whole engine as `Any`. Their green typecheck
gates were checking nothing that crossed into it. A probe of seven deliberately
wrong calls — a misspelled field, a method that does not exist, a node that does
not exist, wrong arity, an unknown module attribute — passed silently under
every one of the seven projects' own configurations.

## What landed

### The checker reads every body

`check_untyped_defs = true` in `[tool.mypy]`.

### The engine is annotated

Every function and method definition carries annotations, and
`disallow_untyped_defs = true` holds new code to it.

### `py.typed`, and a stub for the node namespace

`OpenGLContext/scenegraph/basenodes` fills its namespace from the plugin
registry as it loads, so its 107 node names exist only at run time — and
`from ...basenodes import *` is how the engine and most callers reach them.
`basenodes.pyi` declares them, and `scripts/write_basenodes_stub.py` writes it
from the `Node( 'Name', 'module.Class' )` registrations in
`OpenGLContext/__init__.py`.

The generator reads those registrations without importing, so it runs on a
machine with no GL and covers a node whose implementation module will not
import there. It unrolls the `for suffix in (...)` loop that registers the
shader uniform families, and declares each of those as the subclass it is,
since they are built with `type()` and have no class to import.
`tests/unit/test_basenodes_stub.py` holds the file to the registry.

`__all__` is spelled out as a literal rather than declared as a bare
`List[str]`: a checker can only expand a star import against a literal, and
without that the stub declared 107 names that `import *` still could not reach.

Both `py.typed` and `scenegraph/*.pyi` are declared as package data, and
`tests/unit/test_packaging_metadata.py` builds a wheel and looks inside it —
a pattern that matches a file in the checkout can still miss the distribution.

### Python 2 is gone

`tests/unit/test_code_health_py2.py` guards sixteen spellings at source level.
Some of them raise the moment their line runs; the quiet one is worse — Python 3
never calls `__getslice__`, so a class defining one to keep its own type across
a slice hands back a plain list instead, losing every method on it.

## Defects this found

Turning the check on and annotating behind it surfaced real bugs, each fixed
with a failing test first. See `git log` for the full set; the shapes worth
remembering, because they recur:

- **`min`, `max`, `any`, `all`, `sum` are numpy's** in any module doing
  `from OpenGLContext.arrays import *`, and their second positional argument is
  `axis`. `min(c, 1.0)` raises `TypeError` — it does not clamp.
- **A local shadowing a builtin that is then called.** `Context.fromConfig`
  held the config's context flavour in a local named `type`, then called `type`
  to build the class.
- **A numpy call with the wrong keyword or a stray positional.**
  `identity((4,4), type='f')` (it takes a side length and `dtype`);
  `less(a, b, 0)` (the third positional is an output array).
- **Truth-testing an array.** `if direction:` on a 3-vector raises.
- **An index used one past the slice just taken.**
- **A loop over a preference list that overwrites instead of breaking**, so the
  *last* entry won where the specification says the first should.
- **A name that resolves only by accident**, leaked into the module by a star
  import from a third party that happens not to restrict `__all__`.

## What is still `Any`

A field on a scenegraph node is a `vrml.field.newField` descriptor, and reads
back as the field's Python type rather than as the node class stored there. A
checker follows the descriptor, so `shape.geometry` is as wide as the field's
declaration; narrow it where the concrete class matters. Making the descriptors
generic in pyvrml97 would close this, and is not done.

A node an application registers from its own package is not in the stub and
resolves as `Any`. It works exactly as a built-in one does; only the checking
differs.

## Reference

User documentation: [docs/typing.html](../docs/typing.html).
