"""The checked types: a path held to its document's directory, a URL checked.

A :class:`~OpenGLContext.loaders.resolver.ContainedPath` or a
:class:`~OpenGLContext.loaders.resolver.CheckedURL` is made only by the
resolver's checks, so a function taking one is never handed a name nothing
has checked. These tests hold the producers to what they check, and the types
to being made nowhere else.
"""
import os
import pickle

import pytest

from OpenGLContext.loaders import resolver
from OpenGLContext.loaders.resolver import (
    AllowedHosts, CheckedURL, ContainedPath, Resolver, ResourceTooLarge,
    checked_source, checked_url, contain, contained_source, open_contained,
    read_contained,
)


def test_a_contained_path_is_under_its_base(tmp_path):
    (tmp_path / 'sub').mkdir()
    found = contain(str(tmp_path), 'sub/buf.bin')
    assert isinstance(found, ContainedPath)
    assert found == os.path.join(os.path.realpath(str(tmp_path)), 'sub', 'buf.bin')


@pytest.mark.parametrize('name', ['../../etc/passwd', '/etc/passwd', 'http://evil/x'])
def test_a_name_leaving_its_base_is_refused(tmp_path, name):
    with pytest.raises(IOError):
        contain(str(tmp_path), name)


@pytest.mark.parametrize('kind', [ContainedPath, CheckedURL])
def test_a_checked_type_is_not_made_directly(kind):
    with pytest.raises(TypeError, match='made by'):
        kind('/etc/passwd', object())
    with pytest.raises(TypeError):
        kind('/etc/passwd')


def test_a_checked_value_pickles_as_the_string_it_is(tmp_path):
    found = contain(str(tmp_path), 'a.bin')
    back = pickle.loads(pickle.dumps(found))  # noqa: S301 the bytes are the ones pickled on this line
    assert back == found
    assert type(back) is str


def test_a_path_built_from_a_contained_one_is_not_contained(tmp_path):
    found = contain(str(tmp_path), 'a')
    assert not isinstance(found + '/../../x', ContainedPath)
    assert not isinstance(os.path.join(found, '..'), ContainedPath)


def test_a_url_is_checked_for_its_scheme():
    assert isinstance(checked_url('https://example.com/a.glb'), CheckedURL)
    assert isinstance(checked_url('http://127.0.0.1:8000/a.glb'), CheckedURL)
    for refused in ('file:///etc/passwd', 'ftp://example.com/a', 'data:,x'):
        with pytest.raises(IOError):
            checked_url(refused)


def test_a_host_check_answers_a_checked_url():
    hosts = AllowedHosts(['dl.polyhaven.org'])
    assert isinstance(hosts.check('https://dl.polyhaven.org/a.hdr'), CheckedURL)
    assert isinstance(resolver.require_host('https://dl.polyhaven.org/a', ['dl.polyhaven.org']),
                      CheckedURL)
    with pytest.raises(IOError):
        hosts.check('https://dl.polyhaven.org.example/a.hdr')


def test_a_resolver_answers_the_checked_type_for_its_base(tmp_path):
    assert isinstance(Resolver(base_dir=str(tmp_path)).resolve('a.bin'), ContainedPath)
    assert isinstance(Resolver(base_url='https://example.com/m/scene.gltf').resolve('a.bin'),
                      CheckedURL)


def test_a_source_the_caller_names_is_checked_once(tmp_path):
    local = checked_source(str(tmp_path / 'model.glb'))
    assert isinstance(local, ContainedPath)
    assert local == os.path.join(os.path.realpath(str(tmp_path)), 'model.glb')
    assert isinstance(checked_source('https://example.com/model.glb'), CheckedURL)
    assert checked_source(local) is local
    for refused in ('file:///etc/passwd', 'data:,x', ''):
        with pytest.raises(IOError):
            checked_source(refused)


def test_a_local_source_is_contained_and_a_url_refused(tmp_path):
    local = contained_source(str(tmp_path / 'chain.glb'))
    assert isinstance(local, ContainedPath)
    assert contained_source(local) is local
    for refused in ('https://example.com/chain.glb', ''):
        with pytest.raises(IOError):
            contained_source(refused)


def test_a_resolver_contains_a_local_reference_and_refuses_a_served_one(tmp_path):
    assert isinstance(Resolver(base_dir=str(tmp_path)).contain('a.bin'), ContainedPath)
    with pytest.raises(IOError, match='served document'):
        Resolver(base_url='https://example.com/scene.gltf').contain('a.bin')


def test_a_contained_file_is_read_under_its_cap(tmp_path):
    (tmp_path / 'a.bin').write_bytes(b'12345')
    found = contain(str(tmp_path), 'a.bin')
    assert read_contained(found) == b'12345'
    with open_contained(found) as handle:
        assert handle.read() == b'12345'
    with pytest.raises(ResourceTooLarge):
        read_contained(found, max_bytes=4)


def test_a_cache_entry_is_contained_in_the_cache(tmp_path):
    found = resolver.cached_path('https://example.com/a.glb', str(tmp_path))
    assert isinstance(found, ContainedPath)
    assert os.path.dirname(found) == os.path.realpath(str(tmp_path))
