#! /usr/bin/env python3
"""Build the bust gallery world, install it here, and publish it.

The level-of-detail demo's world is twelve megabytes of CC0 art, which is not
something an index should be asked to serve on every install of the engine. It
does not travel in the wheel: it is attached to a GitHub release and fetched
through :mod:`OpenGLContext.contentpacks`. One command covers the whole of that:

    ./release-assets.py                 # build the world and its registry
    ./release-assets.py --install       # ...and put it in this machine's store
    ./release-assets.py --reinstall     # ...replacing the copy installed there
    ./release-assets.py --push          # ...attach it to the release tag and
                                        #    write OpenGLContext/packs.json

``--install`` is what makes a content release testable before it is a release:
``oglc-view --pack openglcontext/gallery`` then opens it out of this machine's
own store, with nothing published and no network reached. ``oglc-view`` also
opens the archive directly: naming a member with ``#`` unpacks it and opens
that member.

**Building the world needs Blender and openglcontext-editor.** The hall is
authored and exported by the Blender add-on in
``OpenGLContext_editor/blender/openglcontext_lod``, which is how anybody else
would author one -- so what ships is what that add-on produces, not a second
path that might disagree with it. Neither is a dependency of the engine, and
neither is needed to *run* the demo; ``--world`` takes an already-built glB and
skips both.

The registry is written from the archive this built, so its digest and its size
cannot describe a file that was never made. It is written beside the archive;
the one the package ships is rewritten only by ``--push`` or
``--write-registry``. The options, the install and the push are
:func:`OpenGLContext.contentpacks.publish.main`'s.
"""

from __future__ import annotations

import argparse
import os
import shutil

from OpenGLContext.contentpacks import publish

#: Where a release's artefacts are fetched from.
URL = "https://github.com/mcfletch/openglcontext/releases/download/%s/%s"

#: The namespace the engine's own packs sit under.
NAMESPACE = "openglcontext"

#: What proves the pack is unpacked: the world itself.
MARKER = "gallery.glb"

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(HERE, "OpenGLContext", "packs.json")


def build_world(into: str, bays: int, levels: int) -> str:
    """Author and export the gallery in Blender; return the directory.

    Through ``openglcontext-editor``'s own command, so the world in the pack is
    the world its add-on makes.
    """
    try:
        from OpenGLContext_editor import blender
        from OpenGLContext_editor.bin import gallery as build
    except ImportError as error:
        raise SystemExit(
            "building the world needs openglcontext-editor installed (%s). "
            "Pass --world to pack a glB you already have." % (error,)
        ) from error
    try:
        print("blender: %s" % (blender.version(),))
    except blender.BlenderMissing as error:
        raise SystemExit("%s. Pass --world to pack a glB you already have."
                         % (error,)) from error
    content = build.assemble()
    print("content: %s" % (content,))
    world = os.path.join(into, "gallery.glb")
    build.build(content, world, bays=bays, levels=levels)
    shutil.copyfile(os.path.join(content, "CREDITS.txt"),
                    os.path.join(into, "CREDITS.txt"))
    return into


def stage(world: str, into: str) -> str:
    """Put an already-built glB and its notices where the archive is made.

    The registry entry says the full attribution is in ``CREDITS.txt`` inside
    the pack, so a glB without one beside it is refused.
    """
    beside = os.path.join(os.path.dirname(os.path.abspath(world)), "CREDITS.txt")
    if not os.path.exists(beside):
        raise SystemExit("no CREDITS.txt beside %s; the pack carries the art's "
                         "attribution, so put it there" % (world,))
    shutil.copyfile(world, os.path.join(into, MARKER))
    shutil.copyfile(beside, os.path.join(into, "CREDITS.txt"))
    return into


def credits() -> str:
    """Whose the art is, in the one line a consent screen has room for."""
    return ("'Marble Bust 01' by Rico Cilliers from Poly Haven, and the floor, "
            "wall, ceiling and beam materials from ambientCG -- all CC0 1.0 "
            "(public domain). Full attribution in CREDITS.txt inside the pack.")


def declare(build: publish.Build) -> list[dict]:
    """Build the gallery pack; what the registry says about it."""
    options = build.options
    staged = build.staging("gallery")
    if options.world:
        if not os.path.exists(options.world):
            raise SystemExit(f"no world at {options.world}")
        stage(options.world, staged)
    else:
        build_world(staged, options.bays, options.levels)
    built = build.archive(staged, "gallery-world")
    return [build.entry(
        "gallery", built, title="Bust gallery demo world",
        copyright=credits(), marker=MARKER,
        notes="A hall of 120 marble busts on plinths, each a six-level "
              "MSFT_lod chain, with a polished parquet floor and dark beams "
              "overhead. An ordinary glTF file -- a viewer that does not know "
              "the extension draws every bust at its finest level.")]


def arguments(parser: argparse.ArgumentParser) -> None:
    """The options that say how the world is built."""
    parser.add_argument("--world", default=None,
                        help="pack this glB instead of building one, which "
                             "needs neither Blender nor openglcontext-editor")
    parser.add_argument("--bays", type=int, default=30,
                        help="plinths down the hall (default: %(default)s)")
    parser.add_argument("--levels", type=int, default=6,
                        help="levels per bust (default: %(default)s)")


def release() -> publish.Release:
    """What this command publishes."""
    return publish.Release(
        namespace=NAMESPACE, url=URL, catalog=CATALOG, declare=declare,
        into=os.path.join(HERE, "dist", "content"), arguments=arguments,
        description=__doc__.split("\n\n")[0],
        title="Bust gallery world",
        notes="The level-of-detail demo world. Open it with "
              "`oglc-view --pack openglcontext/gallery`. Terms are in the "
              "registry and in CREDITS.txt inside the pack.")


def main(argv: list[str] | None = None) -> int:
    return publish.main(release(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
