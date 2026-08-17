"""Procedurally-textured, alpha-cut foliage for a semi-realistic forest.

Solid-colour primitives read as toy geometry; real foliage is thin alpha-textured
cards — grass blades, pine needles — plus textured bark. This module generates those
textures with numpy and bakes them into small glTF prototypes (alpha-MASK cutout,
double-sided) that the runtime loads once and instances thousands of times.

Textures are deterministic (seeded) so a scene is reproducible.
"""
import os
from collections.abc import Callable, Sequence
from typing import Any, Optional

import numpy as np

from OpenGLContext.loaders import gltf

# Terrain height sampler: height_fn(x, z) -> height (scalar or array, matching x/z).
HeightFn = Callable[..., Any]


# --- procedural textures ------------------------------------------------------

def _noise2d(h: int, w: int, scale: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    small = rng.random((max(2, h // scale), max(2, w // scale)))
    ys = np.linspace(0, small.shape[0] - 1, h)
    xs = np.linspace(0, small.shape[1] - 1, w)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    y1 = np.minimum(y0 + 1, small.shape[0] - 1)
    x1 = np.minimum(x0 + 1, small.shape[1] - 1)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    top = small[y0][:, x0] * (1 - fx) + small[y0][:, x1] * fx
    bot = small[y1][:, x0] * (1 - fx) + small[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def grass_texture(size: int = 128, blades: int = 26, seed: int = 3) -> np.ndarray:
    """RGBA grass-blade card: tapered green blades on a transparent background."""
    img = np.zeros((size, size, 4), np.uint8)
    rng = np.random.default_rng(seed)
    for _ in range(blades):
        x0 = rng.uniform(0.08, 0.92) * size
        sway = rng.uniform(-0.22, 0.22) * size
        width = rng.uniform(0.015, 0.045) * size
        hgt = rng.uniform(0.55, 0.99)
        shade = rng.uniform(0.55, 1.0)
        tipy = rng.uniform(0.85, 1.0)
        for yy in range(size):
            t = yy / size
            if t > hgt:
                continue
            cx = x0 + sway * (t ** 1.6)
            w = width * (1.0 - (t / hgt) ** 1.2)
            # Lush base -> yellow-green tip, brighter toward the top (backlit look).
            up = t / hgt
            r = int((40 + 90 * up) * shade)
            g = int((110 + 80 * up) * shade * tipy)
            b = int((25 + 15 * up) * shade)
            row = size - 1 - yy
            for xx in range(max(0, int(cx - w)), min(size, int(cx + w) + 1)):
                img[row, xx] = (min(255, r), min(255, g), min(255, b), 255)
    return img


def bark_texture(size: int = 128, seed: int = 7) -> np.ndarray:
    """RGB bark: vertical brown fibres with noise."""
    n = _noise2d(size, size, 6, seed)
    v = _noise2d(size, size, 2, seed + 1) * 0.4
    fibre = 0.5 + 0.5 * np.sin(np.linspace(0, np.pi * 14, size))[None, :]
    val = np.clip(0.35 + 0.5 * n + 0.25 * v + 0.15 * fibre, 0, 1)
    img = np.zeros((size, size, 3), np.uint8)
    img[..., 0] = (val * 105 + 25).astype(np.uint8)
    img[..., 1] = (val * 75 + 18).astype(np.uint8)
    img[..., 2] = (val * 55 + 12).astype(np.uint8)
    return img


def ground_texture(size: int = 128, seed: int = 5) -> np.ndarray:
    """RGB forest-floor: brown earth with moss and litter mottle (offline fallback)."""
    dirt = _noise2d(size, size, 8, seed)
    moss = _noise2d(size, size, 4, seed + 2)
    fine = _noise2d(size, size, 2, seed + 5)
    img = np.zeros((size, size, 3), np.uint8)
    base_r = 70 + 55 * dirt + 25 * fine
    base_g = 55 + 45 * dirt + 20 * fine
    base_b = 38 + 25 * dirt
    m = np.clip((moss - 0.55) / 0.25, 0, 1)          # moss patches
    img[..., 0] = np.clip(base_r * (1 - m) + (45 + 40 * fine) * m, 0, 255)
    img[..., 1] = np.clip(base_g * (1 - m) + (85 + 50 * fine) * m, 0, 255)
    img[..., 2] = np.clip(base_b * (1 - m) + (30 + 20 * fine) * m, 0, 255)
    return img


def procedural_ground_maps(seed: int = 5) -> dict[str, str]:
    """A color-only ground map set (dict) for offline use; cached to a temp file."""
    import tempfile
    from PIL import Image
    d = os.path.join(tempfile.gettempdir(), "oglc_proc_ground")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "ground_%d.png" % seed)
    if not os.path.exists(path):
        Image.fromarray(ground_texture(256, seed), "RGB").save(path)
    return {"color": path}


def needle_texture(size: int = 128, sprigs: int = 40, seed: int = 11) -> np.ndarray:
    """RGBA pine-foliage card: clusters of needles on a transparent background."""
    img = np.zeros((size, size, 4), np.uint8)
    rng = np.random.default_rng(seed)
    for _ in range(sprigs):
        cx = rng.uniform(0.1, 0.9) * size
        cy = rng.uniform(0.1, 0.9) * size
        ln = rng.uniform(0.06, 0.16) * size
        ang = rng.uniform(0, 2 * np.pi)
        shade = rng.uniform(0.5, 1.0)
        for k in range(-6, 7):
            a = ang + k * 0.14
            for t in np.linspace(0, ln, int(ln)):
                x = int(cx + np.cos(a) * t)
                y = int(cy + np.sin(a) * t)
                if 0 <= x < size and 0 <= y < size:
                    g = int(120 * shade + 60 * (1 - t / ln))
                    img[y, x] = (int(30 * shade), min(255, g), int(28 * shade), 255)
    return img


# --- glTF prototypes ----------------------------------------------------------

def _textured_glb(positions: np.ndarray, uvs: np.ndarray, indices: np.ndarray,
                  texture: np.ndarray, alpha_mode: str = "OPAQUE",
                  double_sided: bool = True,
                  base_color: tuple[float, float, float, float] = (1, 1, 1, 1)
                  ) -> bytes:
    from PIL import Image
    import io
    from pygltflib import (
        GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
        Buffer, Material, PbrMetallicRoughness, Texture, Image as GImage, Sampler,
        TextureInfo,
    )
    mode = "RGBA" if texture.shape[2] == 4 else "RGB"
    buf = io.BytesIO()
    Image.fromarray(texture, mode).save(buf, format="PNG")
    png = buf.getvalue()

    V = np.asarray(positions, "<f4")
    UV = np.asarray(uvs, "<f4")
    IDX = np.asarray(indices, "<u4")
    blob, spans = b"", []
    for arr in (V, UV, IDX):
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    img_off = len(blob)
    blob += png

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, TEXCOORD_0=1), indices=2, material=0)])]
    g.materials = [Material(
        pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorFactor=list(base_color),
            baseColorTexture=TextureInfo(index=0),
            metallicFactor=0.0, roughnessFactor=1.0),
        alphaMode=alpha_mode, alphaCutoff=0.4, doubleSided=double_sided)]
    g.textures = [Texture(source=0, sampler=0)]
    g.samplers = [Sampler()]
    g.images = [GImage(bufferView=3, mimeType="image/png")]
    g.accessors = [
        Accessor(bufferView=0, componentType=5126, count=len(V), type="VEC3",
                 min=V.min(0).tolist(), max=V.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(UV), type="VEC2"),
        Accessor(bufferView=2, componentType=5125, count=len(IDX), type="SCALAR")]
    g.bufferViews = [BufferView(buffer=0, byteOffset=o, byteLength=l)
                     for o, l in spans]
    g.bufferViews.append(BufferView(buffer=0, byteOffset=img_off, byteLength=len(png)))
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _crossed_quads(width: float, height: float, planes: int = 2
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    V: list[tuple[float, float, float]] = []
    UV: list[tuple[float, float]] = []
    IDX: list[int] = []
    for i in range(planes):
        rot = np.pi * i / planes
        c, s = np.cos(rot), np.sin(rot)
        corners = [(-width / 2, 0, 0), (width / 2, 0, 0),
                   (width / 2, height, 0), (-width / 2, height, 0)]
        base = len(V)
        for x, y, z in corners:
            V.append((x * c - z * s, y, x * s + z * c))
        UV += [(0, 1), (1, 1), (1, 0), (0, 0)]
        IDX += [base, base + 1, base + 2, base, base + 2, base + 3]
    return np.array(V, "f4"), np.array(UV, "f4"), np.array(IDX, "u4")


def _cylinder(radius: float, height: float, sides: int = 10
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    V, UV, IDX = [], [], []
    for i in range(sides + 1):
        a = 2 * np.pi * i / sides
        x, z = np.cos(a) * radius, np.sin(a) * radius
        u = i / sides
        V += [(x, 0, z), (x, height, z)]
        UV += [(u, 1), (u, 0)]
    for i in range(sides):
        b = i * 2
        IDX += [b, b + 2, b + 1, b + 1, b + 2, b + 3]
    return np.array(V, "f4"), np.array(UV, "f4"), np.array(IDX, "u4")


def grass_card_glb(width: float = 0.9, height: float = 0.6, seed: int = 3,
                   planes: int = 3) -> bytes:
    V, UV, IDX = _crossed_quads(width, height, planes=planes)
    return _textured_glb(V, UV, IDX, grass_texture(seed=seed), alpha_mode="MASK")


def conifer_glb(height: float = 9.0, seed: int = 11,
                bark_path: Optional[str] = None) -> bytes:
    """Bark-textured trunk + stacked alpha needle skirts baked into one glTF.

    `bark_path` uses a real CC0 bark JPG for the trunk; otherwise procedural bark."""
    from pygltflib import (
        GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
        Buffer, Material, PbrMetallicRoughness, Texture, Image as GImage, Sampler,
        TextureInfo,
    )
    import io
    from PIL import Image

    trunk_h = height * 0.45
    tV, tUV, tIDX = _cylinder(height * 0.045, trunk_h, sides=8)
    # Three needle skirts (crossed cards) up the tree.
    off = len(tV)
    fV = [tV]
    fUV = [tUV]
    fIDX = [tIDX]
    for i in range(3):
        y = trunk_h * 0.5 + i * height * 0.22
        w = height * 0.5 * (1.0 - 0.22 * i)
        h = height * 0.42
        cV, cUV, cIDX = _crossed_quads(w, h, planes=2)
        cV = cV.copy()
        cV[:, 1] += y
        fV.append(cV)
        fUV.append(cUV)
        fIDX.append(cIDX + off)
        off += len(cV)
    V = np.vstack(fV).astype("<f4")
    UV = np.vstack(fUV).astype("<f4")
    trunk_count = len(tIDX)
    IDX = np.concatenate(fIDX).astype("<u4")

    def png_of(arr: np.ndarray) -> bytes:
        mode = "RGBA" if arr.shape[2] == 4 else "RGB"
        b = io.BytesIO()
        Image.fromarray(arr, mode).save(b, format="PNG")
        return b.getvalue()
    if bark_path:
        with open(bark_path, "rb") as fh:
            bark = fh.read()
        bark_mime = "image/jpeg" if bark_path.lower().endswith((".jpg", ".jpeg")) \
            else "image/png"
    else:
        bark = png_of(bark_texture(seed=seed))
        bark_mime = "image/png"
    needle = png_of(needle_texture(seed=seed + 1))

    blob, spans = b"", []
    for arr in (V, UV, IDX):
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    bark_off = len(blob)
    blob += bark
    needle_off = len(blob)
    blob += needle

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[
        Primitive(attributes=Attributes(POSITION=0, TEXCOORD_0=1),
                  indices=2, material=0),   # trunk
        Primitive(attributes=Attributes(POSITION=0, TEXCOORD_0=1),
                  indices=3, material=1)])]  # needles
    g.materials = [
        Material(pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorTexture=TextureInfo(index=0), metallicFactor=0, roughnessFactor=1),
            alphaMode="OPAQUE", doubleSided=False),
        Material(pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorTexture=TextureInfo(index=1), metallicFactor=0, roughnessFactor=1),
            alphaMode="MASK", alphaCutoff=0.4, doubleSided=True)]
    g.textures = [Texture(source=0, sampler=0), Texture(source=1, sampler=0)]
    g.samplers = [Sampler()]
    g.images = [GImage(bufferView=3, mimeType=bark_mime),
                GImage(bufferView=4, mimeType="image/png")]
    g.accessors = [
        Accessor(bufferView=0, componentType=5126, count=len(V), type="VEC3",
                 min=V.min(0).tolist(), max=V.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(UV), type="VEC2"),
        Accessor(bufferView=2, componentType=5125, count=trunk_count, type="SCALAR"),
        Accessor(bufferView=2, componentType=5125, count=len(IDX) - trunk_count,
                 type="SCALAR", byteOffset=trunk_count * 4)]
    g.bufferViews = [BufferView(buffer=0, byteOffset=o, byteLength=l)
                     for o, l in spans]
    g.bufferViews += [BufferView(buffer=0, byteOffset=bark_off, byteLength=len(bark)),
                      BufferView(buffer=0, byteOffset=needle_off, byteLength=len(needle))]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _pbr_glb(positions: np.ndarray, uvs: np.ndarray, indices: np.ndarray,
            maps: dict[str, str], tile: float = 1.0, alpha_mode: str = "OPAQUE",
            double_sided: bool = True) -> bytes:
    """Build a glTF mesh textured with a CC0 PBR map set (color + normal[+rough]).

    `maps` is the dict from `cc0.material(...)` (local jpg paths). UVs are scaled by
    `tile`. Falls back cleanly if some maps are missing.
    """
    from pygltflib import (
        GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
        Buffer, Material, PbrMetallicRoughness, Texture, Image as GImage, Sampler,
        TextureInfo, NormalMaterialTexture,
    )
    V = np.asarray(positions, "<f4")
    UV = (np.asarray(uvs, "<f4") * tile).astype("<f4")
    IDX = np.asarray(indices, "<u4")
    order = ["color", "normal", "roughness"]
    present = [k for k in order if maps.get(k)]
    blob, spans = b"", []
    for arr in (V, UV, IDX):
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    img_spans = {}
    for k in present:
        data = open(maps[k], "rb").read()
        img_spans[k] = (len(blob), len(data))
        blob += data

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, TEXCOORD_0=1), indices=2, material=0)])]
    pbr = PbrMetallicRoughness(metallicFactor=0.0, roughnessFactor=1.0)
    mat = Material(pbrMetallicRoughness=pbr, alphaMode=alpha_mode,
                   doubleSided=double_sided)
    g.samplers = [Sampler(wrapS=10497, wrapT=10497)]
    g.textures, g.images, g.bufferViews = [], [], [
        BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    for k in present:
        idx = len(g.textures)
        o, l = img_spans[k]
        mime = "image/png" if maps[k].lower().endswith(".png") else "image/jpeg"
        g.bufferViews.append(BufferView(buffer=0, byteOffset=o, byteLength=l))
        g.images.append(GImage(bufferView=len(g.bufferViews) - 1, mimeType=mime))
        g.textures.append(Texture(source=idx, sampler=0))
        if k == "color":
            pbr.baseColorTexture = TextureInfo(index=idx)
        elif k == "normal":
            mat.normalTexture = NormalMaterialTexture(index=idx)
        elif k == "roughness":
            pbr.metallicRoughnessTexture = TextureInfo(index=idx)
    g.materials = [mat]
    g.accessors = [
        Accessor(bufferView=0, componentType=5126, count=len(V), type="VEC3",
                 min=V.min(0).tolist(), max=V.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(UV), type="VEC2"),
        Accessor(bufferView=2, componentType=5125, count=len(IDX), type="SCALAR")]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def textured_ground(positions: np.ndarray, uvs: np.ndarray, indices: np.ndarray,
                    maps: dict[str, str], tile: float = 1.0) -> Any:
    """A loaded ground node textured with a CC0 material set."""
    return gltf.load_gltf(_pbr_glb(positions, uvs, indices, maps, tile=tile,
                                   alpha_mode="OPAQUE", double_sided=False)).group


def _scene_glb(positions: np.ndarray, uvs: np.ndarray,
               primitives: list[dict[str, Any]]) -> bytes:
    """Build a glTF from shared POSITION/TEXCOORD and a list of primitives.

    Each primitive is a dict: ``indices`` (u4 array), and either ``maps`` (a CC0 map
    dict) or ``color`` (rgba); optional ``alpha_mode``, ``double_sided``. Textures are
    deduplicated by path across primitives.
    """
    from pygltflib import (
        GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
        Buffer, Material, PbrMetallicRoughness, Texture, Image as GImage, Sampler,
        TextureInfo, NormalMaterialTexture,
    )
    V = np.asarray(positions, "<f4")
    UV = np.asarray(uvs, "<f4")
    blob, spans = b"", []
    for arr in (V, UV):
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    idx_spans = []
    for prim in primitives:
        arr = np.asarray(prim["indices"], "<u4")
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        idx_spans.append((len(blob), len(raw), len(arr)))
        blob += raw

    # collect images
    img_data = {}
    for prim in primitives:
        for k in ("color", "normal", "roughness"):
            p = (prim.get("maps") or {}).get(k)
            if p:
                if p not in img_data:
                    img_data[p] = open(p, "rb").read()

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.samplers = [Sampler(wrapS=10497, wrapT=10497)]
    g.accessors = [
        Accessor(bufferView=0, componentType=5126, count=len(V), type="VEC3",
                 min=V.min(0).tolist(), max=V.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(UV), type="VEC2")]
    g.bufferViews = [BufferView(buffer=0, byteOffset=o, byteLength=l)
                     for o, l in spans]
    # index accessors
    idx_acc_base = len(g.accessors)
    for o, l, n in idx_spans:
        g.bufferViews.append(BufferView(buffer=0, byteOffset=o, byteLength=l))
        g.accessors.append(Accessor(bufferView=len(g.bufferViews) - 1,
                                    componentType=5125, count=n, type="SCALAR"))
    # images
    path_to_img = {}
    g.images, g.textures = [], []
    for path, data in img_data.items():
        o = len(blob)
        blob += data
        g.bufferViews.append(BufferView(buffer=0, byteOffset=o, byteLength=len(data)))
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        g.images.append(GImage(bufferView=len(g.bufferViews) - 1, mimeType=mime))
        g.textures.append(Texture(source=len(g.images) - 1, sampler=0))
        path_to_img[path] = len(g.textures) - 1
    # materials + primitives
    g.materials, prims = [], []
    for pi, prim in enumerate(primitives):
        pbr = PbrMetallicRoughness(metallicFactor=0.0, roughnessFactor=1.0)
        maps = prim.get("maps") or {}
        if maps.get("color"):
            pbr.baseColorTexture = TextureInfo(index=path_to_img[maps["color"]])
        if prim.get("color"):
            pbr.baseColorFactor = list(prim["color"])
        mat = Material(pbrMetallicRoughness=pbr,
                       alphaMode=prim.get("alpha_mode", "OPAQUE"),
                       doubleSided=prim.get("double_sided", True))
        if prim.get("alpha_mode") == "MASK":
            mat.alphaCutoff = 0.4
        if maps.get("normal"):
            mat.normalTexture = NormalMaterialTexture(index=path_to_img[maps["normal"]])
        g.materials.append(mat)
        prims.append(Primitive(attributes=Attributes(POSITION=0, TEXCOORD_0=1),
                               indices=idx_acc_base + pi, material=pi))
    g.meshes = [Mesh(primitives=prims)]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def slope01(height_fn: HeightFn, x: np.ndarray, z: np.ndarray,
            eps: float = 1.5) -> np.ndarray:
    """Terrain steepness at (x,z): 0 flat .. ~1 very steep (gradient magnitude)."""
    x = np.asarray(x, "d")
    z = np.asarray(z, "d")
    hx = np.asarray(height_fn(x + eps, z), "d") - np.asarray(height_fn(x - eps, z), "d")
    hz = np.asarray(height_fn(x, z + eps), "d") - np.asarray(height_fn(x, z - eps), "d")
    return np.sqrt(hx * hx + hz * hz) / (2 * eps)


def ground_patch_split(center: Sequence[float], radius: float, height_fn: HeightFn,
                       dirt_maps: dict[str, str],
                       rock_maps: Optional[dict[str, str]], res: int = 64,
                       uv_scale: float = 6.0, water_level: float = 0.0,
                       rock_slope: float = 0.55) -> Any:
    """Textured ground where flat areas are dirt and steep areas are rock.

    Triangles are classified by their face slope, so slopes read as exposed stone.
    Returns one glTF node with two textured primitives (dirt + rock)."""
    cx, _, cz = center
    xs = np.linspace(cx - radius, cx + radius, res)
    zs = np.linspace(cz - radius, cz + radius, res)
    gx, gz = np.meshgrid(xs, zs, indexing="ij")
    gy = np.maximum(np.asarray(height_fn(gx, gz), "d"), water_level) + 0.03
    V = np.stack([gx, gy, gz], -1).reshape(-1, 3)
    UV = np.stack([(gx - cx) / uv_scale, (gz - cz) / uv_scale], -1).reshape(-1, 2)
    dirt: list[int] = []
    rock: list[int] = []
    for i in range(res - 1):
        for j in range(res - 1):
            a = i * res + j
            b, c, d = a + 1, a + res, a + res + 1
            for tri in ((a, b, c), (b, d, c)):
                p0, p1, p2 = V[tri[0]], V[tri[1]], V[tri[2]]
                n = np.cross(p1 - p0, p2 - p0)
                ny = abs(n[1]) / (np.linalg.norm(n) + 1e-9)
                (rock if (1.0 - ny) > rock_slope else dirt).extend(tri)
    prims = [{"indices": np.array(dirt or [0, 0, 0], "u4"), "maps": dirt_maps,
              "double_sided": False}]
    if rock_maps and rock:
        prims.append({"indices": np.array(rock, "u4"), "maps": rock_maps,
                      "double_sided": False})
    return gltf.load_gltf(_scene_glb(V, UV, prims)).group


def _load_rgb(path: str, size: int) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB").resize((size, size)),
                      np.float32)


