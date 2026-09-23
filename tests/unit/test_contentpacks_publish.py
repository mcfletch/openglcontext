"""Getting a pack from a build directory to where it can be fetched.

The two ends of a release that never reaches the network in a test: installing
what was just built into this machine's own store, so a game can be driven
against content no release carries yet, and the call that attaches the same
files to a release when it is time.
"""

import os

import pytest

from OpenGLContext.contentpacks import ContentPack, ContentStore, archive, publish


def a_pack(tmp_path, **named):
    fields = dict(
        key='glisteel/ashdown',
        title='Ashdown',
        url='https://github.com/mcfletch/glisteel/releases/download/'
            'content-v1/glisteel-ashdown.tar.gz',
        directory='ashdown', archive='tar', approximate_bytes=1024,
        copyright='the glisteel project', marker='tileset.json')
    fields.update(named)
    return ContentPack(**fields)


def an_archive(tmp_path, name='glisteel-ashdown.tar.gz'):
    """A built pack, as ``release-assets.py`` leaves one."""
    where = tmp_path / 'build' / 'ashdown'
    (where / 'trees').mkdir(parents=True)
    (where / 'tileset.json').write_text('{}')
    (where / 'trees' / 'fir.npz').write_bytes(b'npz')
    into = tmp_path / 'dist'
    into.mkdir(exist_ok=True)
    return archive.write(str(where), str(into / name))


class TestInstallingWhatWasBuilt:
    """A release that does not exist yet, tested anyway.

    The archives are on this disk and the URLs in the registry answer nothing,
    so the download is what is left out -- and only the download. The digest is
    checked and the unpacking is bounded exactly as a fetched pack's is.
    """

    def test_it_lands_where_a_fetched_pack_would(self, tmp_path) -> None:
        built = an_archive(tmp_path)
        pack = a_pack(tmp_path, sha256=archive.digest(built))
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        where = publish.install(pack, store, str(tmp_path / 'dist'))
        assert where == store.directory_for(pack)
        assert store.root_for(pack) == where
        assert os.path.isfile(os.path.join(where, 'trees', 'fir.npz'))

    def test_a_pack_already_here_is_left_alone(self, tmp_path) -> None:
        built = an_archive(tmp_path)
        pack = a_pack(tmp_path, sha256=archive.digest(built))
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        publish.install(pack, store, str(tmp_path / 'dist'))
        marker = os.path.join(store.directory_for(pack), 'mine.txt')
        with open(marker, 'w') as handle:
            handle.write('edited')
        publish.install(pack, store, str(tmp_path / 'dist'))
        assert os.path.isfile(marker)

    def test_a_rebuilt_pack_replaces_the_one_here_when_asked(self,
                                                             tmp_path) -> None:
        """What an author does between builds of a world they are still
        authoring: the store holds the last one, and the point is to see the
        next."""
        an_archive(tmp_path)
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        first = a_pack(tmp_path, sha256=archive.digest(
            str(tmp_path / 'dist' / 'glisteel-ashdown.tar.gz')))
        publish.install(first, store, str(tmp_path / 'dist'))

        (tmp_path / 'build' / 'ashdown' / 'trees' / 'oak.npz').write_bytes(b'2')
        rebuilt = archive.write(str(tmp_path / 'build' / 'ashdown'),
                                str(tmp_path / 'dist' / 'glisteel-ashdown.tar.gz'))
        second = a_pack(tmp_path, sha256=archive.digest(rebuilt))
        where = publish.install(second, store, str(tmp_path / 'dist'),
                                replace=True)

        assert os.path.isfile(os.path.join(where, 'trees', 'oak.npz'))

    def test_replacing_leaves_nothing_of_the_pack_it_replaced(self,
                                                              tmp_path) -> None:
        """A file the new world does not have is gone, rather than surviving
        beside it as something no build accounts for."""
        built = an_archive(tmp_path)
        pack = a_pack(tmp_path, sha256=archive.digest(built))
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        stale = os.path.join(publish.install(pack, store, str(tmp_path / 'dist')),
                             'gone.txt')
        with open(stale, 'w') as handle:
            handle.write('from the build before')

        publish.install(pack, store, str(tmp_path / 'dist'), replace=True)

        assert not os.path.exists(stale)

    def test_content_that_is_not_what_was_declared_is_refused(self,
                                                              tmp_path) -> None:
        """The digest is the whole point of recording one."""
        an_archive(tmp_path)
        pack = a_pack(tmp_path, sha256='00' * 32)
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        with pytest.raises(archive.DigestMismatch):
            publish.install(pack, store, str(tmp_path / 'dist'))

    def test_a_pack_nobody_built_says_which(self, tmp_path) -> None:
        (tmp_path / 'dist').mkdir()
        pack = a_pack(tmp_path)
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        with pytest.raises(IOError) as raised:
            publish.install(pack, store, str(tmp_path / 'dist'))
        assert 'glisteel-ashdown.tar.gz' in str(raised.value)

    def test_the_file_it_looks_for_is_the_one_the_registry_names(self,
                                                                 tmp_path
                                                                 ) -> None:
        """A registry's URL is where the file will be; its name is what it is
        called here, so what is installed is what will be served."""
        assert publish.built(a_pack(tmp_path), '/tmp/dist') == \
            os.path.join('/tmp/dist', 'glisteel-ashdown.tar.gz')


class TestAttachingThemToARelease:
    def test_the_repository_comes_from_the_url_the_registry_names(self,
                                                                  tmp_path
                                                                  ) -> None:
        """One source of truth: a pack fetched from a repository is published
        to that repository."""
        assert publish.repository(a_pack(tmp_path).url) == 'mcfletch/glisteel'

    def test_a_url_that_is_not_a_release_asset_says_so(self) -> None:
        with pytest.raises(ValueError):
            publish.repository('https://example.com/packs/ashdown.tar.gz')

    def test_a_tag_that_is_not_there_yet_is_created(self, tmp_path) -> None:
        ran = []

        def runner(argv):
            ran.append(argv)
            return 1 if argv[1] == 'release' and argv[2] == 'view' else 0

        publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                     run=runner)
        assert ran[0][1:4] == ['release', 'view', 'content-v1']
        assert ran[1][1:4] == ['release', 'create', 'content-v1']
        assert 'a.tar.gz' in ran[1]

    def test_a_tag_that_is_there_takes_the_files_it_is_given(self,
                                                             tmp_path) -> None:
        """A rebuilt pack replaces the one on the release rather than sitting
        beside it under a name nothing fetches."""
        ran = []

        def runner(argv):
            ran.append(argv)
            return 0

        publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                     run=runner)
        assert ran[1][1:4] == ['release', 'upload', 'content-v1']
        assert '--clobber' in ran[1]

    def test_an_upload_that_failed_is_said_rather_than_passed_over(self) -> None:
        def runner(argv):
            return 0 if argv[2] == 'view' else 2

        with pytest.raises(IOError):
            publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                         run=runner)

    def test_without_the_command_it_says_what_to_install(self) -> None:
        def runner(argv):
            raise FileNotFoundError(argv[0])

        with pytest.raises(IOError) as raised:
            publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                         run=runner)
        assert publish.GITHUB in str(raised.value)


class TestRunningTheCommand:
    def test_the_status_is_the_command_s_own(self) -> None:
        """What `push` judges by, when nobody passed a runner of their own."""
        import sys
        assert publish._run([sys.executable, '-c', '']) == 0
        assert publish._run([sys.executable, '-c', 'raise SystemExit(3)']) == 3
