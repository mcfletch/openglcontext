"""What keeps one publisher's content out of another's.

A registry is a file somebody else wrote, naming URLs this application will
fetch and paths it will write. The namespace rule in
:mod:`~OpenGLContext.contentpacks.catalog` keeps an added registry from
declaring a *key* the shipped one declares -- and a key is not where content
lands. These are the cases about where it lands.
"""

import json
import os

import pytest

from OpenGLContext.contentpacks import catalog
from OpenGLContext.contentpacks.store import ContentStore


def registry(tmp_path, name, namespace, packs):
    path = tmp_path / name
    entries = []
    for key, directory in packs:
        entries.append({
            'key': key, 'title': key, 'url': 'https://example.invalid/a.tar.gz',
            'directory': directory, 'archive': 'tar',
            'approximate_bytes': 1024, 'copyright': 'terms',
            'marker': 'tileset.json'})
    path.write_text(json.dumps({'namespace': namespace, 'packs': entries}),
                    encoding='utf-8')
    return catalog.load(str(path))


@pytest.fixture
def store(tmp_path):
    return ContentStore('glisteel', root=str(tmp_path / 'store'), search=[])


class TestTwoPublishersCannotShareADirectory:
    """`directory` is a name a registry chooses, so it cannot be the whole path.

    Without this an added registry declares `directory: "ashdown"` -- a key it
    is allowed, since only the key is namespaced -- and fetching it writes over
    the shipped track's tiles. The application then loads content somebody else
    substituted, having refused nothing at any point.
    """

    def test_the_same_directory_name_in_two_namespaces_is_two_places(
            self, tmp_path, store) -> None:
        mine, = registry(tmp_path, 'a.json', 'glisteel',
                         [('glisteel/ashdown', 'ashdown')])
        theirs, = registry(tmp_path, 'b.json', 'contrib.evil',
                           [('contrib.evil/anything', 'ashdown')])
        assert store.directory_for(mine) != store.directory_for(theirs)

    def test_neither_is_inside_the_other(self, tmp_path, store) -> None:
        """Nesting would be the same hole with an extra step."""
        mine, = registry(tmp_path, 'a.json', 'glisteel',
                         [('glisteel/ashdown', 'ashdown')])
        theirs, = registry(tmp_path, 'b.json', 'contrib.evil',
                           [('contrib.evil/anything', 'ashdown')])
        one, two = store.directory_for(mine), store.directory_for(theirs)
        assert not one.startswith(two + os.sep)
        assert not two.startswith(one + os.sep)

    def test_a_pack_lands_under_its_own_namespace(self, tmp_path,
                                                  store) -> None:
        mine, = registry(tmp_path, 'a.json', 'glisteel',
                         [('glisteel/ashdown', 'ashdown')])
        assert store.directory_for(mine).endswith(
            os.path.join('glisteel', 'ashdown'))

    def test_one_publisher_may_still_share_a_directory_on_purpose(
            self, tmp_path, store) -> None:
        """A track and the art it needs unpack into one tree, by design.

        Same namespace is the same publisher and the same registry, so this is
        theirs to decide; each pack still proves itself by its own marker.
        """
        track, art = registry(tmp_path, 'a.json', 'glisteel',
                              [('glisteel/ashdown', 'ashdown'),
                               ('glisteel/forest-art', 'ashdown')])
        assert store.directory_for(track) == store.directory_for(art)

    def test_a_searched_directory_is_partitioned_the_same_way(
            self, tmp_path) -> None:
        """Or `OPENGLCONTEXT_CONTENT` would be the hole the store closed."""
        mine, = registry(tmp_path, 'a.json', 'glisteel',
                         [('glisteel/ashdown', 'ashdown')])
        theirs, = registry(tmp_path, 'b.json', 'contrib.evil',
                           [('contrib.evil/anything', 'ashdown')])
        elsewhere = tmp_path / 'shipped'
        for pack in (mine, theirs):
            where = elsewhere / pack.namespace / pack.directory
            where.mkdir(parents=True)
            (where / 'tileset.json').write_text(pack.key)
        store = ContentStore('glisteel', root=str(tmp_path / 'store'),
                             search=[str(elsewhere)])
        assert open(os.path.join(store.root_for(mine) or '',
                                 'tileset.json')).read() == 'glisteel/ashdown'


