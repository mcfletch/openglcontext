# Pluggable rendering backends

**Status:** 📋 Placeholder, 2026-09-26. Not started, and not scheduled; this
records the intent so later design work has somewhere to start.

## Intent

Introduce pluggable rendering backends, so the engine can render through
desktop OpenGL, OpenGL ES, Vulkan, Metal or Direct3D.

A backend API isolates all of the logic for rendering the scene with respect
to the rendering API used. The backend is the only point in the engine that
imports a specific API; the scenegraph, the passes and everything above them
talk to the backend, never to GL (or any other API) directly. The desired API
is configured in the context definition, alongside the other
`ContextDefinition` fields.

## Why

- Embedded platforms, where OpenGL ES is what is available.
- Recent Macs, where OpenGL is deprecated and Metal is the native API.
- The goal behind both: the engine should be the default 3D tool people reach
  for when working in client-side Python, and that means running wherever
  that Python runs.

## Scale

This is an enormous change-set: it rewrites a significant subset of the
project. Today GL calls are made directly from geometry nodes' `render()`
methods, the render passes, the instancing and vegetation/terrain layers, the
overlay UI renderer, capture and video, and the shaders are GLSL 330 core.
All of that moves behind the backend API.

## Relationship to other plans

- [WINDOWSYSTEM-COMPOSITION.md](WINDOWSYSTEM-COMPOSITION.md) separates the
  window system from the context. The rendering API is a second, independent
  choice on the same context definition: a window system provides a surface,
  and the rendering backend draws into it.
- [CORE-PROFILE-DEFAULT.md](CORE-PROFILE-DEFAULT.md) and
  [CORE-PROFILE-COMPATIBILITY.md](CORE-PROFILE-COMPATIBILITY.md) moved rendering
  onto shaders and buffers, which is the shape the other APIs share.

## To settle when the plan is written

- The shape of the backend API: its level of abstraction (draw calls and
  resources, or render passes and materials), and how the existing passes map
  onto it.
- Shader sources across APIs: one source language translated per backend, or
  a source per backend.
- What happens to the compatibility-profile (fixed-function) path, which has
  no equivalent outside desktop OpenGL.
- How PyOpenGL fits: this engine exists partly to exercise PyOpenGL, so the GL
  and GLES backends stay first-class, and the Python bindings for Vulkan,
  Metal and Direct3D have to be chosen.
- Ordering: which backend comes second after GL, and whether GLES is a
  variant of the GL backend rather than a backend of its own.
