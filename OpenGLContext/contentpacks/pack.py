"""One downloadable content pack, as a value.

Its own module because three things need it and none should need the others:
:mod:`~OpenGLContext.contentpacks.catalog` reads packs out of a registry file,
:mod:`~OpenGLContext.contentpacks.store` says where one lives on this machine,
and :mod:`~OpenGLContext.contentpacks.fetch` downloads it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ['ContentPack']


@dataclass(frozen=True)
class ContentPack:
    """Data an application fetches rather than ships.

    ``approximate_bytes`` and ``copyright`` are required because both are put in
    front of the user before anything is fetched: a pack that cannot state its
    size and its terms has no business being offered.
    """

    #: ``<namespace>/<name>``. The namespace is the registry that may declare
    #: it, which is what stops an added registry answering for a shipped pack.
    key: str
    title: str
    url: str
    #: Directory name it unpacks into, under the application's store. One path
    #: segment, so a registry cannot choose where on the disk it lands.
    directory: str
    #: ``zip`` or ``tar`` -- the latter covering every compression a tarball
    #: arrives under, which the reader detects for itself.
    archive: str
    approximate_bytes: int
    #: Who holds it and under what terms, then -- after a semicolon -- where the
    #: content was packaged. The order matters: something crediting a pack on
    #: screen while it loads has room for one line and shows everything up to
    #: that semicolon, while an acknowledgements screen prints the whole field.
    copyright: str
    #: A path that, when present, proves the pack is already unpacked. Empty
    #: where the directory existing and being non-empty is proof enough.
    marker: str
    #: The archive's exact digest, lower-case hex, where the publisher controls
    #: the bytes; empty where somebody else hosts it and only an approximate
    #: size can be stated. A rebuilt pack states its new digest, and an
    #: installed copy with the old one is then fetched again, under the same
    #: URL or a new one.
    sha256: str = ''
    #: Whether the application cannot start without it. A base pack is fetched
    #: before anything else, carries a digest, and is not one of a ``family``.
    base: bool = False
    #: Which group of alternatives it belongs to, or None for anything.
    family: str | None = None
    #: Keys of packs this one is incomplete without.
    needs: tuple[str, ...] = ()
    #: A PEP 440 specifier on the version of the application that reads it.
    #: :func:`~OpenGLContext.contentpacks.catalog.for_version` declines a pack
    #: whose specifier excludes the application's version.
    requires: str = ''
    #: A sentence about what it is, for a download or notices screen.
    notes: str = ''
    #: Where a human reads about it.
    url_page: str = ''
    #: A picture of what this pack holds, for a chooser to show before anything
    #: is downloaded. A registry declares it as a path within itself and
    #: :func:`~OpenGLContext.contentpacks.catalog.load` resolves it to a file on
    #: this machine; empty where the registry names none, or names one it does
    #: not carry.
    preview: str = ''

    @property
    def namespace(self) -> str:
        """The registry this pack may be declared by."""
        return self.key.split('/', 1)[0]

    def readable_by(self, version: str) -> bool:
        """Whether an application at ``version`` reads this pack.

        True where the pack states no ``requires``. A pre-release of the
        application counts as its version, so ``>=2.0`` admits ``2.1.0a1``.
        """
        if not self.requires:
            return True
        from packaging.specifiers import SpecifierSet
        return SpecifierSet(self.requires).contains(version, prereleases=True)

    def human_size(self) -> str:
        """The download size as the user should read it."""
        return '%d MB' % (round(self.approximate_bytes / 1e6),)