class TestOneRegistryPerNamespace:
    """A namespace is a claim, and two registries may not both make it.

    Nothing proves who owns a namespace -- there is no registrar. What is
    enforceable is that content under one namespace came from one registry, so
    trusting a second is a decision somebody makes rather than one that happens
    quietly.
    """

    def test_two_registries_claiming_one_namespace_are_refused(
            self, tmp_path) -> None:
        mine = registry(tmp_path, 'a.json', 'glisteel',
                        [('glisteel/ashdown', 'ashdown')])
        theirs = registry(tmp_path, 'b.json', 'glisteel',
                          [('glisteel/other', 'other')])
        with pytest.raises(catalog.BadCatalog) as raised:
            catalog.merge(mine, theirs)
        assert 'glisteel' in str(raised.value)

    def test_different_namespaces_merge_as_before(self, tmp_path) -> None:
        mine = registry(tmp_path, 'a.json', 'glisteel',
                        [('glisteel/ashdown', 'ashdown')])
        theirs = registry(tmp_path, 'b.json', 'contrib.x',
                          [('contrib.x/hillclimb', 'hillclimb')])
        assert len(catalog.merge(mine, theirs)) == 2

    def test_one_registry_with_several_packs_is_untouched(self,
                                                          tmp_path) -> None:
        packs = registry(tmp_path, 'a.json', 'glisteel',
                         [('glisteel/one', 'one'), ('glisteel/two', 'two')])
        assert len(catalog.merge(packs)) == 2


class TestTwoRegistriesCannotShareAFile:
    """Registries are kept by URL, and a URL's last segment is not unique.

    Two sources both publishing `registry.zip` would otherwise be one file in
    the store, the second fetch replacing the first -- and with it every pack
    the application had been offered.
    """

    def test_the_same_basename_from_two_sources_is_two_files(self,
                                                             store, tmp_path) -> None:
        source = tmp_path / 'source.zip'
        source.write_bytes(b'PK\x05\x06' + b'\0' * 18)
        one = store.keep_registry(str(source), 'https://good.example/registry.zip')
        two = store.keep_registry(str(source), 'https://evil.example/registry.zip')
        assert one != two
        assert os.path.isfile(one) and os.path.isfile(two)

    def test_they_unpack_to_two_places(self, store, tmp_path) -> None:
        source = tmp_path / 'source.zip'
        source.write_bytes(b'PK\x05\x06' + b'\0' * 18)
        one = store.keep_registry(str(source), 'https://good.example/registry.zip')
        two = store.keep_registry(str(source), 'https://evil.example/registry.zip')
        assert store.unpacked_registry(one) != store.unpacked_registry(two)

    def test_the_same_url_twice_is_one_file(self, store, tmp_path) -> None:
        """Fetching a registry again refreshes it rather than accumulating."""
        source = tmp_path / 'source.zip'
        source.write_bytes(b'PK\x05\x06' + b'\0' * 18)
        url = 'https://good.example/registry.zip'
        assert store.keep_registry(str(source), url) == \
            store.keep_registry(str(source), url)
        assert len(store.registries()) == 1

    def test_the_name_still_says_where_it_came_from(self, store,
                                                    tmp_path) -> None:
        """A store somebody looks in should say what is in it."""
        source = tmp_path / 'source.zip'
        source.write_bytes(b'PK\x05\x06' + b'\0' * 18)
        kept = store.keep_registry(str(source),
                                   'https://good.example/tracks-2026.zip')
        assert 'tracks-2026' in os.path.basename(kept)
