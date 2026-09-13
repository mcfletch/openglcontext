"""Fetching a content pack, over a real HTTP server on this machine.

A local server rather than a mocked resolver: what is being checked is that the
download, the size cap, the digest and the unpacking compose into one pack
sitting on disk, and a fake that returned bytes from a dictionary would pass
whether or not any of that were wired up.
"""

import functools
import http.server
import io
import os
import tarfile
import threading

import pytest

from OpenGLContext.contentpacks import archive, catalog, fetch
from OpenGLContext.contentpacks.pack import ContentPack
from OpenGLContext.contentpacks.store import ContentStore


@pytest.fixture
def served(tmp_path):
    """A directory served over HTTP, and the base URL it is at."""
    where = tmp_path / 'served'
    where.mkdir()
    handler = functools.partial(_Quiet, directory=str(where))
    server = _Patient(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield where, 'http://127.0.0.1:%d' % (server.server_address[1],)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        """A suite is not a place for a request log."""


class _Patient(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        """A client that walked away is the point of the cancel and cap cases.

        The default prints a BrokenPipeError traceback, which is noise here and
        would hide one that mattered.
        """


@pytest.fixture
def store(tmp_path):
    return ContentStore('glisteel', root=str(tmp_path / 'content'),
                        search=[])


@pytest.fixture
def cache(tmp_path):
    """The resolver's download cache, kept out of the user's own."""
    return str(tmp_path / 'cache')


def make_tarball(where, name, members=('world.json', 'tiles/t_0.glb'), big=0):
    """A tarball of ``members``; ``big`` bytes each where a size is wanted.

    Incompressible content for the sized form, so the archive on the wire is
    about as large as what it holds -- a tarball of zeroes is not a download.
    """
    path = where / name
    with tarfile.open(path, 'w:gz') as handle:
        for member in members:
            payload = os.urandom(big) if big else b'x' * 16
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            handle.addfile(info, io.BytesIO(payload))
    return path


def pack(url, **extra):
    values = dict(
        key='glisteel/ashdown', title='Ashdown', url=url, directory='ashdown',
        archive='tar', approximate_bytes=4096, copyright='BSD-3-Clause',
        marker='world.json')
    values.update(extra)
    return ContentPack(**values)


def digest_of(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestOnePackFetched:
    def test_it_arrives_unpacked_where_the_store_says(self, served, store,
                                                      cache) -> None:
        where, base = served
        make_tarball(where, 'ashdown.tar.gz')
        one = pack(base + '/ashdown.tar.gz')
        root = fetch.fetch_pack(one, store, cache_dir=cache)
        assert root == store.directory_for(one)
        assert os.path.isfile(os.path.join(root, 'world.json'))
        assert os.path.isfile(os.path.join(root, 'tiles', 't_0.glb'))
        assert store.root_for(one) == root

    def test_progress_is_reported_as_it_arrives(self, served, store,
                                                cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz', ['f%d' % n for n in range(8)], big=64 * 1024)
        seen = []
        fetch.fetch_pack(pack(base + '/a.tar.gz'), store, cache_dir=cache,
                         progress=lambda done, total: seen.append((done, total)))
        assert seen, 'nothing reported'
        assert seen[-1][0] > 0
        assert [done for done, _ in seen] == sorted(done for done, _ in seen)

    def test_a_pack_already_here_is_not_fetched_again(self, served, store,
                                                      cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz')
        one = pack(base + '/a.tar.gz')
        fetch.fetch_pack(one, store, cache_dir=cache)
        os.remove(where / 'a.tar.gz')       # the server can no longer answer
        assert fetch.fetch_pack(one, store, cache_dir=cache) == \
            store.directory_for(one)

    def test_a_finished_bar_is_reported_for_one_already_here(
            self, served, store, cache) -> None:
        """A caller drawing a bar sees it fill whether or not anything moved."""
        where, base = served
        make_tarball(where, 'a.tar.gz')
        one = pack(base + '/a.tar.gz')
        fetch.fetch_pack(one, store, cache_dir=cache)
        seen = []
        fetch.fetch_pack(one, store, cache_dir=cache,
                         progress=lambda done, total: seen.append((done, total)))
        assert seen == [(one.approximate_bytes, one.approximate_bytes)]


class TestWhatIsRefused:
    def test_a_digest_that_does_not_match(self, served, store, cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz')
        one = pack(base + '/a.tar.gz', sha256='ab' * 32)
        with pytest.raises(archive.DigestMismatch):
            fetch.fetch_pack(one, store, cache_dir=cache)

    def test_nothing_is_unpacked_when_the_digest_is_wrong(self, served, store,
                                                          cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz')
        one = pack(base + '/a.tar.gz', sha256='ab' * 32)
        with pytest.raises(archive.DigestMismatch):
            fetch.fetch_pack(one, store, cache_dir=cache)
        assert store.root_for(one) is None

    def test_the_digest_it_declares_is_accepted(self, served, store,
                                                cache) -> None:
        where, base = served
        made = make_tarball(where, 'a.tar.gz')
        one = pack(base + '/a.tar.gz', sha256=digest_of(made))
        assert fetch.fetch_pack(one, store, cache_dir=cache)

    def test_a_pack_far_larger_than_it_said(self, served, store, cache,
                                            monkeypatch) -> None:
        """The cap the declared size sets is the one the download runs under.

        The floor is lowered for the case, since a pack has to exceed 256 MB to
        exceed it otherwise and that is not a file to write in a suite. What is
        under test is that `fetch_pack` hands the resolver a limit at all.
        """
        where, base = served
        make_tarball(where, 'a.tar.gz', big=64 * 1024)
        monkeypatch.setattr(fetch, 'FLOOR', 1024)
        one = pack(base + '/a.tar.gz', approximate_bytes=256)
        with pytest.raises(fetch.TooLarge):
            fetch.fetch_pack(one, store, cache_dir=cache)
        assert store.root_for(one) is None

    def test_every_way_a_fetch_fails_is_an_ioerror(self) -> None:
        """One family for a caller reporting "the download did not work".

        The resolver states an over-cap resource as a ValueError, which is right
        for a size limit in general and wrong for one of several ways a single
        download can fail.
        """
        for kind in (fetch.TooLarge, archive.DigestMismatch,
                     archive.UnsafeArchive, archive.UnreadableArchive):
            assert issubclass(kind, IOError), kind
        assert not issubclass(fetch.Cancelled, IOError), (
            'a cancel is a decision, not a failure')

    def test_an_archive_that_climbs_out_of_the_store(self, served, store,
                                                     cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz', ['../../escaped'])
        with pytest.raises(archive.UnsafeArchive):
            fetch.fetch_pack(pack(base + '/a.tar.gz'), store, cache_dir=cache)

    def test_a_url_that_answers_nothing(self, served, store, cache) -> None:
        _, base = served
        with pytest.raises(IOError):
            fetch.fetch_pack(pack(base + '/absent.tar.gz'), store,
                             cache_dir=cache)


class TestTheSizeCap:
    def test_it_is_the_declared_size_with_headroom(self) -> None:
        assert fetch.fetch_limit(1000) == pytest.approx(
            max(1500, fetch.FLOOR))

    def test_a_small_pack_still_gets_the_resolver_floor(self) -> None:
        """The right cap for an asset of unknown size is the floor here."""
        assert fetch.fetch_limit(1) == fetch.FLOOR

    def test_a_large_one_raises_it(self) -> None:
        assert fetch.fetch_limit(4 * fetch.FLOOR) == 6 * fetch.FLOOR


class TestCancelling:
    def test_the_user_stopping_it_is_not_a_failure(self, served, store,
                                                   cache) -> None:
        """Telling somebody their own decision was an error answers it badly."""
        where, base = served
        make_tarball(where, 'a.tar.gz', ['f%d' % n for n in range(8)], big=64 * 1024)
        with pytest.raises(fetch.Cancelled):
            fetch.fetch_pack(pack(base + '/a.tar.gz'), store, cache_dir=cache,
                             cancel=lambda: True)

    def test_nothing_is_left_behind(self, served, store, cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz', ['f%d' % n for n in range(8)], big=64 * 1024)
        one = pack(base + '/a.tar.gz')
        with pytest.raises(fetch.Cancelled):
            fetch.fetch_pack(one, store, cache_dir=cache, cancel=lambda: True)
        assert store.root_for(one) is None


class TestAJobTheFrameLoopPolls:
    """`poll()` is the only place anything the worker wrote is read.

    That single rule is the whole of the thread safety, and it is why a caller
    needs no lock of its own. Its visible consequence looks like a bug and is
    not: a job whose worker has finished still reports itself unfinished until
    it is polled, because there is nobody to tell.
    """

    def drive(self, job, limit=500):
        import time
        for _ in range(limit):
            job.poll()
            if job.finished:
                return job
            time.sleep(0.01)
        raise AssertionError('the job never finished: %s' % (job.state,))

    def test_it_fetches_what_it_was_given(self, served, store, cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz')
        make_tarball(where, 'b.tar.gz')
        packs = [pack(base + '/a.tar.gz', key='glisteel/a', directory='a'),
                 pack(base + '/b.tar.gz', key='glisteel/b', directory='b')]
        job = self.drive(fetch.FetchJob(packs, store, cache_dir=cache))
        assert not job.failed and not job.cancelled
        assert sorted(os.path.basename(root) for root in job.roots) == ['a', 'b']
        assert job.fraction == 1.0

    def test_it_is_not_finished_until_it_is_polled(self, served, store,
                                                  cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz')
        job = fetch.FetchJob([pack(base + '/a.tar.gz')], store, cache_dir=cache)
        assert not job.finished
        self.drive(job)
        assert job.finished

    def test_one_bar_spans_the_whole_set(self, served, store, cache) -> None:
        """A bar that filled and reset three times reads as three failures."""
        where, base = served
        for name in 'abc':
            make_tarball(where, '%s.tar.gz' % name)
        packs = [pack(base + '/%s.tar.gz' % name, key='glisteel/' + name,
                      directory=name) for name in 'abc']
        job = fetch.FetchJob(packs, store, cache_dir=cache)
        assert job.total_bytes == sum(one.approximate_bytes for one in packs)
        seen = []
        job.on_progress = lambda: seen.append(job.fraction)
        self.drive(job)
        assert seen == sorted(seen), 'the bar went backwards'
        assert job.fraction == 1.0

    def test_a_failure_is_published_rather_than_raised(self, served, store,
                                                       cache) -> None:
        """The frame loop is not a place for an exception from another thread."""
        _, base = served
        job = self.drive(fetch.FetchJob([pack(base + '/absent.tar.gz')], store,
                                        cache_dir=cache))
        assert job.failed is not None
        assert not job.cancelled

    def test_a_cancel_is_not_a_failure(self, served, store, cache) -> None:
        where, base = served
        make_tarball(where, 'a.tar.gz', ['f%d' % n for n in range(8)], big=64 * 1024)
        job = fetch.FetchJob([pack(base + '/a.tar.gz')], store, cache_dir=cache)
        job.cancel()
        self.drive(job)
        assert job.cancelled and job.failed is None

    def test_an_empty_job_is_finished_at_once(self, store, cache) -> None:
        job = fetch.FetchJob([], store, cache_dir=cache)
        assert job.fraction == 1.0
        job.poll()
        assert job.finished and not job.failed

    def test_polling_a_finished_job_costs_nothing(self, served, store,
                                                  cache) -> None:
        """A frame loop that keeps calling is not a frame loop to punish."""
        where, base = served
        make_tarball(where, 'a.tar.gz')
        job = self.drive(fetch.FetchJob([pack(base + '/a.tar.gz')], store,
                                        cache_dir=cache))
        roots, seen = list(job.roots), []
        job.on_progress = lambda: seen.append(1)
        for _ in range(5):
            job.poll()
        assert job.roots == roots and seen == []


class TestWhatTheFirstRunNeeds:
    def test_a_base_pack_not_here_is_named(self, tmp_path, store) -> None:
        packs = [pack('https://example.invalid/a.tar.gz', key='glisteel/cars',
                      directory='cars', base=True, sha256='ab' * 32),
                 pack('https://example.invalid/b.tar.gz', key='glisteel/track',
                      directory='track')]
        assert fetch.missing_base(packs, store) == [packs[0]]

    def test_one_already_here_is_not(self, store) -> None:
        one = pack('https://example.invalid/a.tar.gz', key='glisteel/cars',
                   directory='cars', base=True, sha256='ab' * 32)
        where = store.directory_for(one)
        os.makedirs(where)
        with open(os.path.join(where, one.marker), 'w') as handle:
            handle.write('{}')
        assert fetch.missing_base([one], store) == []

    def test_a_registry_with_no_base_pack_needs_nothing(self, store) -> None:
        assert fetch.missing_base([pack('https://example.invalid/a.tar.gz')],
                                  store) == []

    def test_what_a_base_pack_needs_comes_with_it(self, store) -> None:
        """A base pack may be split; the first run wants all of it."""
        packs = catalog.merge([
            pack('https://example.invalid/a.tar.gz', key='glisteel/cars',
                 directory='cars', base=True, sha256='ab' * 32,
                 needs=('glisteel/shared',)),
            pack('https://example.invalid/b.tar.gz', key='glisteel/shared',
                 directory='shared')])
        assert [one.key for one in fetch.missing_base(packs, store)] == [
            'glisteel/cars', 'glisteel/shared']


class TestARegistryFetchedFromElsewhere:
    """Pointing the application at a registry URL, before any content.

    A bundle is a document and some thumbnails, so fetching one gives a chooser
    a picture of every pack it declares while committing to none of them.
    """

    def registry_bundle(self, where, name='registry.zip', pictures=('p.png',),
                        namespace='contrib.x', key='contrib.x/hillclimb'):
        import json
        import zipfile
        entry = {
            'key': key, 'title': 'Hill climb',
            'url': 'https://example.invalid/hillclimb.tar.gz',
            'directory': 'hillclimb', 'archive': 'tar',
            'approximate_bytes': 10 * 1024 * 1024,
            'copyright': 'Somebody, CC BY 4.0', 'marker': 'world.json',
        }
        if pictures:
            entry['preview'] = pictures[0]
        path = where / name
        with zipfile.ZipFile(path, 'w') as handle:
            handle.writestr('packs.json',
                            json.dumps({'namespace': namespace,
                                        'packs': [entry]}))
            for picture in pictures:
                handle.writestr(picture, b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        return path

    def test_its_packs_and_their_pictures_arrive(self, served, store,
                                                 cache) -> None:
        where, base = served
        self.registry_bundle(where)
        packs = fetch.fetch_registry(base + '/registry.zip', store,
                                     cache_dir=cache)
        assert [one.key for one in packs] == ['contrib.x/hillclimb']
        assert os.path.isfile(packs[0].preview)
        assert packs[0].preview.startswith(store.root)

    def test_no_content_is_downloaded_by_asking(self, served, store,
                                                cache) -> None:
        where, base = served
        self.registry_bundle(where)
        packs = fetch.fetch_registry(base + '/registry.zip', store,
                                     cache_dir=cache)
        assert store.missing(packs) == packs, (
            'looking at a registry fetched content')

    def test_a_bundle_larger_than_a_registry_should_be(self, served, store,
                                                       cache, monkeypatch) -> None:
        """Thumbnails and a document; anything else is not a registry."""
        where, base = served
        self.registry_bundle(where, pictures=tuple(
            'p%d.png' % n for n in range(4)))
        monkeypatch.setattr(fetch, 'REGISTRY_LIMIT', 16)
        with pytest.raises(fetch.TooLarge):
            fetch.fetch_registry(base + '/registry.zip', store, cache_dir=cache)

    def test_one_that_answers_nothing(self, served, store, cache) -> None:
        _, base = served
        with pytest.raises(IOError):
            fetch.fetch_registry(base + '/absent.zip', store, cache_dir=cache)

    def test_it_lands_where_the_store_keeps_added_registries(self, served,
                                                             store, cache) -> None:
        """So a later run finds it without being pointed at it again."""
        where, base = served
        self.registry_bundle(where)
        fetch.fetch_registry(base + '/registry.zip', store, cache_dir=cache)
        kept, = store.registries()
        assert 'registry' in os.path.basename(kept)
        assert [one.key for one in store.load_registries()] == [
            'contrib.x/hillclimb']

    def test_a_registry_cannot_declare_someone_elses_packs(self, served, store,
                                                           cache) -> None:
        """The namespacing rule holds for one fetched as much as one shipped."""
        where, base = served
        self.registry_bundle(where, namespace='contrib.x',
                             key='glisteel/ashdown')
        with pytest.raises(catalog.BadCatalog):
            fetch.fetch_registry(base + '/registry.zip', store, cache_dir=cache)

    @pytest.mark.parametrize('path', ['/a/../../escaped.zip', '/', '/a/..',
                                      '/a/%2e%2e%2fescaped.zip'])
    def test_a_url_cannot_choose_where_the_bundle_is_written(self, store,
                                                             tmp_path, path) -> None:
        """The kept name comes off the URL, which somebody else may have written."""
        source = tmp_path / 'source.zip'
        source.write_bytes(b'PK\x05\x06' + b'\0' * 18)
        kept = store.keep_registry(str(source), 'https://example.invalid' + path)
        assert os.path.dirname(kept) == os.path.join(store.root, 'registries')
        assert os.path.isfile(kept)

    def test_the_user_stopping_a_registry_fetch(self, served, store,
                                                cache) -> None:
        where, base = served
        self.registry_bundle(where, pictures=tuple(
            'p%d.png' % n for n in range(200)))
        with pytest.raises(fetch.Cancelled):
            fetch.fetch_registry(base + '/registry.zip', store,
                                 cache_dir=cache, cancel=lambda: True)
