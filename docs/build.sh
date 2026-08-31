#!/bin/bash
# Regenerate the generated parts of the docs/ site, then leave them for you to
# review, commit and push. GitHub Pages publishes the committed docs/ directory
# (see .github/workflows/pages.yml), so run this BEFORE you push whenever the
# tutorials' source (tests/*.py) or the renderer has changed.
#
# Three things are generated:
#   1. The code-walkthrough tutorials, extracted from the triple-quoted
#      commentary in tests/*.py by the 'directdocs' tool (oglctutorials).
#   2. The rendered screenshots in docs/images/, by generate_doc_images.py.
#   3. The pictures docs/images/manifest.toml declares, and the gallery blocks
#      that show them, by the workspace's tools/doc_images.py.  Several of those
#      come from projects beside this one -- a lap of glisteel, a walk through
#      the forest demo, a board from the marble demo -- so it runs only in a
#      checkout of the development workspace, and each picture whose source is
#      absent is skipped with the committed one left alone.
#
# Requirements:
#   - Tutorials: the 'directdocs' package, which lives in the sibling pyopengl
#     checkout, and the 'genshi' package.  DIRECTDOCS names the directory the
#     package is imported from, so it is the checkout root rather than the
#     package itself.
#   - Screenshots: a GL display, or an offscreen platform (PYOPENGL_PLATFORM=egl).
#     The Parthenon gallery also needs the sibling 'parthenon' model; it is
#     skipped if absent.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

# 1. Tutorials (the "demo documentation extraction"): must run before publishing
DIRECTDOCS="${DIRECTDOCS:-$REPO/../pyopengl}"
echo "== Extracting tutorials from tests/*.py -> docs/tutorials/ =="
if [ -d "$DIRECTDOCS/directdocs" ]; then
    ( cd "$DIRECTDOCS" && python -m directdocs.oglctutorials ) \
        && echo "  tutorials regenerated" \
        || echo "  WARNING: tutorial extraction failed (is 'genshi' installed?)"
else
    echo "  SKIP: no directdocs package under $DIRECTDOCS (set DIRECTDOCS=/path)"
fi

# 2. Screenshots
echo "== Rendering doc screenshots -> docs/images/ =="
python scripts/generate_doc_images.py "$@" \
    || echo "  WARNING: image generation failed (needs a GL display / EGL)"

# 3. The declared pictures and the galleries that show them
WORKSPACE="$(cd "$REPO/.." && pwd)"
echo "== Rendering declared pictures -> docs/images/ (workspace tool) =="
if [ -f "$WORKSPACE/tools/doc_images.py" ]; then
    ( cd "$WORKSPACE" && python tools/doc_images.py ) \
        || echo "  WARNING: doc_images.py failed"
else
    # A standalone clone has no siblings to photograph; the committed pictures
    # stay as they are, and the gallery blocks in the pages with them.
    echo "  SKIP: not in a workspace checkout ($WORKSPACE/tools/doc_images.py)"
fi

echo
echo "Done. Review docs/, then commit and push; GitHub Pages will deploy docs/."
