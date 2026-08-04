"""glTF 2.0 / GLB loader -> OpenGLContext scenegraph with PBR materials.

Loads meshes, metallic/roughness materials and textures, plus the full
rig/animation stack (keyframe TRS animation, morph targets, linear-blend skinning)
from self-contained ``.glb`` or ``.gltf`` files with embedded, ``data:``-URI or
external buffers and images. Sparse accessors are handled, as is
``KHR_draco_mesh_compression`` when the optional ``DracoPy`` package is installed
(without it, a Draco primitive is skipped with a warning rather than crashing the
load). The entry points return a :class:`~.scene.GLTFScene` whose ``group`` is a
renderable ``Transform`` the caller mounts and whose ``getDEF(name)`` addresses one
imported node::

    from OpenGLContext.loaders.gltf import load_gltf, load_gltf_url
    scene = load_gltf('model.glb')          # bytes, a path, or (with base_url) refs
    scene = load_gltf_url('https://.../m.gltf')   # fetch + cache, then load
    root = scene.group                       # mount this in your scenegraph
    player = scene.player()                  # animate: player.evaluate(t) per frame

The package is layered bottom-up; each module depends only on those above it.
Secure fetching of external assets is delegated to the shared
:mod:`OpenGLContext.loaders.resolver`, not owned here::

    accessors             buffers/bufferViews/accessors -> numpy arrays
    textures              images + samplers -> PBRTexture holders
    specular_glossiness   the archived spec/gloss extension -> metallic/roughness
    transforms            matrix / quaternion / bounds / camera math
    materials             glTF material + KHR extensions -> PBRMaterial
    draco                 KHR_draco_mesh_compression -> decoded attribute arrays
    meshes                primitive -> renderable Shape (normals/tangents/morph)
    animation             the animation runtime engine + its load-time parsing
    environment_sky       OMI_environment_sky -> the Background node it describes
    scene                 walk the node graph -> GLTFScene (lights, cameras, skins)
    loader                load_gltf / load_gltf_url public entry points
    samples               Khronos glTF-Sample-Assets catalogue helpers

This module is the package's public API. It re-exports the entry points and the
returned/authored types; reach into a submodule (e.g. ``gltf.scene.GLTFScene``,
``gltf.animation.Player``) for the layer internals.
"""
from __future__ import annotations

from OpenGLContext.loaders.gltf.loader import load_gltf, load_gltf_url
from OpenGLContext.loaders.gltf.scene import GLTFScene
from OpenGLContext.loaders.gltf.transforms import look_orientation
from OpenGLContext.loaders.gltf.samples import (
    SAMPLE_MODELS_BASE,
    SAMPLE_MODELS,
    SAMPLE_README_URL,
    sample_model_url,
    fetch_sample_catalog,
    reference_screenshot_url,
    cache_reference_screenshot,
    load_sample,
    load_sample_url,
)

__all__ = [
    "load_gltf",
    "load_gltf_url",
    "GLTFScene",
    "look_orientation",
    "SAMPLE_MODELS_BASE",
    "SAMPLE_MODELS",
    "SAMPLE_README_URL",
    "sample_model_url",
    "fetch_sample_catalog",
    "reference_screenshot_url",
    "cache_reference_screenshot",
    "load_sample",
    "load_sample_url",
]
