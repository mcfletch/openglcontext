"""Opening a scene that is inside an archive.

A world that is more than one file -- a ``.gltf`` with its buffers, its textures
and its level-of-detail sidecars -- travels as an archive. A viewer that can
only open a loose path makes the person unpack it first and then find the right
file inside, which is a chore the viewer is in a better position to do.

    oglc-view world.tar.gz#gallery.glb
    oglc-view https://example.com/world.tar.gz#gallery.glb

The fragment names the member. Without one the archive is opened if it holds
exactly one scene file, because then there is no choice to make.

An archive from a URL is somebody else's file, so it goes through the same
extraction the content packs use -- bounded, and refusing a member that climbs
out of the directory. No GL here: this is the source resolution.
"""

import os
import tarfile
import zipfile

import pytest

from OpenGLContext.contentpacks.archive import UnsafeArchive
from OpenGLContext.viewer import source as viewersource


def _tar(path, names, payload=b'glTF-ish'):
    with tarfile.open(path, 'w:gz') as archive:
        for name in names:
            beside = str(path) + '.' + os.path.basename(name)
            with open(beside, 'wb') as handle:
                handle.write(payload)
            archive.add(beside, arcname=name)
            os.unlink(beside)
    return str(path)


def _zip(path, names, payload=b'glTF-ish'):
    with zipfile.ZipFile(path, 'w') as archive:
        for name in names:
            archive.writestr(name, payload)
    return str(path)


@pytest.fixture
def cache(tmp_path):
    return str(tmp_path / 'unpacked')


class TestTellingAnArchiveFromAModel:
    @pytest.mark.parametrize('name', [
        'world.tar.gz', 'world.tgz', 'world.tar', 'world.zip',
        'https://example.com/world.tar.gz',
    ])
    def test_these_are_archives(self, name):
        assert viewersource.is_archive(name)

    @pytest.mark.parametrize('name', [
        'model.glb', 'model.gltf', 'world.wrl', 'tileset.json',
        'https://example.com/model.glb',
    ])
    def test_these_are_not(self, name):
        assert not viewersource.is_archive(name)

    def test_a_fragment_does_not_confuse_it(self):
        assert viewersource.is_archive('world.tar.gz#gallery.glb')

    def test_the_member_is_split_off(self):
        assert viewersource.split_member('world.tar.gz#a/b.glb') == \
            ('world.tar.gz', 'a/b.glb')

    def test_a_source_with_no_fragment_has_no_member(self):
        assert viewersource.split_member('world.tar.gz') == ('world.tar.gz', None)

    def test_a_windows_path_is_not_a_fragment(self):
        assert viewersource.split_member(r'C:\worlds\a.glb') == \
            (r'C:\worlds\a.glb', None)


