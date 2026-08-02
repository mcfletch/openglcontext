"""Opening a glTF 2.0 asset (``.gltf`` / ``.glb``).

The loader already produces the shape the viewer wants -- bounds, cameras,
animations and a metered exposure -- so this is little more than the choice of
which of the two load paths a source needs.
"""
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

    def load(self, source: str) -> Any:
        """Load ``source`` from disk or over http(s).

        A URL goes through the security-hardened resolver, which also keeps the
        document URL a multi-file ``.gltf`` needs to resolve its ``.bin`` and its
        images against.
        """
        return load_gltf_source(source)