def _upsample(grid: np.ndarray, size: int) -> np.ndarray:
    from PIL import Image
    g = np.asarray(grid, np.float32)
    im = Image.fromarray((np.clip(g, 0, 1) * 255).astype(np.uint8))
    return np.asarray(im.resize((size, size)), np.float32) / 255.0


def blended_ground_texture(mat_paths: Sequence[str], slope_grid: np.ndarray,
                           size: int = 1024, tile_px: int = 256,
                           seed: int = 5) -> np.ndarray:
    """Bake a ground albedo by blending [dirt, rock, needle] materials with a large-
    scale 'painting': rock where the terrain is steep, needle-litter and dirt in
    low-frequency patches. This is texture splatting realised at bake time — one
    control field (noise + slope) chooses/blends N tiled materials per texel."""
    tiles = []
    reps = size // tile_px + 1
    for p in mat_paths:
        t = _load_rgb(p, tile_px)
        tiles.append(np.tile(t, (reps, reps, 1))[:size, :size])
    slope = _upsample(slope_grid, size)
    n_rock = _noise2d(size, size, 24, seed)
    n_needle = _noise2d(size, size, 18, seed + 3)
    w_rock = np.clip(slope * 1.8 + (n_rock - 0.5) * 1.2, 0, 1)
    w_needle = np.clip((n_needle - 0.5) / 0.22, 0, 1) * (1 - w_rock)
    w_dirt = np.clip(1.0 - w_rock - w_needle, 0.02, 1)
    W = np.stack([w_dirt, w_rock, w_needle], -1)
    W /= W.sum(-1, keepdims=True) + 1e-6
    out = sum(tiles[i] * W[..., i:i + 1] for i in range(len(tiles)))
    return np.clip(out, 0, 255).astype(np.uint8)


