#!/bin/bash
# Render the pictures the documentation shows, and leave them for you to review
# and commit.  They are committed rather than built with the site: drawing them
# needs a GPU, and several come from projects that sit beside this one.
#
# The site itself is `python build-docs.py` at the top of the checkout, which
# writes the tutorials and the module pages and runs Sphinx over everything.
#
# Two things are rendered here:
#   1. The screenshots in docs/images/, by scripts/generate_doc_images.py.
#   2. The pictures docs/images/manifest.toml declares, by the workspace's
#      tools/doc_images.py.  Several of those come from projects beside this
#      one -- a lap of glisteel, a walk through the forest demo, a board from
#      the marble demo -- so it runs only in a checkout of the development
#      workspace, and each picture whose source is absent is skipped with the
#      committed one left alone.
#
# Both need a GL display, or an offscreen platform (PYOPENGL_PLATFORM=egl).
# The Parthenon gallery also needs the sibling 'parthenon' model; it is
# skipped if absent.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

# 1. Screenshots
echo "== Rendering doc screenshots -> docs/images/ =="
python scripts/generate_doc_images.py "$@" \
    || echo "  WARNING: image generation failed (needs a GL display / EGL)"

# 2. The declared pictures
WORKSPACE="$(cd "$REPO/.." && pwd)"
echo "== Rendering declared pictures -> docs/images/ (workspace tool) =="
if [ -f "$WORKSPACE/tools/doc_images.py" ]; then
    ( cd "$WORKSPACE" && python tools/doc_images.py ) \
        || echo "  WARNING: doc_images.py failed"
else
    # A standalone clone has no siblings to photograph; the committed pictures
    # stay as they are.
    echo "  SKIP: not in a workspace checkout ($WORKSPACE/tools/doc_images.py)"
fi

echo
echo "Done.  Review docs/images/, commit what changed, then build the site:"
echo "    python build-docs.py"
