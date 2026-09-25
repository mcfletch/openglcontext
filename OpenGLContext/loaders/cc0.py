"""Fetch and cache CC0 PBR textures from ambientCG for the terrain/forest.

ambientCG (https://ambientcg.com) publishes public-domain (CC0) photographic PBR
materials — bark, ground, rock, grass, forest floor — each a set of Color / Normal /
Roughness / AO maps. This downloads a named material once, caches the extracted maps
under the per-user app-data directory, and returns local file paths. Everything is
CC0, so it can be redistributed; a manifest records provenance.

Offline or on failure the caller falls back to the procedural textures in
`tiles3d/foliage.py`; nothing here is required for the engine to run.

Both the download and the archive it expands are bounded. An archive is
compressed, so the bytes that arrive do not limit what extracting them writes:
:data:`MAX_ARCHIVE_BYTES` caps the download and :data:`MAX_MEMBER_BYTES` caps each
map taken out of it.
"""
import io
import os
import ssl
import urllib.request
import zipfile
from typing import Optional

from OpenGLContext import userpaths
from OpenGLContext.loaders import resolver
from OpenGLContext.loaders.documentvalues import (
    parse_object, require_array, require_object, require_text,
)

_UA = {"User-Agent": resolver.user_agent()}
_CTX = ssl.create_default_context()
_API = "https://ambientcg.com/api/v2/full_json?id=%s&type=Material&include=downloadData"

#: Ceiling on one downloaded material archive. A 1K four-map set is a few MB.
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024      # 256 MiB

#: Ceiling on one map extracted from an archive, applied before it is written.
MAX_MEMBER_BYTES = 64 * 1024 * 1024        # 64 MiB

#: Ceiling on the library's JSON answer, which is read into memory before it is
#: parsed. A description of one material is a few kilobytes.
MAX_API_BYTES = 8 * 1024 * 1024            # 8 MiB

#: Where an ambientCG archive may be fetched from. The API answers with the
#: link, and an answer is not permission to fetch from anywhere.
DOWNLOAD_HOSTS = ('ambientcg.com', 'acg-download.struffelproductions.com')

# Curated CC0 materials (ambientCG asset ids) for a coniferous-forest floor + trunks.
CATALOG = {
    "bark": "Bark012",
    "ground": "Ground037",       # dark forest earth
    "dirt": "Ground068",
    "rock": "Rock030",
    "grass": "Grass004",
    "forest_floor": "Ground042",  # needles / leaf litter
    "moss": "Ground038",
}


def cache_dir() -> str:
    """Where extracted maps are kept, per user rather than in shared temp.

    The same location the rest of OpenGLContext uses for downloaded assets, so no
    other account can pre-seed a texture this user then loads.
    """
    d = os.path.join(userpaths.appdatadirectory(), "OpenGLContext", "cc0")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _read_capped(url: str, max_bytes: int) -> bytes:
    """Read a URL, refusing a body over ``max_bytes`` as it arrives."""
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=60, context=_CTX) as response:
        return resolver.stream_capped(response, max_bytes)


def _require_download_host(link: str) -> str:
    """``link``, unless it is somewhere ambientCG does not publish from.

    The library is asked where an archive is and answers with a URL. That
    answer is data: a service that is compromised, misconfigured or simply
    wrong can name a local address, a plaintext link or a ``file://`` path, and
    a client that fetches whatever it is told has handed over the decision. The
    hosts are a fact about the provider, so they are stated here rather than
    taken from the reply.
    """
    return resolver.require_host(link, DOWNLOAD_HOSTS)


def _api_download_link(asset: str, resolution: str) -> str:
    """The JPG download URL ambientCG offers for ``asset`` at ``resolution``."""
    data = parse_object(_read_capped(_API % asset, MAX_API_BYTES), 'the ambientCG reply')
    found = require_array(data.get("foundAssets"), "the ambientCG assets")
    if not found:
        raise RuntimeError("ambientCG has no asset %s" % (asset,))
    folders: object = require_object(found[0], "the ambientCG asset")
    for key in ("downloadFolders", "default", "downloadFiletypeCategories"):
        folders = require_object(folders, "the ambientCG %s" % (key,)).get(key)
    for cat in require_object(folders, "the ambientCG categories").values():
        for entry in require_array(require_object(cat, "a download category")
                                   .get("downloads"), "the downloads"):
            f = require_object(entry, "a download")
            attribute = f.get("attribute")
            if isinstance(attribute, str) and attribute.startswith(resolution) \
                    and "JPG" in attribute:
                return _require_download_host(
                    require_text(f.get("downloadLink"), "the download link"))
    raise RuntimeError("no %s JPG download for %s" % (resolution, asset))


def _download(asset: str, resolution: str = "1K") -> zipfile.ZipFile:
    link = _api_download_link(asset, resolution)
    return zipfile.ZipFile(io.BytesIO(_read_capped(link, MAX_ARCHIVE_BYTES)))


def material(name: str, resolution: str = "1K",
             max_member_bytes: int = MAX_MEMBER_BYTES) -> dict[str, str]:
    """Return {'color','normal','roughness','ao'} local map paths for a CATALOG name.

    Downloads + caches on first use. Raises on network failure (caller falls back),
    and on a member larger than ``max_member_bytes``.
    """
    asset = CATALOG.get(name, name)
    out = os.path.join(cache_dir(), "%s_%s" % (asset, resolution))
    os.makedirs(out, exist_ok=True)
    kinds = {"color": "_Color", "normal": "_NormalGL",
             "roughness": "_Roughness", "ao": "_AmbientOcclusion"}
    paths = {k: os.path.join(out, k + ".jpg") for k in kinds}
    if all(os.path.exists(p) for p in (paths["color"], paths["normal"])):
        return {k: p for k, p in paths.items() if os.path.exists(p)}

    z = _download(asset, resolution)
    written = {}
    for kind, marker in kinds.items():
        for n in z.namelist():
            if marker in n and n.lower().endswith((".jpg", ".png")):
                # The declared size is checked before extracting, so a bomb is
                # refused rather than expanded onto the disk and measured after.
                resolver.check_size(z.getinfo(n).file_size, max_member_bytes, n)
                with open(paths[kind], "wb") as fh:
                    fh.write(z.read(n))
                written[kind] = paths[kind]
                break
    _write_manifest(asset, resolution)
    return written


def _write_manifest(asset: str, resolution: str) -> None:
    path = os.path.join(cache_dir(), "CREDITS.txt")
    line = "%s (%s) — CC0, https://ambientcg.com/view?id=%s\n" % (
        asset, resolution, asset)
    try:
        existing = open(path).read() if os.path.exists(path) else ""
        if line not in existing:
            with open(path, "a") as fh:
                fh.write(line)
    except OSError:
        pass


def try_material(name: str, resolution: str = "1K",
                 max_member_bytes: int = MAX_MEMBER_BYTES) -> Optional[dict[str, str]]:
    """Like `material` but returns None on any failure (offline-safe)."""
    try:
        return material(name, resolution, max_member_bytes)
    except Exception:
        return None
