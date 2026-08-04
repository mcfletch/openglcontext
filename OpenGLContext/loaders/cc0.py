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
import json
import os
import ssl
import urllib.request
import zipfile
from typing import Optional

from OpenGLContext import userpaths
from OpenGLContext.loaders import resolver

_UA = {"User-Agent": resolver._user_agent()}
_CTX = ssl.create_default_context()
_API = "https://ambientcg.com/api/v2/full_json?id=%s&type=Material&include=downloadData"

#: Ceiling on one downloaded material archive. A 1K four-map set is a few MB.
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024      # 256 MiB

#: Ceiling on one map extracted from an archive, applied before it is written.
MAX_MEMBER_BYTES = 64 * 1024 * 1024        # 64 MiB

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
        return resolver._stream(response, max_bytes)


def _api_download_link(asset: str, resolution: str) -> str:
    """The JPG download URL ambientCG offers for ``asset`` at ``resolution``."""
    req = urllib.request.Request(_API % asset, headers=_UA)
    data = json.load(urllib.request.urlopen(req, timeout=25, context=_CTX))
    folders = (data["foundAssets"][0]["downloadFolders"]["default"]
               ["downloadFiletypeCategories"])
    for cat in folders.values():
        for f in cat["downloads"]:
            if f.get("attribute", "").startswith(resolution) and "JPG" in f["attribute"]:
                return str(f["downloadLink"])
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
                resolver._check_size(z.getinfo(n).file_size, max_member_bytes, n)
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
