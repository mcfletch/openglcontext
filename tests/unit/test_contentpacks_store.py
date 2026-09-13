"""Where an application's packs live, and which of them are already here.

The store answers "is this pack on this machine" before anything asks the user
or touches the network, so a pack is downloaded once and every later run finds
it. It creates nothing until something is written into it: asking where a file
belongs is not a reason to make a directory.
"""

import os

import pytest

from OpenGLContext.contentpacks import store as store_module
from OpenGLContext.contentpacks.pack import ContentPack
from OpenGLContext.contentpacks.store import ContentStore


def pack(key='glisteel/ashdown', directory='ashdown', marker='tileset.json',
         **extra):
    return ContentPack(
        key=key, title='Ashdown', url='https://example.invalid/a.tar.gz',
        directory=directory, archive='tar', approximate_bytes=1024,
        copyright='BSD-3-Clause', marker=marker, **extra)


@pytest.fixture
def store(tmp_path):
    return ContentStore('glisteel', root=str(tmp_path / 'content'))


def shipped(where, one):
    """A searched directory holding a pack, laid out as the store lays them out.

    ``<namespace>/<directory>`` here too: a flat one would be the hole the store
    closes by partitioning content by namespace.
    """
    inside = where / one.namespace / one.directory
    inside.mkdir(parents=True, exist_ok=True)
    (inside / (one.marker or 'something')).write_text('{}')
    return where


def unpack(store, one, *, marker=True):
    """Put a pack's content where the store looks for it."""
    where = store.directory_for(one)
    os.makedirs(where, exist_ok=True)
    if marker and one.marker:
        with open(os.path.join(where, one.marker), 'w') as handle:
            handle.write('{}')
    elif marker:
        with open(os.path.join(where, 'something'), 'w') as handle:
            handle.write('x')
    return where


