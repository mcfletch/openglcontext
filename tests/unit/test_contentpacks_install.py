"""What an installed pack is, and what an interrupted install leaves.

A pack is unpacked into a staging directory beside its place in the store and
moved in once it is whole, with a record of what was installed (its key, its
URL and its digest). A later run asks the record, so content a publisher has
rebuilt under a new digest is fetched again, and an extraction that stopped
part way is not taken for a pack.
"""

import io
import os
import tarfile
import threading

import pytest

from OpenGLContext.contentpacks import ContentPack, ContentStore, archive, fetch
from OpenGLContext.contentpacks import publish
from OpenGLContext.loaders import resolver

from . import test_contentpacks_fetch as fetched

#: The local HTTP server and the download cache the fetch tests use.
served = fetched.served
cache = fetched.cache


def a_pack(url='https://example.invalid/ashdown.tar.gz', **named):
    fields = dict(key='glisteel/ashdown', title='Ashdown', url=url,
                  directory='ashdown', archive='tar', approximate_bytes=4096,
                  copyright='BSD-3-Clause', marker='world.json')
    fields.update(named)
    return ContentPack(**fields)


@pytest.fixture
def store(tmp_path):
    return ContentStore('glisteel', root=str(tmp_path / 'content'), search=[])


def tarball(path, members):
    """A tarball of ``members``: (name, bytes) for a file, (name, '->target')
    for a symbolic link."""
    with tarfile.open(path, 'w:gz') as handle:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            if isinstance(payload, str):
                info.type = tarfile.SYMTYPE
                info.linkname = payload[2:]
                handle.addfile(info)
            else:
                info.size = len(payload)
                handle.addfile(info, io.BytesIO(payload))
    return str(path)


class TestAnInterruptedInstall:
    def test_a_refusal_part_way_leaves_no_pack(self, tmp_path, store):
        """The marker came first in the archive; the pack is still not here."""
        path = tarball(tmp_path / 'a.tar.gz', [
            ('world.json', b'{}'),
            ('escape', '->/etc/passwd'),
            ('rest.bin', b'x' * 64)])
        pack = a_pack()
        with pytest.raises(archive.UnsafeArchive):
            store.install(pack, path)
        assert store.root_for(pack) is None
        assert not os.path.exists(store.directory_for(pack))

    def test_nothing_of_the_staging_is_left(self, tmp_path, store):
        path = tarball(tmp_path / 'a.tar.gz', [('world.json', b'{}'),
                                               ('escape', '->/etc/passwd')])
        with pytest.raises(archive.UnsafeArchive):
            store.install(a_pack(), path)
        parent = os.path.dirname(store.directory_for(a_pack()))
        leftovers = [name for name in os.listdir(parent)
                     if not name.endswith('.lock')] if os.path.isdir(parent) else []
        assert leftovers == []

    def test_a_cancel_during_the_unpacking_stops_it(self, tmp_path, store):
        path = tarball(tmp_path / 'a.tar.gz',
                       [('f%d' % n, b'x') for n in range(50)]
                       + [('world.json', b'{}')])
        seen = []

        def cancel():
            seen.append(1)
            return len(seen) > 5

        with pytest.raises(resolver.FetchCancelled):
            store.install(a_pack(), path, cancel=cancel)
        assert store.root_for(a_pack()) is None


class TestAnUpdate:
    def test_a_new_version_leaves_none_of_the_old_files(self, tmp_path, store):
        old = tarball(tmp_path / 'old.tar.gz', [('world.json', b'1'),
                                                ('dropped.bin', b'x')])
        new = tarball(tmp_path / 'new.tar.gz', [('world.json', b'2')])
        store.install(a_pack(sha256=archive.digest(old)), old)
        root = store.install(a_pack(sha256=archive.digest(new)), new)
        assert sorted(name for name in os.listdir(root)
                      if not name.startswith('.')) == ['world.json']

    def test_a_changed_digest_is_not_the_pack_that_is_here(self, tmp_path,
                                                          store):
        old = tarball(tmp_path / 'old.tar.gz', [('world.json', b'1')])
        store.install(a_pack(sha256=archive.digest(old)), old)
        assert store.root_for(a_pack(sha256=archive.digest(old)))
        assert store.root_for(a_pack(sha256='ab' * 32)) is None

    def test_without_a_digest_a_changed_url_is_a_new_pack(self, tmp_path,
                                                          store):
        old = tarball(tmp_path / 'old.tar.gz', [('world.json', b'1')])
        store.install(a_pack(), old)
        assert store.root_for(a_pack())
        assert store.root_for(a_pack(url='https://example.invalid/v2.tgz')) \
            is None

    def test_content_placed_by_hand_is_taken_as_it_is(self, store):
        """A directory with the marker and no record is somebody's own copy."""
        where = store.directory_for(a_pack())
        os.makedirs(where)
        open(os.path.join(where, 'world.json'), 'w').close()
        assert store.root_for(a_pack(sha256='ab' * 32)) == where


