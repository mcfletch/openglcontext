"""A filesystem path is not a URL, and one of them starts with a drive letter.

``urlsplit`` reads ``C:\\scenes\\room.wrl`` as the scheme ``c`` with the path
``\\scenes\\room.wrl`` -- a scheme the loader does not know, and a path with the
drive dropped off it. Every absolute path on Windows looks like that, so a scene
opened by absolute path resolves none of its references and a scene opened at
all raises for a scheme nobody wrote.

No registered URL scheme is a single character, which is what tells the two
apart.
"""

import os

import pytest

from OpenGLContext.loaders.loader import (
    _resolver_for, join_reference, local_path, url_scheme,
)


class TestTellingAPathFromAURL:
    @pytest.mark.parametrize('text,expected', [
        ('http://example.com/a.wrl', 'http'),
        ('https://example.com/a.wrl', 'https'),
        ('file:///tmp/a.wrl', 'file'),
        ('res://icon', 'res'),
        ('wrls/a.wrl', ''),
        ('./a.wrl', ''),
        ('/tmp/scenes/a.wrl', ''),
        (r'C:\scenes\room.wrl', ''),
        (r'c:/scenes/room.wrl', ''),
        (r'Z:\room.wrl', ''),
    ])
    def test_the_scheme_is_what_it_looks_like(self, text, expected):
        assert url_scheme(text) == expected


class TestAnAbsolutePath:
    """Whatever this platform's absolute paths look like, they are paths."""

    def test_local_path_leaves_it_alone(self, tmp_path):
        scene = str(tmp_path / 'room.wrl')
        assert local_path(scene) == scene

    def test_a_resolver_can_be_built_against_it(self, tmp_path):
        """The base of a scene decides what its references may reach."""
        scene = str(tmp_path / 'room.wrl')
        resolver = _resolver_for(scene)
        assert resolver is not None

    def test_the_resolver_is_confined_to_its_own_directory(self, tmp_path):
        scene = str(tmp_path / 'room.wrl')
        resolver = _resolver_for(scene)
        assert os.path.normcase(resolver.base_dir) == os.path.normcase(str(tmp_path))


class TestResolvingAReference:
    """A document's references resolve against wherever the document is."""

    def test_a_sibling_resolves_beside_an_absolute_document(self, tmp_path):
        document = str(tmp_path / 'model.obj')
        joined = join_reference(document, 'brick.png')
        assert os.path.basename(joined) == 'brick.png'
        assert '/' in joined, 'the reference was not resolved against anything'
        assert os.path.dirname(joined.replace('/', os.sep)) == str(tmp_path)

    def test_a_subdirectory_reference_resolves_too(self, tmp_path):
        document = str(tmp_path / 'model.obj')
        joined = join_reference(document, 'textures/brick.png')
        assert joined.replace('/', os.sep).endswith(
            os.path.join('textures', 'brick.png'))

    def test_a_relative_document_keeps_its_directory(self):
        assert join_reference('wrls/model.obj', 'brick.png') == 'wrls/brick.png'

    def test_a_url_document_resolves_as_a_url(self):
        assert join_reference('http://example.com/a/model.obj', 'brick.png') == (
            'http://example.com/a/brick.png')

    def test_a_reference_that_is_itself_a_url_is_left_alone(self, tmp_path):
        document = str(tmp_path / 'model.obj')
        assert join_reference(document, 'http://example.com/b.png') == (
            'http://example.com/b.png')
