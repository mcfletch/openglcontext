#!/bin/bash
# Regenerate the generated parts of the docs/ site, then leave them for you to
# review, commit and push. GitHub Pages publishes the committed docs/ directory
# (see .github/workflows/pages.yml), so run this BEFORE you push whenever the
# tutorials' source (tests/*.py) or the renderer has changed.
#
# Two things are generated:
#   1. The code-walkthrough tutorials, extracted from the triple-quoted
#      commentary in tests/*.py by the 'directdocs' tool (oglctutorials).
#   2. The rendered screenshots in docs/images/, by generate_doc_images.py.
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

echo
echo "Done. Review docs/, then commit and push; GitHub Pages will deploy docs/."
