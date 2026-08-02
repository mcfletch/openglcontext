#! /usr/bin/env python
"""``oglc-tiles`` -- the former 3D-Tiles-only viewer, now an alias for ``oglc-view``.

There is one viewer, and it works out the format from the source, so the command
that opens a ``tileset.json`` is the command that opens a ``.glb``.  A dataset
under some other name is recognised by its content -- any JSON carrying both
``asset`` and ``root`` -- and the streaming knobs this command had are still
here: ``--sse``, ``--memory``, ``--no-recenter`` and ``--cache-dir``.  See
:mod:`OpenGLContext.bin.view`.

Opened this way a dataset gains everything that was previously only in the glTF
viewer: framing from its root bounding volume, loading in the background, a
caption, screenshots, the settled ``--capture``, the library, the settings and
controls screens, and walking it with gravity and collision.

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
        "oglc-tiles is deprecated and will be removed; use %s instead "
        "(it opens every format, and a dataset gets the full viewer).\n"
        % REPLACEMENT)
    sys.stderr.flush()
    return view_main(argv, prog='oglc-tiles')


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
