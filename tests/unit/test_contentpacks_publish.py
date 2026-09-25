"""Getting a pack from a build directory to where it can be fetched.

The two ends of a release that never reaches the network in a test: installing
what was just built into this machine's own store, so a game can be driven
against content no release carries yet, and the call that attaches the same
files to a release when it is time.
"""

import json
import os
import sys

import pytest

from OpenGLContext.contentpacks import ContentPack, ContentStore, archive, publish, catalog


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

    def after_terminator(self, argv):
        return argv[argv.index('--') + 1:]

    def test_a_tag_that_is_not_there_yet_is_created(self, tmp_path) -> None:
        ran = []

        def ask(argv):
            ran.append(argv)
            return 1, 'release not found\n'

        def runner(argv):
            ran.append(argv)
            return 0

        publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                     run=runner, ask=ask)
        assert ran[0][1:3] == ['release', 'view']
        assert self.after_terminator(ran[0]) == ['content-v1']
        assert ran[1][1:3] == ['release', 'create']
        assert self.after_terminator(ran[1]) == [
            'content-v1', os.path.abspath('a.tar.gz')]

    def test_a_tag_that_is_there_takes_the_files_it_is_given(self,
                                                             tmp_path) -> None:
        """A rebuilt pack replaces the one on the release rather than sitting
        beside it under a name nothing fetches."""
        ran = []

        def runner(argv):
            ran.append(argv)
            return 0

        publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                     run=runner, ask=lambda argv: (0, '{"id": 1}'))
        assert ran[0][1:3] == ['release', 'upload']
        assert '--clobber' in ran[0]
        assert self.after_terminator(ran[0]) == [
            'content-v1', os.path.abspath('a.tar.gz')]

    def test_a_failure_to_ask_is_not_taken_for_a_missing_release(self) -> None:
        """An authentication or network failure is not a release to create."""
        ran = []
        with pytest.raises(IOError) as raised:
            publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                         run=lambda argv: ran.append(argv) or 0,
                         ask=lambda argv: (4, 'HTTP 401: Bad credentials'))
        assert ran == [], 'it went on to create a release'
        assert 'Bad credentials' in str(raised.value)

    def test_a_path_or_tag_like_an_option_stays_an_argument(self) -> None:
        ran = []
        publish.push('mcfletch/glisteel', '-v1', ['-a.tar.gz'],
                     run=lambda argv: ran.append(argv) or 0,
                     ask=lambda argv: (0, '{}'))
        assert self.after_terminator(ran[0]) == [
            '-v1', os.path.abspath('-a.tar.gz')]

    def test_an_upload_that_failed_is_said_rather_than_passed_over(self) -> None:
        with pytest.raises(IOError):
            publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                         run=lambda argv: 2, ask=lambda argv: (0, '{}'))

    def test_without_the_command_it_says_what_to_install(self) -> None:
        def ask(argv):
            raise FileNotFoundError(argv[0])

        with pytest.raises(IOError) as raised:
            publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                         run=lambda argv: 0, ask=ask)
        assert publish.GITHUB in str(raised.value)


class TestRunningTheCommand:
    def test_the_status_is_the_command_s_own(self) -> None:
        """What `push` judges by, when nobody passed a runner of their own."""
        assert publish._run([sys.executable, '-c', '']) == 0
        assert publish._run([sys.executable, '-c', 'raise SystemExit(3)']) == 3

    def test_asking_answers_the_status_and_what_it_printed(self) -> None:
        status, said = publish._ask(
            [sys.executable, '-c',
             'import sys; print("out"); print("err", file=sys.stderr); '
             'raise SystemExit(1)'])
        assert status == 1
        assert 'out' in said and 'err' in said


URL = 'https://github.com/mcfletch/glisteel/releases/download/%s/%s'


def a_release(tmp_path, declare, **named):
    """A game's release command, writing into the test's own directory."""
    fields = dict(namespace='glisteel', url=URL,
                  catalog=str(tmp_path / 'game' / 'packs.json'),
                  declare=declare, into=str(tmp_path / 'dist'),
                  store=lambda: ContentStore('glisteel',
                                             root=str(tmp_path / 'store')))
    fields.update(named)
    (tmp_path / 'game').mkdir(exist_ok=True)
    return publish.Release(**fields)