def ground_patch_blended(center: Sequence[float], radius: float,
                         height_fn: HeightFn, mat_paths: Sequence[str],
                         res: int = 64, uv_scale: float = 8.0,
                         water_level: float = 0.0, tex_size: int = 1024,
                         seed: int = 5) -> Any:
    """A ground patch whose single albedo is a splat-blended bake of several CC0
    materials (dirt/rock/needle), painted by slope + noise. UVs span the patch 1:1 so
    the baked painting maps across it; material tiling inside the bake gives detail."""
    cx, _, cz = center
    xs = np.linspace(cx - radius, cx + radius, res)
    zs = np.linspace(cz - radius, cz + radius, res)
    gx, gz = np.meshgrid(xs, zs, indexing="ij")
    gy = np.maximum(np.asarray(height_fn(gx, gz), "d"), water_level) + 0.03
    slope = slope01(height_fn, gx, gz)
    V = np.stack([gx, gy, gz], -1).reshape(-1, 3)
    # UV covers the patch once; the bake already tiles the materials internally.
    UV = np.stack([(gx - cx) / (2 * radius) + 0.5,
                   (gz - cz) / (2 * radius) + 0.5], -1).reshape(-1, 2)
    idx = []
    for i in range(res - 1):
        for j in range(res - 1):
            a = i * res + j
            b, c, d = a + 1, a + res, a + res + 1
            idx += [a, b, c, b, d, c]
    tex = blended_ground_texture(mat_paths, slope, size=tex_size,
                                 tile_px=tex_size // 6, seed=seed)
    return gltf.load_gltf(_textured_glb(V.astype("f4"), UV.astype("f4"),
                                        np.array(idx, "u4"), tex,
                                        alpha_mode="OPAQUE",
                                        double_sided=False)).group


def ground_patch_node(center: Sequence[float], radius: float, height_fn: HeightFn,
                      maps: dict[str, str], res: int = 48, uv_scale: float = 8.0,
                      water_level: float = 0.0) -> Any:
    """A CC0-textured ground mesh over a disc-ish square around `center`.

    Meshes `height_fn` at `res`x`res`, UV-tiled every `uv_scale` metres, textured with
    the given CC0 map set (colour + normal + roughness). Sits over the streamed terrain
    as the close-up, detailed ground the coarse tiles can't provide."""
    cx, _, cz = center
    xs = np.linspace(cx - radius, cx + radius, res)
    zs = np.linspace(cz - radius, cz + radius, res)
    gx, gz = np.meshgrid(xs, zs, indexing="ij")
    gy = np.maximum(np.asarray(height_fn(gx, gz), "d"), water_level) + 0.03
    V = np.stack([gx, gy, gz], -1).reshape(-1, 3)
    UV = np.stack([(gx - cx) / uv_scale, (gz - cz) / uv_scale], -1).reshape(-1, 2)
    idx = []
    for i in range(res - 1):
        for j in range(res - 1):
            a = i * res + j
            b, c, d = a + 1, a + res, a + res + 1
            idx += [a, b, c, b, d, c]
    return textured_ground(V, UV, np.array(idx, "u4"), maps, tile=1.0)


def _uv_sphere(rings: int = 5, sectors: int = 7
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    V, UV, IDX = [], [], []
    for i in range(rings + 1):
        phi = np.pi * i / rings
        for j in range(sectors + 1):
            th = 2 * np.pi * j / sectors
            V.append((np.sin(phi) * np.cos(th), np.cos(phi), np.sin(phi) * np.sin(th)))
            UV.append((j / sectors, i / rings))
    w = sectors + 1
    for i in range(rings):
        for j in range(sectors):
            a = i * w + j
            b, c, d = a + 1, a + w, a + w + 1
            IDX += [a, c, b, b, c, d]
    return np.array(V, "f4"), np.array(UV, "f4"), np.array(IDX, "u4")


def rock_glb(maps: dict[str, str], seed: int = 0) -> bytes:
    """A rough low-poly boulder textured with a CC0 rock material.

    The origin sits *inside* the rock (base below y=0) so that, placed at terrain
    height, the boulder is partly buried rather than floating on the surface."""
    V, UV, IDX = _uv_sphere(5, 7)
    rng = np.random.default_rng(seed)
    V = V * (1.0 + 0.4 * (rng.random(len(V)) - 0.5))[:, None]
    V[:, 0] *= rng.uniform(0.8, 1.4)
    V[:, 2] *= rng.uniform(0.8, 1.4)
    V[:, 1] *= rng.uniform(0.5, 0.9)
    V[:, 1] -= V[:, 1].min()               # base at 0
    V[:, 1] -= 0.4 * V[:, 1].max()         # then bury ~40% below the ground
    return _scene_glb(V.astype("f4"), (UV * 2.0).astype("f4"),
                      [{"indices": IDX, "maps": maps, "double_sided": False}])


def rock(maps: dict[str, str], seed: int = 0) -> Any:
    return gltf.load_gltf(rock_glb(maps, seed)).group


def flower_texture(size: int = 64, seed: int = 0) -> np.ndarray:
    """RGBA wildflower card: a couple of bright blooms on a transparent background."""
    img = np.zeros((size, size, 4), np.uint8)
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    palette = [(235, 90, 90), (245, 225, 95), (205, 125, 225), (245, 245, 245),
               (245, 150, 65)]
    for _ in range(2):
        cx = rng.uniform(0.3, 0.7) * size
        cy = rng.uniform(0.15, 0.5) * size
        col = palette[rng.integers(len(palette))]
        r = rng.uniform(0.09, 0.15) * size
        # stem
        stem = (np.abs(xx - cx) < size * 0.02) & (yy > cy)
        img[stem] = (60, 120, 45, 255)
        for p in range(6):
            a = 2 * np.pi * p / 6
            px, py = cx + np.cos(a) * r, cy + np.sin(a) * r
            petal = (xx - px) ** 2 + (yy - py) ** 2 < (r * 0.6) ** 2
            img[petal] = (*col, 255)
        centre = (xx - cx) ** 2 + (yy - cy) ** 2 < (r * 0.42) ** 2
        img[centre] = (250, 215, 80, 255)
    # flip so stems point down in UV
    return img[::-1]


def flower_card(width: float = 0.5, height: float = 0.5, seed: int = 0) -> Any:
    V, UV, IDX = _crossed_quads(width, height, planes=2)
    return gltf.load_gltf(_textured_glb(V, UV, IDX, flower_texture(seed=seed),
                                        alpha_mode="MASK")).group


def branch_glb(bark_path: Optional[str] = None, length: float = 1.4,
               seed: int = 0) -> bytes:
    """A fallen stick lying on the ground — a thin gnarled cylinder laid horizontal.

    Modelled along +Z at ground level (so instance yaw spins its direction), with a
    slight bend and taper; reads as a branch, not a post."""
    rng = np.random.default_rng(seed)
    V, UV, IDX = _cylinder(0.035, length, sides=5)
    V = V.copy()
    # Lay it down: the cylinder is built along +Y, rotate onto +Z.
    V = np.stack([V[:, 0], V[:, 2] + 0.035, V[:, 1] - length * 0.5], axis=1)
    V[:, 1] += 0.05 * np.sin(V[:, 2] * 2.0)           # gentle bend
    V[:, 0] += 0.02 * rng.standard_normal(len(V))     # gnarl
    if bark_path:
        maps = {"color": bark_path}
    else:
        import tempfile
        from PIL import Image
        p = os.path.join(tempfile.gettempdir(), "oglc_branch_bark.png")
        if not os.path.exists(p):
            Image.fromarray(bark_texture(64), "RGB").save(p)
        maps = {"color": p}
    return _scene_glb(V.astype("f4"), (UV * np.array([1, 3], "f4")).astype("f4"),
                      [{"indices": IDX, "maps": maps, "double_sided": False}])


def branch(bark_path: Optional[str] = None, length: float = 1.4,
           seed: int = 0) -> Any:
    return gltf.load_gltf(branch_glb(bark_path, length, seed)).group


def tree_texture(size: int = 128, seed: int = 0) -> np.ndarray:
    """RGBA conifer silhouette (stacked foliage + trunk) on a transparent background."""
    img = np.zeros((size, size, 4), np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = size / 2.0
    trunk = (np.abs(xx - cx) < size * 0.04) & (yy > size * 0.72)
    img[trunk] = (70, 46, 26, 255)
    rng = np.random.default_rng(seed)
    for y0, y1, w in ((0.03, 0.42, 0.24), (0.28, 0.62, 0.33), (0.5, 0.80, 0.42)):
        row = yy / size
        within = (row >= y0) & (row <= y1)
        t = np.clip((row - y0) / (y1 - y0 + 1e-6), 0, 1)
        halfw = w * size * t
        band = within & (np.abs(xx - cx) < halfw)
        g = (95 + 55 * (1 - t)).astype(np.uint8)
        img[band, 0] = 28
        img[band, 1] = np.clip(g[band], 0, 255)
        img[band, 2] = 34
        img[band, 3] = 255
    # a little noise on the foliage edge
    edge = (img[:, :, 3] > 0) & (rng.random((size, size)) < 0.08)
    img[edge, 3] = 0
    return img[::-1]


def tree_billboard_glb(width: float = 6.0, height: float = 10.0,
                       seed: int = 0) -> bytes:
    """A cheap 2-plane conifer billboard for distant trees, as glTF bytes.

    The far rung of a tree's detail ladder: two crossed alpha-masked cards for
    the cost of four triangles, where the real conifer is hundreds.
    """
    V, UV, IDX = _crossed_quads(width, height, planes=2)
    return _textured_glb(V, UV, IDX, tree_texture(seed=seed), alpha_mode="MASK")


def tree_billboard(width: float = 6.0, height: float = 10.0, seed: int = 0) -> Any:
    """A loaded 2-plane conifer billboard for distant trees (no shadow-casting)."""
    node = gltf.load_gltf(tree_billboard_glb(width, height, seed)).group
    return no_shadow(node)


def no_shadow(node: Any) -> Any:
    """Mark every Shape under `node` as not casting shadows (returns the node).

    Dense alpha foliage into every shadow cascade is the dominant cost; opting grass
    out keeps the framerate up while trees/rocks still cast."""
    stack = [node]
    while stack:
        n = stack.pop()
        if type(n).__name__ == "Shape":
            n.castsShadow = False
        stack.extend(getattr(n, "children", None) or [])
    return node


def grass_card(width: float = 0.9, height: float = 0.6, seed: int = 3,
               planes: int = 3) -> Any:
    """A loaded, mountable grass-card node (share it across instances)."""
    return gltf.load_gltf(grass_card_glb(width, height, seed, planes)).group


def conifer(height: float = 9.0, seed: int = 11,
            bark_path: Optional[str] = None) -> Any:
    """A loaded, mountable textured-conifer node (share it across instances)."""
    return gltf.load_gltf(conifer_glb(height, seed, bark_path=bark_path)).group