class TestOpeningAMemberOfALocalArchive:
    def test_the_named_member_is_returned(self, tmp_path, cache):
        path = _tar(tmp_path / 'world.tar.gz', ['gallery.glb', 'CREDITS.txt'])

        got = viewersource.open_archive(path + '#gallery.glb', cache_dir=cache)

        assert os.path.basename(got) == 'gallery.glb'
        assert os.path.exists(got)

    def test_a_zip_works_the_same_way(self, tmp_path, cache):
        path = _zip(tmp_path / 'world.zip', ['gallery.glb'])

        got = viewersource.open_archive(path + '#gallery.glb', cache_dir=cache)

        assert os.path.exists(got)

    def test_a_member_in_a_subdirectory(self, tmp_path, cache):
        path = _tar(tmp_path / 'w.tar.gz', ['gallery/scene.gltf', 'gallery/a.bin'])

        got = viewersource.open_archive(path + '#gallery/scene.gltf',
                                        cache_dir=cache)

        assert os.path.exists(got)

    def test_everything_beside_it_is_unpacked_too(self, tmp_path, cache):
        """A .gltf names its buffers relatively; they have to be there."""
        path = _tar(tmp_path / 'w.tar.gz', ['scene.gltf', 'scene.bin'])

        got = viewersource.open_archive(path + '#scene.gltf', cache_dir=cache)

        assert os.path.exists(os.path.join(os.path.dirname(got), 'scene.bin'))

    def test_the_only_scene_file_needs_no_fragment(self, tmp_path, cache):
        path = _tar(tmp_path / 'w.tar.gz', ['gallery.glb', 'CREDITS.txt'])

        got = viewersource.open_archive(path, cache_dir=cache)

        assert os.path.basename(got) == 'gallery.glb'

    def test_a_choice_of_scenes_asks_for_one(self, tmp_path, cache):
        path = _tar(tmp_path / 'w.tar.gz', ['a.glb', 'b.glb'])

        with pytest.raises(viewersource.UnknownMember) as raised:
            viewersource.open_archive(path, cache_dir=cache)

        assert 'a.glb' in str(raised.value) and 'b.glb' in str(raised.value)

    def test_an_archive_with_no_scene_in_it_says_so(self, tmp_path, cache):
        path = _tar(tmp_path / 'w.tar.gz', ['CREDITS.txt'])

        with pytest.raises(viewersource.UnknownMember):
            viewersource.open_archive(path, cache_dir=cache)

    def test_a_member_that_is_not_there_says_so(self, tmp_path, cache):
        path = _tar(tmp_path / 'w.tar.gz', ['gallery.glb'])

        with pytest.raises(viewersource.UnknownMember) as raised:
            viewersource.open_archive(path + '#absent.glb', cache_dir=cache)

        assert 'absent.glb' in str(raised.value)

    def test_the_second_opening_does_not_unpack_again(self, tmp_path, cache):
        path = _tar(tmp_path / 'w.tar.gz', ['gallery.glb'])
        first = viewersource.open_archive(path + '#gallery.glb', cache_dir=cache)
        os.utime(first, (1, 1))

        again = viewersource.open_archive(path + '#gallery.glb', cache_dir=cache)

        assert again == first
        assert os.stat(again).st_mtime == 1


