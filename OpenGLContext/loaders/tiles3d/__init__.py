"""Runtime for OGC 3D Tiles terrain streaming.

Renders a `tileset.json` bounding-volume hierarchy of glTF tile payloads: a
per-frame traversal converts each tile's geometric error to screen-space error
against the live camera, refines where detail is warranted, and drives background
loading and LRU eviction of tile payloads. Reading of the tileset and tile content
is delegated to `py3dtiles`; the camera-driven traversal, streaming, and GL upload
are provided here (no third-party runtime renderer is reusable).
"""
