#!/bin/bash
# Deprecated. The docs are no longer rsynced to SourceForge.
#
# Publishing is now via GitHub Pages: pushing changes under docs/ to the main
# branch triggers ../.github/workflows/pages.yml, which deploys the docs/
# directory. Before pushing, regenerate the tutorials and screenshots with:
#     bash docs/build.sh
echo "docs/upload.sh is deprecated; publishing is via GitHub Pages."
echo "Run 'bash docs/build.sh', then commit and push to deploy."