class TestWhatAnArchiveMayNotDo:
    def test_a_member_climbing_out_is_refused(self, tmp_path, cache):
        """The extraction the content packs use, for the same reason."""
        path = str(tmp_path / 'evil.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('../escaped.glb', b'x')

        with pytest.raises(UnsafeArchive, match='outside'):
            viewersource.open_archive(path + '#escaped.glb', cache_dir=cache)
        assert not os.path.exists(str(tmp_path / 'escaped.glb'))

    def test_a_member_naming_an_absolute_path_is_refused(self, tmp_path, cache):
        outside = tmp_path / 'outside.glb'
        path = str(tmp_path / 'evil.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('/' + str(outside).lstrip('/'), b'x')

        with pytest.raises(UnsafeArchive, match='outside'):
            viewersource.open_archive(path, cache_dir=cache)
        assert not outside.exists()


class TestTheViewersOwnResolution:
    def test_an_archive_resolves_to_the_member_inside_it(self, tmp_path, cache):
        path = _tar(tmp_path / 'w.tar.gz', ['gallery.glb'])

        got = viewersource.resolve_source(path + '#gallery.glb', cache_dir=cache)

        assert os.path.basename(got) == 'gallery.glb'

    def test_a_plain_path_is_unchanged(self, tmp_path):
        path = tmp_path / 'model.glb'
        path.write_bytes(b'x')

        assert viewersource.resolve_source(str(path)) == str(path)

    def test_a_url_is_unchanged(self):
        assert viewersource.resolve_source('https://example.com/a.glb') == \
            'https://example.com/a.glb'

    def test_a_path_that_is_not_there_is_none(self, tmp_path):
        assert viewersource.resolve_source(str(tmp_path / 'absent.glb')) is None

    def test_an_archive_that_is_not_there_is_none(self, tmp_path, cache):
        """A typo in an archive's name is answered as one in a model's is."""
        assert viewersource.resolve_source(
            str(tmp_path / 'absent.zip') + '#gallery.glb', cache_dir=cache) is None
        assert viewersource.resolve_source(
            str(tmp_path / 'absent.tar.gz'), cache_dir=cache) is None

    def test_an_archive_with_a_choice_in_it_says_what_it_holds(self, tmp_path, cache):
        path = _zip(tmp_path / 'w.zip', ['a.glb', 'b.glb'])
        with pytest.raises(viewersource.UnknownMember, match='b.glb'):
            viewersource.resolve_source(path, cache_dir=cache)


class TestAnUnpackingThatDidNotFinish:
    """A world is unpacked once and kept, so a half-unpacked one must not be."""

    def test_the_next_opening_unpacks_it_again(self, tmp_path, cache,
                                               monkeypatch):
        world = _tar(tmp_path / 'world.tar.gz', ['a.bin', 'gallery.glb'])
        real = viewersource.archive.extract

        def interrupted(path, directory, kind, **named):
            os.makedirs(directory, exist_ok=True)
            with open(os.path.join(directory, 'a.bin'), 'wb') as handle:
                handle.write(b'the first member')
            raise KeyboardInterrupt

        monkeypatch.setattr(viewersource.archive, 'extract', interrupted)
        with pytest.raises(KeyboardInterrupt):
            viewersource.open_archive(world, cache_dir=cache)
        monkeypatch.setattr(viewersource.archive, 'extract', real)
        found = viewersource.open_archive(world, cache_dir=cache)
        assert os.path.basename(found) == 'gallery.glb'

    def test_nothing_of_it_is_left_in_the_cache(self, tmp_path, cache,
                                                monkeypatch):
        world = _tar(tmp_path / 'world.tar.gz', ['gallery.glb'])

        def interrupted(path, directory, kind, **named):
            os.makedirs(directory, exist_ok=True)
            raise OSError('the disk is full')

        monkeypatch.setattr(viewersource.archive, 'extract', interrupted)
        with pytest.raises(OSError):
            viewersource.open_archive(world, cache_dir=cache)
        assert [name for name in os.listdir(cache)
                if not name.endswith('.lock')] == []


class TestAPackTheEngineOffers:
    """``oglc-view --pack openglcontext/gallery``: the engine's own registry,
    its store, and the digest check a content pack gets."""

    def installed(self, tmp_path):
        import json
        from OpenGLContext.contentpacks import ContentStore, archive, catalog
        from OpenGLContext.contentpacks import publish
        world = tmp_path / 'built'
        world.mkdir()
        (world / 'gallery.glb').write_bytes(b'glTF')
        dist = tmp_path / 'dist'
        dist.mkdir()
        built = archive.write(str(world), str(dist / 'gallery-world.tar.gz'))
        registry = tmp_path / 'packs.json'
        registry.write_text(json.dumps({'namespace': 'openglcontext', 'packs': [{
            'key': 'openglcontext/gallery', 'title': 'Gallery',
            'url': 'https://github.com/mcfletch/openglcontext/releases/'
                   'download/content-v1/gallery-world.tar.gz',
            'directory': 'gallery', 'archive': 'tar',
            'approximate_bytes': os.path.getsize(built),
            'sha256': archive.digest(built), 'copyright': 'CC0',
            'marker': 'gallery.glb'}]}))
        store = ContentStore('openglcontext', root=str(tmp_path / 'store'),
                             search=[])
        pack, = catalog.load(str(registry))
        publish.install(pack, store, str(dist))
        return str(registry), store

    def test_an_installed_pack_opens_from_the_store(self, tmp_path):
        registry, store = self.installed(tmp_path)
        found = viewersource.open_pack('openglcontext/gallery',
                                       registry=registry, store=store)
        assert found == os.path.join(store.root_for(
            viewersource.pack_named('openglcontext/gallery', registry)),
            'gallery.glb')

    def test_a_key_the_registry_does_not_hold_says_what_it_does(self,
                                                                 tmp_path):
        registry, store = self.installed(tmp_path)
        with pytest.raises(viewersource.UnknownMember) as raised:
            viewersource.open_pack('openglcontext/nothing', registry=registry,
                                   store=store)
        assert 'openglcontext/gallery' in str(raised.value)

    def test_the_engines_registry_ships_in_the_wheel(self):
        import tomllib
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, 'pyproject.toml'), 'rb') as handle:
            data = tomllib.load(handle)['tool']['setuptools']['package-data']
        assert 'packs.json' in data['OpenGLContext']
        assert os.path.isfile(viewersource.ENGINE_REGISTRY)
