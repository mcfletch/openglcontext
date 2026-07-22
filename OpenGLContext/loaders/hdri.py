"""Catalogue of freely-licensed (CC0) HDRI environment panoramas.

A tiny name->URL registry of public-domain equirectangular ``.hdr`` panoramas from
Poly Haven (https://polyhaven.com), so demos and the viewer can name an IBL
environment instead of hard-coding a CDN URL. Every entry is CC0 (public domain,
no attribution required); the ``license``/``author``/``source`` fields keep that
provenance next to the URL. Panoramas are fetched and cached through the Resolver
on first use.

:func:`resolve` maps a catalogue name (``studio_small_03`` or the provider-prefixed
``polyhaven:studio_small_03``) to its URL, and passes an explicit path or http(s)
URL through unchanged, so a caller can accept "environment" from a user as either a
catalogue name or a direct source.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HDRI:
    """One catalogued panorama and its provenance."""
    name: str
    url: str
    license: str
    author: str
    source: str
    description: str = ''


# Poly Haven's CC0 HDRIs, 1k equirectangular .hdr (small enough for a quick demo
# download, enough range for IBL). The 1k file is the reflection/skybox source; the
# IBL probe downsamples it to its env cube regardless.
_PH = 'https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/%s_1k.hdr'


def _polyhaven(name, author, description=''):
    return HDRI(name=name, url=_PH % name, license='CC0', author=author,
                source='https://polyhaven.com/a/%s' % name, description=description)


CATALOG = {
    e.name: e for e in (
        _polyhaven('studio_small_03', 'Greg Zaal',
                   'Neutral indoor studio; good for showing metals/glass.'),
        _polyhaven('kloofendal_43d_clear_puresky', 'Greg Zaal, Sergej Majboroda',
                   'Clear blue sky over an open field; bright outdoor key light.'),
        _polyhaven('venice_sunset', 'Andreas Mischok',
                   'Warm low-sun harbour; strong directional colour.'),
        _polyhaven('brown_photostudio_02', 'Sergej Majboroda',
                   'Softbox photo studio; product-shot lighting.'),
        _polyhaven('mirrored_hall', 'Sergej Majboroda',
                   'Ornate mirrored indoor hall; rich reflections for glass/interiors.'),
        _polyhaven('little_paris_eiffel_tower', 'Sergej Majboroda',
                   'Open-air Paris rooftop with the Eiffel tower; outdoor daylight.'),
    )
}

# The default demo environment: a neutral studio so metals read as metal.
DEFAULT = 'studio_small_03'


def default_url():
    """URL of the default demo HDRI."""
    return CATALOG[DEFAULT].url


def resolve(name_or_source):
    """Resolve a catalogue name to its URL, or pass a path/URL through unchanged.

    Accepts ``studio_small_03``, ``polyhaven:studio_small_03``, an ``http(s)://``
    URL, or a local filesystem path (anything containing a ``/`` or ending ``.hdr``
    is treated as an explicit source). Raises ``KeyError`` for an unknown bare name.
    """
    s = name_or_source.strip()
    if s.startswith(('http://', 'https://')) or '/' in s or s.lower().endswith(
            ('.hdr', '.pic')):
        return s
    if ':' in s:
        provider, _, bare = s.partition(':')
        if provider == 'polyhaven':
            s = bare
    return CATALOG[s].url
