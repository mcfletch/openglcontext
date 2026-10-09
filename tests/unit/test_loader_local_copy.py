"""Loader.local_copy: a reference as a file on this machine, under the document's policy.

A movie is read in place, a sample at a time, so its loader hands back a path
rather than the bytes. The policy is the one every other reference is held to.
"""
import os

import pytest

from OpenGLContext.loaders import loader, resolver
from OpenGLContext.loaders.loader import _Loader


@pytest.fixture
def document(tmp_path):
    """A scene file with a movie beside it"""
    base = tmp_path / 'scene.x3d'
    base.write_text('<X3D/>')
    (tmp_path / 'film.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
    return base


def test_a_sibling_file_is_its_own_path(document):
    resolved, path = _Loader().local_copy(['film.mp4'], str(document))
    assert os.path.realpath(path) == os.path.realpath(str(document.parent / 'film.mp4'))
    assert resolved == path


def test_the_first_entry_found_is_taken(document):
    resolved, path = _Loader().local_copy(['missing.mp4', 'film.mp4'], str(document))
    assert os.path.basename(path) == 'film.mp4'


def test_a_reference_out_of_the_directory_is_refused(document):
    outside = document.parent.parent / 'secret.mp4'
    outside.write_bytes(b'secret')
    with pytest.raises(IOError):
        _Loader().local_copy(['../secret.mp4', '/etc/passwd'], str(document))


def test_a_single_string_is_one_entry(document):
    _resolved, path = _Loader().local_copy('film.mp4', str(document))
    assert os.path.basename(path) == 'film.mp4'


def test_a_top_level_file_is_taken_where_it_is(document):
    film = str(document.parent / 'film.mp4')
    _resolved, path = _Loader().local_copy(film)
    assert os.path.realpath(path) == os.path.realpath(film)


def test_a_served_document_downloads_into_the_cache(monkeypatch, tmp_path):
    fetched = []
    (tmp_path / 'cached.mp4').write_bytes(b'film')

    def fetch(url, cache_dir=None, max_bytes=None, **named):
        fetched.append((str(url), max_bytes))
        return resolver.contain(str(tmp_path), 'cached.mp4')

    monkeypatch.setattr(loader, 'fetch_to_cache', fetch)
    resolved, path = _Loader().local_copy(['film.mp4'], 'https://example.com/scenes/room.x3d')
    assert resolved == 'https://example.com/scenes/film.mp4'
    assert fetched == [('https://example.com/scenes/film.mp4',
                        resolver.DEFAULT_MAX_RESOURCE_BYTES)]
    assert os.path.basename(path) == 'cached.mp4'


def test_a_served_document_cannot_reach_another_origin(monkeypatch):
    monkeypatch.setattr(loader, 'fetch_to_cache',
                        lambda *args, **named: pytest.fail('fetched another origin'))
    with pytest.raises(IOError):
        _Loader().local_copy(['https://elsewhere.example/film.mp4'],
                             'https://example.com/scenes/room.x3d')
