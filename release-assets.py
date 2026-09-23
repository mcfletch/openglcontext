#! /usr/bin/env python3
"""Build the bust gallery world, install it here, and publish it.

The level-of-detail demo's world is twelve megabytes of CC0 art, which is not
something an index should be asked to serve on every install of the engine. It
does not travel in the wheel: it is attached to a GitHub release and fetched
through :mod:`OpenGLContext.contentpacks`. One command covers the whole of that:

    ./release-assets.py                 # build the world, write the registry
    ./release-assets.py --install       # ...and put it in this machine's store
    ./release-assets.py --reinstall     # ...over whatever that store already holds
    ./release-assets.py --push          # ...and attach it to the release tag

``--install`` is what makes a content release testable before it is a release:
the demo then opens out of this machine's own store, with nothing published
and no network reached. `oglc-view` opens the archive directly either way:
naming a member with `#` unpacks it and opens that member.

**Building the world needs Blender and openglcontext-editor.** The hall is
authored and exported by the Blender add-on in
``OpenGLContext_editor/blender/openglcontext_lod``, which is how anybody else
would author one -- so what ships is what that add-on produces, not a second
path that might disagree with it. Neither is a dependency of the engine, and
neither is needed to *run* the demo; ``--world`` takes an already-built glB and
skips both.

The registry is written from the archive this built, so its digest and its size
cannot describe a file that was never made.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from OpenGLContext.contentpacks import archive, catalog, publish

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
    """Put an already-built glB and its notices where the archive is made."""
    os.makedirs(into, exist_ok=True)
    shutil.copyfile(world, os.path.join(into, MARKER))
    beside = os.path.join(os.path.dirname(os.path.abspath(world)), "CREDITS.txt")
    if os.path.exists(beside):
        shutil.copyfile(beside, os.path.join(into, "CREDITS.txt"))
    return into


def build(where: str, name: str, into: str) -> tuple[str, int, str]:
    """Archive ``where`` as ``name``; return its path, size and digest."""
    path = archive.write(where, os.path.join(into, f"{name}.tar.gz"))
    return path, os.path.getsize(path), archive.digest(path)


def credits() -> str:
    """Whose the art is, in the one line a consent screen has room for."""
    return ("'Marble Bust 01' by Rico Cilliers from Poly Haven, and the floor, "
            "wall, ceiling and beam materials from ambientCG -- all CC0 1.0 "
            "(public domain). Full attribution in CREDITS.txt inside the pack.")


def entry(tag: str, path: str, size: int, sha: str) -> dict:
    """What the registry says about the world this built."""
    return {
        "key": f"{NAMESPACE}/gallery",
        "title": "Bust gallery demo world",
        "url": URL % (tag, os.path.basename(path)),
        "directory": "gallery",
        "archive": "tar",
        "approximate_bytes": size,
        "sha256": sha,
        "base": False,
        "copyright": credits(),
        "marker": MARKER,
        "notes": "A hall of 120 marble busts on "
                 "plinths, each a six-level MSFT_lod chain, with a polished "
                 "parquet floor and dark beams overhead. An ordinary glTF "
                 "file -- a viewer that does not know the extension draws "
                 "every bust at its finest level.",
    }


def install(into: str, replace: bool = False) -> int:
    """Put what was built into the store the demo reads, and say where.

    ``replace`` throws away what is installed under each key first, which is
    what a second build of a world wants: the store holds the last one, and an
    install that leaves it there shows the world before the change.
    """
    from OpenGLContext.contentpacks import ContentStore

    store = ContentStore(NAMESPACE)
    packs = catalog.merge(catalog.load(CATALOG))
    print(f"store: {store.root}")
    for pack in packs:
        where = publish.install(pack, store, into, replace=replace)
        print(f"  {pack.key:<28} {os.path.relpath(where, store.root)}")
    return 0


def push(tag: str, paths: list[str]) -> int:
    """Attach the built archives to the release the registry names."""
    publish.push(publish.repository(URL % (tag, "x")), tag, paths,
                 title=f"Bust gallery world {tag}",
                 notes="The level-of-detail demo world. Open it with "
                       "`oglc-view <url>#gallery.glb`. "
                       "Terms are in the registry and in CREDITS.txt inside "
                       "the pack.")
    print(f"attached {len(paths)} file(s) to {tag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tag", default="content-v1",
                        help="the release tag the artefact is attached to "
                             "(default: %(default)s)")
    parser.add_argument("--into", default=os.path.join(HERE, "dist", "content"),
                        help="where to write the archive")
    parser.add_argument("--world", default=None,
                        help="pack this glB instead of building one, which "
                             "needs neither Blender nor openglcontext-editor")
    parser.add_argument("--bays", type=int, default=30,
                        help="plinths down the hall (default: %(default)s)")
    parser.add_argument("--levels", type=int, default=6,
                        help="levels per bust (default: %(default)s)")
    parser.add_argument("--install", action="store_true",
                        help="install what was built into this machine's own "
                             "store, so the demo runs against it with nothing "
                             "published")
    parser.add_argument("--reinstall", action="store_true",
                        help="install, throwing away what is already in the "
                             "store under this key first, which is what a "
                             "rebuilt world needs to be the one that opens")
    parser.add_argument("--push", action="store_true",
                        help="attach the archives to the release at --tag, "
                             "creating it if it is not there yet (needs the "
                             "GitHub CLI, and an account that may write here)")
    options = parser.parse_args(argv)

    staged = os.path.join(options.into, "gallery")
    os.makedirs(staged, exist_ok=True)
    if options.world:
        if not os.path.exists(options.world):
            print(f"no world at {options.world}", file=sys.stderr)
            return 2
        stage(options.world, staged)
    else:
        build_world(staged, options.bays, options.levels)

    path, size, sha = build(staged, "gallery-world", options.into)
    declared = entry(options.tag, path, size, sha)
    with open(CATALOG, "w", encoding="utf-8") as handle:
        json.dump({"namespace": NAMESPACE, "packs": [declared]}, handle,
                  indent=1)
        handle.write("\n")
    print(f"gallery world: {size / 1048576:.1f} MB, sha256 {sha[:12]}, "
          f"registry written to {os.path.relpath(CATALOG, HERE)}")

    if options.install or options.reinstall:
        install(options.into, replace=options.reinstall)
    if options.push:
        return push(options.tag, [path])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
