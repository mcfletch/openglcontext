#! /bin/sh
# Build a .deb of the Tk viewer demo, carrying its own Python.
#
#     OpenGLContext/demos/packaging/build-deb.sh
#     OpenGLContext/demos/packaging/build-deb.sh -r requirements-stack.txt
#
# Nothing outside the package is needed to run it: no system Python, no virtual
# environment for the user to make, no pip at install time.  It installs under
# /opt/openglcontext-viewer-demo, links the command into /usr/bin and adds a
# desktop menu entry.  Anything given on the command line is passed through to
# oglc-deb, which is where `-r` for an unreleased stack goes.
#
# The three things that are not obvious:
#
#   --backend tk   Tk is part of CPython, and `oglc-deb` strips what an
#                  application cannot reach out of the interpreter it ships.
#                  Without this the package installs and then fails to start.
#   --menu         which command the menu entry runs.  The default is the one
#                  named after the package, and this package's command is not,
#                  so without this it would install with no entry at all.
#   --bindir       /usr/games and the Game menu category are the defaults, this
#   --categories   being an engine for games; a viewer is a graphics tool.
#
# See `docs/packaging.html`, and `viewer-demos.spec` beside this for the frozen
# bundle, which is the same application delivered the other way.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
runtime=${RUNTIME:-build/runtime}
output=${OUTPUT:-dist}
version=${PYTHON_VERSION:-3.12}

# A relocatable CPython -- one that finds its standard library beside itself
# rather than at a path compiled into it -- which is what lets the environment
# be built here by an ordinary user and run from /opt.
if [ ! -d "$runtime" ]; then
    uv python install --install-dir "$runtime" "$version"
fi

exec oglc-deb \
    --project "$here/deb-project" \
    --runtime "$runtime" \
    --backend tk \
    --command oglc-tk-viewer \
    --menu oglc-tk-viewer \
    --menu-name 'OpenGLContext viewer (Tk)' \
    --section graphics \
    --categories 'Graphics;3DGraphics;Viewer;' \
    --bindir /usr/bin \
    --output "$output" \
    "$@"