class TestARebuiltPackUnderTheSameURL:
    """``publish.push`` replaces a release's assets in place, so a URL can
    serve new bytes under a new digest while the download cache holds the old
    ones."""

    def test_the_cached_copy_is_fetched_again_once(self, served, store,
                                                   cache):
        where, base = served
        url = base + '/a.tar.gz'
        stale = resolver.cached_path(url, cache)
        os.makedirs(cache)
        with open(stale, 'wb') as handle:
            handle.write(b'the build before this one')
        made = fetched.make_tarball(where, 'a.tar.gz')
        root = fetch.fetch_pack(a_pack(url, sha256=fetched.digest_of(made)), store,
                                cache_dir=cache)
        assert os.path.isfile(os.path.join(root, 'world.json'))

    def test_a_digest_the_server_never_matches_is_still_refused(
            self, served, store, cache):
        where, base = served
        fetched.make_tarball(where, 'a.tar.gz')
        with pytest.raises(archive.DigestMismatch):
            fetch.fetch_pack(a_pack(base + '/a.tar.gz', sha256='ab' * 32),
                             store, cache_dir=cache)


class TestContentInsideAnotherPack:
    def world_and_art(self, tmp_path, store):
        world = a_pack(directory='ashdown', needs=('glisteel/art',))
        art = a_pack(key='glisteel/art', directory='art', marker='trees',
                     url='https://example.invalid/art.tar.gz')
        store.install(world, tarball(tmp_path / 'w.tar.gz',
                                     [('world.json', b'{}'),
                                      ('tiles/t0.glb', b'glb')]))
        store.install(art, tarball(tmp_path / 'a1.tar.gz',
                                   [('trees/fir.npz', b'1'),
                                    ('trees/old-oak.npz', b'1')]),
                      within=world)
        return world, art

    def test_both_are_here(self, tmp_path, store):
        world, art = self.world_and_art(tmp_path, store)
        assert store.root_for(art, within=world) == store.directory_for(world)
        assert store.root_for(world)

    def test_replacing_the_art_keeps_the_world(self, tmp_path, store):
        world, art = self.world_and_art(tmp_path, store)
        rebuilt = tarball(tmp_path / 'a2.tar.gz', [('trees/fir.npz', b'2')])
        root = store.install(art, rebuilt, within=world, replace=True)
        assert os.path.isfile(os.path.join(root, 'world.json'))
        assert os.path.isfile(os.path.join(root, 'tiles', 't0.glb'))
        with open(os.path.join(root, 'trees', 'fir.npz'), 'rb') as handle:
            assert handle.read() == b'2'
        assert not os.path.exists(os.path.join(root, 'trees', 'old-oak.npz'))

    def test_publish_replacing_the_art_keeps_the_world(self, tmp_path, store):
        """``--reinstall`` of a needed pack removes that pack and only it."""
        world, art = self.world_and_art(tmp_path, store)
        dist = tmp_path / 'dist'
        dist.mkdir()
        tarball(dist / 'art.tar.gz', [('trees/fir.npz', b'2')])
        publish.install(art, store, str(dist), within=world, replace=True)
        assert store.root_for(world)
        assert store.root_for(art, within=world)

    def test_an_interrupted_one_is_not_installed(self, tmp_path, store,
                                                 monkeypatch):
        world = a_pack(needs=('glisteel/art',))
        art = a_pack(key='glisteel/art', directory='art', marker='trees',
                     url='https://example.invalid/art.tar.gz')
        store.install(world, tarball(tmp_path / 'w.tar.gz',
                                     [('world.json', b'{}')]))
        real = os.replace
        moved = []

        def fail_after_the_marker(source, target):
            moved.append(target)
            if len(moved) == 3:            # the record, one file, then this
                raise OSError('the disk is full')
            return real(source, target)

        monkeypatch.setattr(os, 'replace', fail_after_the_marker)
        with pytest.raises(OSError):
            store.install(art, tarball(tmp_path / 'a.tar.gz',
                                       [('trees/fir.npz', b'1'),
                                        ('trees/pine.npz', b'1')]),
                          within=world)
        monkeypatch.setattr(os, 'replace', real)
        assert store.root_for(art, within=world) is None
        assert store.root_for(world)


