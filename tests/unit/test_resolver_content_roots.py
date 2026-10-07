"""Content roots: the trees an application's own documents may reference across.

A document read from a file may reference files under its own directory. An
application that keeps its content in one tree -- levels beside a shared
textures folder -- declares that tree a content root, and a document inside
it may then reference anything under the root.
"""
import os

import pytest

from OpenGLContext.loaders import resolver


@pytest.fixture
def tree(tmp_path):
    (tmp_path / 'content' / 'levels').mkdir(parents=True)
    (tmp_path / 'content' / 'textures').mkdir()
    (tmp_path / 'content' / 'textures' / 'brick.png').write_bytes(b'png')
    (tmp_path / 'secret.txt').write_text('no')
    return tmp_path


@pytest.fixture
def declared(tree):
    root = str(tree / 'content')
    resolver.add_content_root(root)
    yield root
    resolver.remove_content_root(root)


def test_without_one_a_reference_stays_under_its_document(tree):
    with pytest.raises(IOError):
        resolver.contain(str(tree / 'content' / 'levels'), '../textures/brick.png')


def test_a_reference_across_a_declared_root(tree, declared):
    found = resolver.contain(str(tree / 'content' / 'levels'), '../textures/brick.png')
    assert isinstance(found, resolver.ContainedPath)
    assert found == os.path.realpath(str(tree / 'content' / 'textures' / 'brick.png'))


def test_nothing_above_the_root(tree, declared):
    with pytest.raises(IOError):
        resolver.contain(str(tree / 'content' / 'levels'), '../../secret.txt')


def test_a_document_outside_every_root_keeps_its_own_directory(tree, declared):
    (tree / 'elsewhere').mkdir()
    with pytest.raises(IOError):
        resolver.contain(str(tree / 'elsewhere'), '../content/textures/brick.png')


def test_a_resolver_for_a_file_follows_the_roots(tree, declared):
    found = resolver.Resolver(base_dir=str(tree / 'content' / 'levels')).resolve(
        '../textures/brick.png')
    assert found.endswith('brick.png')


def test_the_roots_declared(tree, declared):
    assert os.path.realpath(declared) in resolver.content_roots()
    resolver.remove_content_root(declared)
    assert os.path.realpath(declared) not in resolver.content_roots()
    resolver.add_content_root(declared)


def test_a_root_is_a_directory(tree):
    with pytest.raises(ValueError):
        resolver.add_content_root(str(tree / 'secret.txt'))
