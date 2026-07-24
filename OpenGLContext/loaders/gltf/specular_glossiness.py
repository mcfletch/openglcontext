"""KHR_materials_pbrSpecularGlossiness -> metallic/roughness conversion.

``KHR_materials_pbrSpecularGlossiness`` is an archived glTF extension: an early
alternative to the metallic/roughness workflow that is now the glTF 2.0 core
model. The PBR shader implements metallic/roughness only, so a spec/gloss material
is converted to an equivalent metallic/roughness one at load time -- this is the
Khronos reference conversion (glTF-Sample-Viewer), not a bespoke rendering model.

Two levels:

* factor-only conversion (:func:`_specgloss_to_metalrough`) -- solve the metallic
  factor from the diffuse/specular blend and rebuild base colour.
* per-pixel texture conversion (:func:`_specgloss_textures_to_metalrough`) --
  needed because a texture-driven spec/gloss asset carries its metalness in the
  specular-glossiness image, not in the factors, so there is no scalar shortcut.

Modern (metallic/roughness) assets never touch this module; only materials that
declare the spec/gloss extension are routed through it by :mod:`materials`.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional, Sequence, Tuple

import numpy as np

if TYPE_CHECKING:
    from PIL import Image


# --- KHR_materials_pbrSpecularGlossiness -> metallic/roughness ---------------
# The metallic/roughness shader can't consume a coloured-specular dielectric
# directly, so spec/gloss materials are converted at load. The naive conversion
# (metallic=0, drop the specular colour) turns a metal authored in spec/gloss
# into dull F0=0.04 plastic -- the SpecGlossVsMetalRough discrepancy. This is the
# Khronos reference conversion (glTF-Sample-Viewer): recover metallic by solving
# the dielectric/metal specular blend, then rebuild base colour accordingly.
_DIELECTRIC_SPECULAR = 0.04


def _perceived_brightness(c: Sequence[float]) -> float:
    return math.sqrt(0.299 * c[0] * c[0] + 0.587 * c[1] * c[1] + 0.114 * c[2] * c[2])


def _solve_metallic(diffuse_b: float, specular_b: float,
                    one_minus_spec_strength: float) -> float:
    """Recover the metallic factor from diffuse/specular perceived brightness."""
    if specular_b < _DIELECTRIC_SPECULAR:
        return 0.0
    a = _DIELECTRIC_SPECULAR
    b = (diffuse_b * one_minus_spec_strength / (1.0 - _DIELECTRIC_SPECULAR)
         + specular_b - 2.0 * _DIELECTRIC_SPECULAR)
    c = _DIELECTRIC_SPECULAR - specular_b
    disc = max(b * b - 4.0 * a * c, 0.0)
    return min(max((-b + math.sqrt(disc)) / (2.0 * a), 0.0), 1.0)


def _specgloss_to_metalrough(diffuse_rgb: Sequence[float], spec_rgb: Sequence[float],
                             glossiness: float) -> Tuple[list, float, float]:
    """Convert (diffuse, specular, glossiness) -> (baseColor, metallic, roughness)."""
    eps = 1e-6
    one_minus_spec_strength = 1.0 - max(spec_rgb[0], spec_rgb[1], spec_rgb[2])
    metallic = _solve_metallic(
        _perceived_brightness(diffuse_rgb), _perceived_brightness(spec_rgb),
        one_minus_spec_strength)
    denom = max(1.0 - metallic, eps)
    base = []
    for d, s in zip(diffuse_rgb[:3], spec_rgb[:3], strict=True):
        from_diffuse = d * one_minus_spec_strength / (1.0 - _DIELECTRIC_SPECULAR) / denom
        from_specular = (s - _DIELECTRIC_SPECULAR * (1.0 - metallic)) / max(metallic, eps)
        c = from_diffuse * (1.0 - metallic * metallic) + from_specular * (metallic * metallic)
        base.append(min(max(c, 0.0), 1.0))
    return base, metallic, 1.0 - float(glossiness)


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * (c ** (1.0 / 2.4)) - 0.055)


def _specgloss_textures_to_metalrough(diffuse_pil: "Optional[Image.Image]",
                                      sg_pil: "Optional[Image.Image]",
                                      diffuse_factor: Sequence[float],
                                      spec_factor: Sequence[float],
                                      gloss_factor: float) -> "Tuple[Image.Image, Image.Image]":
    """Per-pixel spec/gloss -> (baseColorTexture, metallicRoughnessTexture) PILs.

    The metalness of texture-driven spec/gloss assets (e.g. SpecGlossVsMetalRough)
    lives in the specular-glossiness image, not the factors, so a per-pixel
    conversion is needed for them to render as metal. Works in linear space:
    decode the sRGB diffuse/specular, solve metallic, rebuild base colour, then
    re-encode base to sRGB (sampled as sRGB) while metallic/roughness stay linear.
    """
    from PIL import Image
    # a common resolution (upsample the smaller of the two)
    w = max(diffuse_pil.width if diffuse_pil else 1, sg_pil.width if sg_pil else 1)
    h = max(diffuse_pil.height if diffuse_pil else 1, sg_pil.height if sg_pil else 1)

    def as_array(pil: "Optional[Image.Image]", default: float) -> np.ndarray:
        if pil is None:
            return np.full((h, w, 4), default, dtype='f')
        if (pil.width, pil.height) != (w, h):
            # Pillow keeps BILINEAR as a module-level alias at runtime; its inline
            # types only expose it under Image.Resampling, so mypy can't see it.
            pil = pil.resize((w, h), Image.BILINEAR)  # type: ignore[attr-defined]
        return np.asarray(pil, dtype='f') / 255.0

    diff = as_array(diffuse_pil, 1.0)
    sg = as_array(sg_pil, 1.0)

    diffuse_lin = _srgb_to_linear(diff[..., :3]) * np.asarray(diffuse_factor[:3], 'f')
    spec_lin = _srgb_to_linear(sg[..., :3]) * np.asarray(spec_factor[:3], 'f')
    gloss = sg[..., 3] * float(gloss_factor)
    alpha = diff[..., 3] * (diffuse_factor[3] if len(diffuse_factor) > 3 else 1.0)

    pb_diff = np.sqrt(0.299 * diffuse_lin[..., 0] ** 2 + 0.587 * diffuse_lin[..., 1] ** 2
                      + 0.114 * diffuse_lin[..., 2] ** 2)
    spec_max = np.max(spec_lin, axis=-1)
    pb_spec = np.sqrt(0.299 * spec_lin[..., 0] ** 2 + 0.587 * spec_lin[..., 1] ** 2
                      + 0.114 * spec_lin[..., 2] ** 2)
    one_minus = 1.0 - spec_max

    a = _DIELECTRIC_SPECULAR
    b = (pb_diff * one_minus / (1.0 - _DIELECTRIC_SPECULAR)
         + pb_spec - 2.0 * _DIELECTRIC_SPECULAR)
    c = _DIELECTRIC_SPECULAR - pb_spec
    disc = np.maximum(b * b - 4.0 * a * c, 0.0)
    metallic = np.clip((-b + np.sqrt(disc)) / (2.0 * a), 0.0, 1.0)
    metallic = np.where(pb_spec < _DIELECTRIC_SPECULAR, 0.0, metallic)

    eps = 1e-6
    denom = np.maximum(1.0 - metallic, eps)[..., None]
    m2 = (metallic * metallic)[..., None]
    from_diffuse = diffuse_lin * one_minus[..., None] / (1.0 - _DIELECTRIC_SPECULAR) / denom
    from_specular = (spec_lin - _DIELECTRIC_SPECULAR * (1.0 - metallic)[..., None]) \
        / np.maximum(metallic[..., None], eps)
    base_lin = np.clip(from_diffuse * (1.0 - m2) + from_specular * m2, 0.0, 1.0)

    base_srgb = _linear_to_srgb(base_lin)
    base_rgba = np.concatenate([base_srgb, alpha[..., None]], axis=-1)
    base_img = Image.fromarray((base_rgba * 255.0 + 0.5).astype('u1'), 'RGBA')

    # metallicRoughness packing: G=roughness, B=metallic (R/A unused, kept opaque)
    roughness = 1.0 - gloss
    mr = np.zeros((h, w, 4), dtype='f')
    mr[..., 1] = roughness
    mr[..., 2] = metallic
    mr[..., 3] = 1.0
    mr_img = Image.fromarray((mr * 255.0 + 0.5).astype('u1'), 'RGBA')
    return base_img, mr_img
