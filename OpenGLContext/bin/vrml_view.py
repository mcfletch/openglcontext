#! /usr/bin/env python
"""``oglc-vrml`` -- the former VRML97-only viewer, now an alias for ``oglc-view``.

There is one viewer, and it works out the format from the source, so the command
that opens a ``.wrl`` is the command that opens a ``.glb``.  A VRML world opened
this way gains everything that was previously only in the glTF viewer: framing,
loading in the background, camera cycling over the world's own ``Viewpoint``
nodes, a caption, screenshots, ``--capture``, and walking with gravity and
collision.  See :mod:`OpenGLContext.bin.view`.

The old ``--shaders`` / ``--no-shaders`` switches are gone: they reached into the
render pass from inside ``Redraw`` to turn on shader rendering, and the viewer
now renders through the core-profile PBR pass as a matter of course.  A world
that genuinely wants the compatibility pipeline gets it from the environment,
which is where every other renderer switch lives::

    OPENGLCONTEXT_PROFILE=compatibility oglc-view world.wrl

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
        "oglc-vrml is deprecated and will be removed; use %s instead "
        "(it opens every format, and a world gets the full viewer).\n"
        % REPLACEMENT)
    sys.stderr.flush()
    return view_main(argv, prog='oglc-vrml')


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
