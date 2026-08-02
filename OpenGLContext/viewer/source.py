"""Where a model comes from, and getting it.

A viewer opens a filesystem path or an http(s) URL, and the difference matters
further than the fetch: a multi-file ``.gltf`` names its ``.bin`` and its images
by URI *relative to the document*, so whatever fetches it has to keep hold of
where it came from.
"""
import os
from typing import TYPE_CHECKING, Optional

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.resolver import is_url

if TYPE_CHECKING:
    from OpenGLContext.loaders.gltf.scene import GLTFScene

__all__ = ['is_url', 'resolve_source', 'load_gltf_source']


def resolve_source(source: Optional[str]) -> Optional[str]:
    """``source`` if it names something openable, else None.

    A local path must exist, so a typo is answered before a window opens rather
    than as an empty scene.  A URL is returned unchanged for
    :func:`load_gltf_source` to fetch, since whether it resolves is not knowable
    without asking.

    Answering rather than exiting, because what to do about a source that is not
    there depends on who asked: a viewer starting up has nothing else to do and
    exits, while one already showing a scene keeps showing it and says so.
    """
    if source is None:
        return None
    if is_url(source):
        return source
    return source if os.path.exists(source) else None


def load_gltf_source(source: str) -> "GLTFScene":
    """Load a :class:`GLTFScene` from a path or an http(s) URL.

    A URL goes through the security-hardened resolver -- same-origin,
    size-capped, disk-cached -- keeping the document URL to resolve a multi-file
    ``.gltf``'s external ``.bin`` and image references against.  Fetching the
    document by itself cannot: the base URL is gone by then and those relative
    references have nowhere to resolve from.  A self-contained ``.glb`` loads
    either way.

    A **Khronos sample** URL falls back through the other variants it may have
    been published as.  Not every sample ships a ``.glb`` -- Sponza, SciFiHelmet
    and Suzanne publish only ``glTF/`` -- so naming the binary one, which is the
    one to prefer, answered 404 for those and they could not be opened at all.
    """
    if is_url(source):
        return gltf.load_sample_url(source)
    return gltf.load_gltf(source)
