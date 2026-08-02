#! /usr/bin/env python
"""``oglc-gltf`` -- the former glTF-only viewer, now an alias for ``oglc-view``.

There is one viewer, and it works out the format from the source, so the command
that opens a ``.glb`` is the command that opens a ``.wrl``.  Every option this
command took is still accepted, unchanged; see :mod:`OpenGLContext.bin.view`.

This name is kept for one release cycle so existing scripts and documentation
keep working, and prints where to go instead.  It will then be removed.
"""
import sys
from typing import Any, Optional

from OpenGLContext.bin.view import main as view_main

#: What to type now.  Named here so the notice and the replacement cannot drift.
REPLACEMENT = 'oglc-view'


def main(argv: Optional[list] = None) -> Any:
    """Run ``oglc-view``, having said that is what this now is."""
    sys.stderr.write(
        "oglc-gltf is deprecated and will be removed; use %s instead "
        "(same options, and it opens every format).\n" % REPLACEMENT)
    sys.stderr.flush()
    return view_main(argv, prog='oglc-gltf')


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
