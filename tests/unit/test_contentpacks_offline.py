"""Content already on this machine is used without the network being asked.

A box with no route out runs every demo that needs a pack once the pack is
here: installed in the store, unpacked in a searched directory, or sitting in
the download cache as the archive. Each case seeds the content under a URL
nothing serves, then forbids every socket and every name lookup, so a request
made anywhere in the path is an error at the line that made it.
"""

import json
import os
import socket
import zipfile

import pytest

from OpenGLContext.contentpacks import Application, application, archive, fetch
from OpenGLContext.contentpacks.store import ContentStore
from OpenGLContext.loaders import cc0, resolver
from OpenGLContext.viewer import source

from tests.unit.test_contentpacks_fetch import make_tarball, pack

OFFLINE_URL = 'https://content.invalid/releases/ashdown.tar.gz'


class NetworkTouched(AssertionError):
    """Something opened a socket or looked up a name."""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every way out of the process raises :class:`NetworkTouched`."""
    def refuse(*_args, **_named):
        raise NetworkTouched('the network was asked')
    for name in ('getaddrinfo', 'gethostbyname', 'create_connection'):
        monkeypatch.setattr(socket, name, refuse)
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.delenv('OPENGLCONTEXT_CONTENT', raising=False)


@pytest.fixture
def store(tmp_path):
    return ContentStore('glisteel', root=str(tmp_path / 'content'), search=[])


@pytest.fixture
def cache(tmp_path):
    return str(tmp_path / 'cache')


@pytest.fixture
def the_pack(tmp_path):
    """The pack, and the archive it is built from, held back from any store."""
    built = make_tarball(tmp_path, 'built.tar.gz')
    return pack(OFFLINE_URL, sha256=archive.digest(str(built))), built


def downloaded(one, built, cache):
    """``built`` put in the download cache where a fetch of ``one`` finds it."""
    os.makedirs(cache, exist_ok=True)
    target = resolver.cached_path(one.url, cache)
    with open(built, 'rb') as source_file, open(target, 'wb') as kept:
        kept.write(source_file.read())
    return target


class TestAPackInTheStore:
    def test_fetching_it_asks_nothing(self, store, cache, the_pack) -> None:
        one, built = the_pack
        store.install(one, str(built))
        assert fetch.fetch_pack(one, store, cache_dir=cache) == \
            store.directory_for(one)

    def test_a_job_for_it_finishes_without_a_request(self, store, cache,
                                                     the_pack) -> None:
        one, built = the_pack
        store.install(one, str(built))
        job = fetch.FetchJob([one], store, cache_dir=cache).start()
        assert job.wait(10)
        job.poll()
        assert job.failed is None and job.roots == [store.directory_for(one)]

    def test_nothing_is_missing(self, store, the_pack) -> None:
        one, built = the_pack
        store.install(one, str(built))
        assert store.missing([one]) == []
        assert fetch.wanted_for(one, [one], store) == []

    def test_an_installed_one_without_a_digest_in_the_registry(self, store, cache,
                                                               tmp_path) -> None:
        """A pack that names no digest is matched by its URL, with no lookup."""
        built = make_tarball(tmp_path, 'plain.tar.gz')
        one = pack(OFFLINE_URL)
        store.install(one, str(built))
        assert fetch.fetch_pack(one, store, cache_dir=cache) == \
            store.directory_for(one)


class TestAPackInASearchedDirectory:
    def test_it_is_used_where_it_is(self, tmp_path, cache) -> None:
        one = pack(OFFLINE_URL, sha256='ab' * 32)
        placed = tmp_path / 'mine' / one.namespace / one.directory
        placed.mkdir(parents=True)
        (placed / one.marker).write_text('{}')
        store = ContentStore('glisteel', root=str(tmp_path / 'content'),
                             search=[str(tmp_path / 'mine')])
        assert fetch.fetch_pack(one, store, cache_dir=cache) == str(placed)

    def test_the_environment_names_the_directory(self, tmp_path, cache,
                                                 monkeypatch) -> None:
        one = pack(OFFLINE_URL, sha256='ab' * 32)
        placed = tmp_path / 'copy' / one.namespace / one.directory
        placed.mkdir(parents=True)
        (placed / one.marker).write_text('{}')
        monkeypatch.setenv('OPENGLCONTEXT_CONTENT', str(tmp_path / 'copy'))
        store = ContentStore('glisteel', root=str(tmp_path / 'content'))
        assert fetch.fetch_pack(one, store, cache_dir=cache) == str(placed)


class TestAnArchiveInTheDownloadCache:
    def test_it_is_unpacked_without_being_fetched(self, store, cache,
                                                  the_pack) -> None:
        one, built = the_pack
        downloaded(one, built, cache)
        root = fetch.fetch_pack(one, store, cache_dir=cache)
        assert os.path.isfile(os.path.join(root, 'world.json'))

    def test_a_job_unpacks_it_too(self, store, cache, the_pack) -> None:
        one, built = the_pack
        downloaded(one, built, cache)
        job = fetch.FetchJob([one], store, cache_dir=cache).start()
        assert job.wait(10)
        job.poll()
        assert job.failed is None and store.root_for(one) is not None

    def test_a_pack_that_is_nowhere_here_does_ask(self, store, cache,
                                                 the_pack) -> None:
        """The guard bites: with nothing local, the fetch reaches for a socket."""
        one, _built = the_pack
        with pytest.raises(NetworkTouched):
            fetch.fetch_pack(one, store, cache_dir=cache)


class TestAnApplicationWithItsArtHere:
    @pytest.fixture
    def game(self, tmp_path, store, cache, the_pack):
        one, built = the_pack
        one = pack(OFFLINE_URL, key='racer/cars', directory='cars', base=True,
                   sha256=one.sha256)
        registry = tmp_path / 'packs.json'
        registry.write_text(json.dumps({'namespace': 'racer', 'packs': [{
            'key': one.key, 'title': one.title, 'url': one.url,
            'directory': one.directory, 'archive': 'tar',
            'approximate_bytes': 4096, 'sha256': one.sha256, 'base': True,
            'copyright': 'BSD-3-Clause', 'marker': 'world.json'}]}))
        game = Application('racer', str(registry), base='racer/cars',
                           root=store.root, cache_dir=cache)
        return game, one, built

    def test_installed_art_starts_without_a_request(self, game) -> None:
        app, one, built = game
        app.store().install(one, str(built))
        assert app.needed_to_start() == []
        assert app.needs() == []
        assert app.ensure_base() is True
        assert application.ensure_needs(app.needs()) is True
        assert os.path.isdir(app.base_directory())

    def test_art_in_the_download_cache_is_installed_without_a_request(
            self, game, cache) -> None:
        app, one, built = game
        downloaded(one, built, cache)
        assert app.ensure_base() is True
        assert app.base_directory() == app.store().directory_for(one)

    def test_art_in_the_download_cache_through_the_window_job(
            self, game, cache) -> None:
        app, one, built = game
        downloaded(one, built, cache)
        job = app.base_job().start()
        assert job.wait(10)
        job.poll()
        assert job.failed is None and job.roots == [app.store().directory_for(one)]

    def test_the_consent_is_not_asked_for_what_is_here(self, game) -> None:
        app, one, built = game
        app.store().install(one, str(built))

        def refuse(_packs):
            raise AssertionError('asked consent for a download')
        assert app.ensure_base(consent=refuse) is True


class TestAViewerPack:
    def test_a_pack_in_the_store_opens(self, store, the_pack) -> None:
        one, built = the_pack
        store.install(one, str(built))
        assert source.open_pack(one.key, registry=_registry_of(one, store),
                                store=store).endswith(one.marker)

    def test_a_pack_in_the_download_cache_opens(self, store, cache, the_pack,
                                                monkeypatch) -> None:
        one, built = the_pack
        monkeypatch.setattr(resolver, 'default_cache_dir', lambda: cache)
        downloaded(one, built, cache)
        assert source.open_pack(one.key, registry=_registry_of(one, store),
                                store=store).endswith(one.marker)


def _registry_of(one, store):
    path = os.path.join(os.path.dirname(store.root), 'viewer-packs.json')
    with open(path, 'w') as handle:
        json.dump({'namespace': one.namespace, 'packs': [{
            'key': one.key, 'title': one.title, 'url': one.url,
            'directory': one.directory, 'archive': one.archive,
            'approximate_bytes': one.approximate_bytes, 'sha256': one.sha256,
            'copyright': one.copyright, 'marker': one.marker}]}, handle)
    return path


class TestAFetchedDocument:
    def test_one_in_the_cache_is_read_without_a_request(self, cache) -> None:
        url = 'https://assets.invalid/models/Box.glb'
        os.makedirs(cache)
        with open(resolver.cached_path(url, cache), 'wb') as handle:
            handle.write(b'glTF')
        assert resolver.fetch_url(resolver.checked_url(url), cache) == b'glTF'

    def test_a_registry_bundle_in_the_cache_is_read_without_a_request(
            self, store, cache, tmp_path) -> None:
        url = 'https://registry.invalid/registry.zip'
        os.makedirs(cache)
        with zipfile.ZipFile(resolver.cached_path(url, cache), 'w') as bundle:
            bundle.writestr('packs.json', json.dumps({
                'namespace': 'contrib.x', 'packs': [{
                    'key': 'contrib.x/hillclimb', 'title': 'Hill climb',
                    'url': 'https://example.invalid/hillclimb.tar.gz',
                    'directory': 'hillclimb', 'archive': 'tar',
                    'approximate_bytes': 1024, 'copyright': 'CC0',
                    'marker': 'world.json'}]}))
        packs = fetch.fetch_registry(url, store, cache_dir=cache)
        assert [one.key for one in packs] == ['contrib.x/hillclimb']


class TestAmbientCGMaterials:
    def test_a_material_already_extracted_is_not_downloaded(self, tmp_path,
                                                            monkeypatch) -> None:
        monkeypatch.setattr(cc0, 'cache_dir', lambda: str(tmp_path))
        monkeypatch.setattr(cc0, 'pack_directory', lambda: None)
        out = tmp_path / 'Bark012_1K'
        out.mkdir()
        for kind in ('color', 'normal'):
            (out / (kind + '.jpg')).write_bytes(b'x')
        maps = cc0.material('bark')
        assert sorted(maps) == ['color', 'normal']

    def test_a_material_in_the_installed_pack_is_not_downloaded(
            self, tmp_path, monkeypatch) -> None:
        where = tmp_path / cc0.PACK_FOLDER / 'Bark012_1K'
        where.mkdir(parents=True)
        for kind in ('color', 'normal'):
            (where / (kind + '.jpg')).write_bytes(b'x')
        monkeypatch.setattr(cc0, 'pack_directory', lambda: str(tmp_path))
        assert sorted(cc0.material('bark')) == ['color', 'normal']
