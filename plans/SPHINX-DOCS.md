# The documentation set, in Sphinx

**Status: landed.** The pages are reStructuredText, the tutorials and the
module pages are generated, and `build-docs.py` builds and publishes the whole
thing.

## What the set is

Three parts, built together:

| Part | Where it comes from | In version control |
|------|--------------------|--------------------|
| The narrative pages | `docs/*.rst`, written by hand | yes |
| The tutorials | `docbuild/tutorials.py`, from the `'''` commentary in `tests/*.py` | no (`docs/tutorials/*.rst`) |
| The module pages | PyOpenGL's `directdocs/dumbpydoc.py`, from the installed packages | no (`docs/api/`) |

`python build-docs.py` writes the two generated halves and runs Sphinx over all
three, leaving the site in `docs/_build/html`. `--stage DIR` puts a copy
somewhere to look at; `--publish` replaces `gh-pages` with it as a single
parentless commit, and `--push` sends that to the remote against a lease.
`.github/workflows/documentation.yml` does it on a push to `main`.

## The module pages cover the whole stack

One doctree for the engine and everything around it, so a name is one page
away wherever it is declared:

    OpenGLContext  OpenGLContext_editor  OpenGLContext_qt  vrml
    omi_audio  omi_physics  opengl_decimate  opengl_extrusions  pyopengl_video

PyOpenGL, TTFQuery and SimpleParse have sets of their own and are linked into
rather than restated: `intersphinx_mapping` in `docs/conf.py` names them, and
`build-docs.py --intersphinx` turns the lookups on (off by default, since they
need the network).

Every module is imported to be documented, so a module whose optional
dependency is absent gets no page — wxPython's four contexts, the two Windows
font modules, the three Blender add-on modules — and the build says which. A
release build wants a machine that has them.

The generator is PyOpenGL's, and lives in the PyOpenGL *repository* rather than
in the PyOpenGL distribution: `DIRECTDOCS=../pyopengl`, `--directdocs DIR`, or a
checkout beside this one. What is specific to this project — the commentary
notation the tutorials are written in, and the tutorial paths — is `docbuild/`
here.

## What moved, and what the URLs do

Every page keeps its name: `docs/pbr.html` was published at
`…/openglcontext/pbr.html` and the built `pbr.rst` is published at the same
address. The sections of a page keep their anchors where the `id` was unique
across the set; the few that were not (`#demo` appeared on eight pages) are
prefixed with the page name.

The old site was the committed `docs/` directory, served from `main`. The built
site is now on `gh-pages`, which is what GitHub Pages serves, so the repository
carries one copy of a large generated site rather than one per release.

## Pictures

`docs/images/` is unchanged, and `tools/doc_images.py` in the workspace still
renders what `docs/images/manifest.toml` declares. The galleries that manifest
declares are no longer written into the pages: `docs/_ext/oglc_gallery.py` adds
a `gallery` directive that reads the manifest as Sphinx builds the page, so the
slides cannot go stale against what is declared. The drawn diagrams that were
inline SVG in four pages are files under `docs/images/diagrams/`.
