"""Opening a glTF 2.0 asset (``.gltf`` / ``.glb``).

The loader already produces the shape the viewer wants -- bounds, cameras,
animations and a metered exposure -- so this is little more than the choice of
which of the two load paths a source needs.
"""
import os
from typing import Any

from OpenGLContext.viewer.adapters.base import SceneAdapter
from OpenGLContext.viewer.source import load_gltf_source

__all__ = ['GLTFAdapter']


class GLTFAdapter(SceneAdapter):
    """A glTF asset: one model, in coordinates of its own choosing."""

    name = 'gltf'

    #: A glTF is an *asset*, not a world.  Its origin is wherever the exporter
    #: left it, so a viewer is free to move it to the middle of the frame.
    recentres = True

    accepts_content = True

    def read(self, source: str) -> Any:
        """Load ``source`` from disk or over http(s), as a ``GLTFScene``.

        A URL goes through the security-hardened resolver, which also keeps the
        document URL a multi-file ``.gltf`` needs to resolve its ``.bin`` and its
        images against.
        """
        return load_gltf_source(source)

    def read_content(self, data: bytes, name: str = '') -> Any:
        """Load a ``.glb``, or a ``.gltf`` whose buffers and images are embedded.

        ``name`` is where the document would be: a URL or a path whose
        directory the files a ``.gltf`` names are looked for in.  A bare
        file name leaves a ``.gltf`` with external files nothing to resolve
        them against.
        """
        from OpenGLContext.loaders.gltf import loader
        from OpenGLContext.loaders.resolver import is_url
        if is_url(name):
            return loader.load_gltf(data, base_url=name)
        return loader.load_gltf(data, base_dir=os.path.dirname(name) or None)