class TestWhereAPackBelongs:
    def test_it_is_under_the_store_by_namespace_and_directory(self, store) -> None:
        assert store.directory_for(pack()) == os.path.join(
            store.root, 'packs', 'glisteel', 'ashdown')

    def test_asking_creates_nothing(self, tmp_path) -> None:
        store = ContentStore('glisteel', root=str(tmp_path / 'content'))
        store.directory_for(pack())
        assert not os.path.exists(store.root)

    def test_two_applications_do_not_share_one_store(self, tmp_path) -> None:
        """One download cache, but a game's content is its own."""
        monkeypatched = str(tmp_path)
        one = ContentStore('glisteel', root=os.path.join(monkeypatched, 'a'))
        two = ContentStore('twig-bb', root=os.path.join(monkeypatched, 'b'))
        assert one.directory_for(pack()) != two.directory_for(pack())

    def test_the_default_root_is_under_the_application_data_directory(
            self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(store_module.userpaths, 'appdatadirectory',
                            lambda: str(tmp_path))
        monkeypatch.delenv(store_module.CONTENT_OVERRIDE, raising=False)
        store = ContentStore('glisteel')
        assert store.root.startswith(str(tmp_path))
        assert 'glisteel' in store.root


class TestWhetherAPackIsHere:
    def test_one_that_has_not_been_fetched_is_not(self, store) -> None:
        assert store.root_for(pack()) is None

    def test_its_marker_is_what_proves_it(self, store) -> None:
        one = pack()
        where = unpack(store, one)
        assert store.root_for(one) == where

    def test_a_directory_without_the_marker_is_not_unpacked(self, store) -> None:
        """A fetch that died half way leaves a directory and no marker."""
        one = pack()
        os.makedirs(store.directory_for(one))
        assert store.root_for(one) is None

    def test_with_no_marker_a_non_empty_directory_is_proof(self, store) -> None:
        one = pack(marker='')
        os.makedirs(store.directory_for(one))
        assert store.root_for(one) is None, 'an empty directory proves nothing'
        with open(os.path.join(store.directory_for(one), 'x'), 'w') as handle:
            handle.write('x')
        assert store.root_for(one) == store.directory_for(one)

    def test_a_marker_below_the_top_is_honoured(self, store) -> None:
        one = pack(marker='maps/plat23.bsp')
        where = store.directory_for(one)
        os.makedirs(os.path.join(where, 'maps'))
        with open(os.path.join(where, 'maps', 'plat23.bsp'), 'w') as handle:
            handle.write('x')
        assert store.root_for(one) == where


class TestAskingAboutSeveral:
    def test_it_says_which_are_here_and_which_are_not(self, store) -> None:
        here, absent = pack(key='glisteel/one', directory='one'), pack(
            key='glisteel/two', directory='two')
        unpack(store, here)
        assert store.installed([here, absent]) == [here]
        assert store.missing([here, absent]) == [absent]

    def test_the_order_asked_is_the_order_answered(self, store) -> None:
        packs = [pack(key='glisteel/%d' % n, directory=str(n))
                 for n in range(4)]
        assert store.missing(packs) == packs


class TestADirectoryPointedAtInstead:
    """`OPENGLCONTEXT_CONTENT` is what a packaged, offline or CI run uses.

    Searched before the store, so a machine that cannot reach the network -- or
    should not -- runs against a local copy and fetches nothing.
    """

    def test_content_there_is_found_without_a_fetch(self, store, tmp_path,
                                                    monkeypatch) -> None:
        elsewhere = shipped(tmp_path / 'shipped', pack())
        monkeypatch.setenv(store_module.CONTENT_OVERRIDE, str(elsewhere))
        store = ContentStore('glisteel', root=store.root)
        assert store.root_for(pack()) == str(elsewhere / 'glisteel' / 'ashdown')

    def test_it_outranks_the_store(self, store, tmp_path, monkeypatch) -> None:
        one = pack()
        unpack(store, one)
        elsewhere = shipped(tmp_path / 'shipped', one)
        monkeypatch.setenv(store_module.CONTENT_OVERRIDE, str(elsewhere))
        store = ContentStore('glisteel', root=store.root)
        assert store.root_for(one) == str(elsewhere / 'glisteel' / 'ashdown')

    def test_one_that_holds_nothing_falls_through_to_the_store(
            self, store, tmp_path, monkeypatch) -> None:
        one = pack()
        where = unpack(store, one)
        monkeypatch.setenv(store_module.CONTENT_OVERRIDE, str(tmp_path / 'empty'))
        store = ContentStore('glisteel', root=store.root)
        assert store.root_for(one) == where

    def test_several_directories_are_searched_in_order(self, store, tmp_path,
                                                       monkeypatch) -> None:
        first = tmp_path / 'first'
        second = shipped(tmp_path / 'second', pack())
        monkeypatch.setenv(store_module.CONTENT_OVERRIDE,
                           os.pathsep.join([str(first), str(second)]))
        store = ContentStore('glisteel', root=store.root)
        assert store.root_for(pack()) == str(second / 'glisteel' / 'ashdown')

    def test_a_caller_may_name_them_rather_than_the_environment(
            self, tmp_path) -> None:
        elsewhere = shipped(tmp_path / 'shipped', pack())
        store = ContentStore('glisteel', root=str(tmp_path / 'content'),
                             search=[str(elsewhere)])
        assert store.root_for(pack()) == str(elsewhere / 'glisteel' / 'ashdown')


class TestTheRegistriesDirectory:
    """Extra registries a build did not ship, merged in from the store."""

    def test_none_where_there_is_no_directory(self, store) -> None:
        assert store.registries() == []

    def test_every_json_in_it_in_a_settled_order(self, store) -> None:
        where = os.path.join(store.root, 'registries')
        os.makedirs(where)
        for name in ('b.json', 'a.json', 'notes.txt'):
            with open(os.path.join(where, name), 'w') as handle:
                handle.write('{}')
        assert store.registries() == [os.path.join(where, 'a.json'),
                                      os.path.join(where, 'b.json')]
