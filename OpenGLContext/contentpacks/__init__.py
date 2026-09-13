"""Data an application fetches rather than ships.

A game built on this engine is code plus data, and the two want different
distribution: the code is small and goes to an index, while the art, the levels
and the worlds are tens to hundreds of megabytes and change on their own
cadence. This package is how an application declares the data it needs, offers
it to the user, and finds what has already arrived.

    >>> from OpenGLContext.contentpacks import ContentStore, catalog
    >>> packs = catalog.merge(catalog.load('packs.json'))    # doctest: +SKIP
    >>> store = ContentStore('glisteel')                     # doctest: +SKIP
    >>> store.missing(packs)                                 # doctest: +SKIP

What each module answers is in its own docstring; ``docs/contentpacks.html`` is
the guide for an application author.
"""

from .pack import ContentPack
from .store import ContentStore

__all__ = ['ContentPack', 'ContentStore']