class TestTwoInstallsAtOnce:
    def test_both_callers_get_one_whole_pack(self, tmp_path, store):
        path = tarball(tmp_path / 'a.tar.gz',
                       [('f%03d' % n, b'x' * 512) for n in range(200)]
                       + [('world.json', b'{}')])
        pack = a_pack(sha256=archive.digest(path))
        roots, errors = [], []

        def install():
            try:
                roots.append(store.install(pack, path))
            except Exception as error:          # noqa: BLE001 - reported below
                errors.append(error)

        threads = [threading.Thread(target=install) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert errors == []
        assert len(set(roots)) == 1
        assert len([name for name in os.listdir(roots[0])
                    if not name.startswith('.')]) == 201


class TestRemovingAPack:
    def test_a_pack_of_its_own_goes_with_its_directory(self, tmp_path, store):
        path = tarball(tmp_path / 'a.tar.gz', [('world.json', b'{}')])
        root = store.install(a_pack(), path)
        store.remove(a_pack())
        assert not os.path.exists(root)
        assert store.root_for(a_pack()) is None

    def test_a_needed_pack_takes_only_its_own_files(self, tmp_path, store):
        world, art = TestContentInsideAnotherPack().world_and_art(tmp_path,
                                                                  store)
        store.remove(art, within=world)
        root = store.directory_for(world)
        assert not os.path.exists(os.path.join(root, 'trees'))
        assert store.root_for(world) == root
        assert store.root_for(art, within=world) is None

    def test_a_pack_that_is_not_there_is_nothing_to_do(self, store):
        store.remove(a_pack())
        store.remove(a_pack(key='glisteel/art'), within=a_pack())
        assert not os.path.exists(store.directory_for(a_pack()))
        assert store.missing([a_pack()]) == [a_pack()]


class TestReplacingAPackFoundElsewhere:
    def test_a_searched_copy_is_refused_for_replace(self, tmp_path):
        """The searched copy is read first, so a rebuilt one in the store
        would never be opened."""
        search = tmp_path / 'search'
        found = search / 'glisteel' / 'ashdown'
        found.mkdir(parents=True)
        (found / 'world.json').write_text('{}')
        store = ContentStore('glisteel', root=str(tmp_path / 'content'),
                             search=[str(search)])
        dist = tmp_path / 'dist'
        dist.mkdir()
        tarball(dist / 'ashdown.tar.gz', [('world.json', b'{}')])
        with pytest.raises(IOError) as raised:
            publish.install(a_pack(), store, str(dist), replace=True)
        assert 'OPENGLCONTEXT_CONTENT' in str(raised.value)
        assert publish.install(a_pack(), store, str(dist)) == str(found)


class TestTheStoresOwnDirectory:
    @pytest.mark.skipif(os.name != 'posix', reason='POSIX modes')
    def test_it_is_this_accounts_alone(self, tmp_path, store):
        path = tarball(tmp_path / 'a.tar.gz', [('world.json', b'{}')])
        store.install(a_pack(), path)
        assert os.stat(store.root).st_mode & 0o077 == 0


class TestASizeAsAPersonReadsIt:
    @pytest.mark.parametrize('count,shown', [
        (41_711_739, '42 MB'), (640_000, '640 kB'), (12, '1 kB'),
        (2_345_000_000, '2.3 GB')])
    def test_it_is_never_zero_megabytes(self, count, shown):
        from OpenGLContext.contentpacks.pack import human_bytes
        assert human_bytes(count) == shown
        assert a_pack(approximate_bytes=count).human_size() == shown