def a_tree(tmp_path, name, files):
    where = tmp_path / 'art' / name
    for leaf, text in files.items():
        (where / leaf).parent.mkdir(parents=True, exist_ok=True)
        (where / leaf).write_text(text)
    return str(where)


def cars_and_track(tmp_path):
    """Two packs: a base pack of cars, and a track that needs shared art."""
    cars = a_tree(tmp_path, 'cars', {'cars/hero.glb': 'car'})
    art = a_tree(tmp_path, 'forest-art', {'trees/fir.npz': 'fir'})
    track = a_tree(tmp_path, 'ashdown', {'tileset.json': '{}'})

    def declare(build):
        return [
            build.entry('cars', build.archive(cars, 'glisteel-cars'),
                        title='The cars', copyright='ours',
                        marker='cars/hero.glb', base=True),
            build.entry('forest-art', build.archive(art, 'glisteel-art'),
                        title='Forest art', copyright='CC-BY',
                        marker='trees'),
            build.entry('ashdown', build.archive(track, 'glisteel-ashdown'),
                        title='Ashdown', copyright='ours',
                        marker='tileset.json',
                        needs=['glisteel/forest-art'],
                        preview='previews/ashdown.jpg'),
        ]
    return declare


class TestTheReleaseCommand:
    """What every application's ``release-assets.py`` does once it has said
    what to build."""

    def test_the_registry_describes_what_was_built(self, tmp_path) -> None:
        release = a_release(tmp_path, cars_and_track(tmp_path))
        assert publish.main(release, []) == 0
        packs = catalog.load(str(tmp_path / 'dist' / 'packs.json'))
        assert [one.key for one in packs] == [
            'glisteel/cars', 'glisteel/forest-art', 'glisteel/ashdown']
        cars = packs[0]
        assert cars.base
        assert cars.url == URL % ('content-v1', 'glisteel-cars.tar.gz')
        assert cars.sha256 == archive.digest(
            str(tmp_path / 'dist' / 'glisteel-cars.tar.gz'))

    def test_a_build_leaves_the_shipped_registry_alone(self,
                                                       tmp_path) -> None:
        release = a_release(tmp_path, cars_and_track(tmp_path))
        shipped = tmp_path / 'game' / 'packs.json'
        shipped.write_text('{"namespace": "glisteel", "packs": []}')
        publish.main(release, ['--install'])
        assert shipped.read_text() == '{"namespace": "glisteel", "packs": []}'

    def test_the_tag_is_in_every_url(self, tmp_path) -> None:
        release = a_release(tmp_path, cars_and_track(tmp_path))
        publish.main(release, ['--tag', 'content-v9'])
        document = (tmp_path / 'dist' / 'packs.json').read_text()
        assert 'content-v9/glisteel-ashdown.tar.gz' in document
        assert 'content-v1' not in document

    def test_installing_places_each_pack_as_a_download_would(self,
                                                             tmp_path) -> None:
        release = a_release(tmp_path, cars_and_track(tmp_path))
        assert publish.main(release, ['--install']) == 0
        store = release.open_store()
        packs = catalog.merge(catalog.load(
            str(tmp_path / 'dist' / 'packs.json')))
        cars, art, track = packs
        assert store.root_for(cars) is not None
        assert store.root_for(track) is not None
        assert store.root_for(art, within=track) is not None

    def test_reinstalling_replaces_what_is_installed(self, tmp_path) -> None:
        """``--install`` keeps a pack that is already installed; ``--reinstall``
        replaces it with the one just built."""
        release = a_release(tmp_path, cars_and_track(tmp_path))
        publish.main(release, ['--install'])
        store = release.open_store()
        hero = os.path.join(store.root, 'packs', 'glisteel', 'cars', 'cars',
                            'hero.glb')
        with open(hero, 'w') as handle:
            handle.write('edited by hand')
        publish.main(release, ['--install'])
        with open(hero) as handle:
            assert handle.read() == 'edited by hand'
        publish.main(release, ['--reinstall'])
        with open(hero) as handle:
            assert handle.read() == 'car'

    def test_a_refusal_is_said_and_writes_no_registry(self, tmp_path,
                                                      capsys) -> None:
        def declare(build):
            raise SystemExit('no art to pack')
        release = a_release(tmp_path, declare)
        assert publish.main(release, []) == 2
        assert 'no art to pack' in capsys.readouterr().err
        assert not (tmp_path / 'dist' / 'packs.json').exists()

    def test_other_entries_are_kept_where_the_release_says(self,
                                                           tmp_path) -> None:
        """A registry that also lists other people's packages keeps them."""
        shipped = tmp_path / 'game' / 'packs.json'
        shipped.parent.mkdir()
        theirs = {'key': 'glisteel/theirs', 'title': 'Theirs',
                  'url': 'https://example.com/theirs.zip',
                  'directory': 'theirs', 'archive': 'zip',
                  'approximate_bytes': 10, 'copyright': 'theirs',
                  'marker': 'x'}
        shipped.write_text(json.dumps({'namespace': 'glisteel',
                                       'packs': [theirs]}))
        release = a_release(tmp_path, cars_and_track(tmp_path),
                            keep_unbuilt=True)
        publish.main(release, ['--write-registry'])
        written = json.loads(shipped.read_text())
        assert [one['key'] for one in written['packs']] == [
            'glisteel/cars', 'glisteel/forest-art', 'glisteel/ashdown',
            'glisteel/theirs']
        assert written['packs'][-1] == theirs

    def test_pushing_attaches_the_archives_and_the_bundle(self,
                                                          tmp_path) -> None:
        (tmp_path / 'game' / 'previews').mkdir(parents=True)
        (tmp_path / 'game' / 'previews' / 'ashdown.jpg').write_bytes(b'jpg')
        release = a_release(tmp_path, cars_and_track(tmp_path), bundle=True,
                            title='glisteel content')
        ran = []
        assert publish.main(release, ['--push'],
                            run=lambda argv: ran.append(argv) or 0,
                            ask=lambda argv: (0, '{}')) == 0
        attached = [os.path.basename(one) for one in ran[0][ran[0].index(
            'content-v1') + 1:]]
        assert attached == ['glisteel-cars.tar.gz', 'glisteel-art.tar.gz',
                            'glisteel-ashdown.tar.gz',
                            'glisteel-registry.zip']
        assert (tmp_path / 'game' / 'packs.json').read_text() == \
            (tmp_path / 'dist' / 'packs.json').read_text()

    def test_the_bundle_is_the_registry_and_its_pictures(self,
                                                         tmp_path) -> None:
        (tmp_path / 'game' / 'previews').mkdir(parents=True)
        (tmp_path / 'game' / 'previews' / 'ashdown.jpg').write_bytes(b'jpg')
        release = a_release(tmp_path, cars_and_track(tmp_path), bundle=True)
        publish.main(release, [])
        packs = catalog.load_bundle(
            str(tmp_path / 'dist' / 'glisteel-registry.zip'),
            str(tmp_path / 'unpacked'))
        assert packs[-1].preview.endswith('ashdown.jpg')
        assert os.path.isfile(packs[-1].preview)

    def test_the_application_s_own_options_reach_its_declare(self,
                                                             tmp_path) -> None:
        seen = []

        def declare(build):
            seen.append(build.options.depth)
            return []

        def arguments(parser):
            parser.add_argument('--depth', type=int, default=None)
        publish.main(a_release(tmp_path, declare, arguments=arguments),
                     ['--depth', '3'])
        assert seen == [3]

    def test_a_staging_directory_starts_empty(self, tmp_path) -> None:
        found = []

        def declare(build):
            where = build.staging('gallery')
            found.append(sorted(os.listdir(where)))
            with open(os.path.join(where, 'left.txt'), 'w') as handle:
                handle.write('from this build')
            return []
        release = a_release(tmp_path, declare)
        publish.main(release, [])
        publish.main(release, [])
        assert found == [[], []]
