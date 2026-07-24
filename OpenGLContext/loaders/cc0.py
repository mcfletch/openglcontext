"""Fetch and cache CC0 PBR textures from ambientCG for the terrain/forest.

ambientCG (https://ambientcg.com) publishes public-domain (CC0) photographic PBR
materials — bark, ground, rock, grass, forest floor — each a set of Color / Normal /
Roughness / AO maps. This downloads a named material once, caches the extracted maps
under the user cache dir, and returns local file paths. Everything is CC0, so it can be
redistributed; a manifest records provenance.

Offline or on failure the caller falls back to the procedural textures in
`foliage.py`; nothing here is required for the engine to run.
"""
import io
import json
import os
import ssl
import urllib.request
import zipfile
from typing import Optional

_UA = {"User-Agent": "Mozilla/5.0 (OpenGLContext terrain)"}
_CTX = ssl.create_default_context()
_API = "https://ambientcg.com/api/v2/full_json?id=%s&type=Material&include=downloadData"

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
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = os.path.join(base, "openglcontext", "cc0")
    os.makedirs(d, exist_ok=True)
    return d


def _download(asset: str, resolution: str = "1K") -> zipfile.ZipFile:
    req = urllib.request.Request(_API % asset, headers=_UA)
    data = json.load(urllib.request.urlopen(req, timeout=25, context=_CTX))
    folders = (data["foundAssets"][0]["downloadFolders"]["default"]
               ["downloadFiletypeCategories"])
    link = None
    for cat in folders.values():
        for f in cat["downloads"]:
            if f.get("attribute", "").startswith(resolution) and "JPG" in f["attribute"]:
                link = f["downloadLink"]
                break
        if link:
            break
    if not link:
        raise RuntimeError("no %s JPG download for %s" % (resolution, asset))
    blob = urllib.request.urlopen(urllib.request.Request(link, headers=_UA),
                                  timeout=60, context=_CTX).read()
    return zipfile.ZipFile(io.BytesIO(blob))


def material(name: str, resolution: str = "1K") -> dict[str, str]:
    """Return {'color','normal','roughness','ao'} local map paths for a CATALOG name.

    Downloads + caches on first use. Raises on network failure (caller falls back).
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


def try_material(name: str, resolution: str = "1K") -> Optional[dict[str, str]]:
    """Like `material` but returns None on any failure (offline-safe)."""
    try:
        return material(name, resolution)
    except Exception:
        return None
