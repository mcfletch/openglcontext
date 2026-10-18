"""Getting a pack from a build directory to where it can be fetched.

The two ends of a release that never reaches the network in a test: installing
what was just built into this machine's own store, so a game can be driven
against content no release carries yet, and the call that attaches the same
files to a release when it is time.
"""

import json
import os
import subprocess
import sys

import pytest

from OpenGLContext.contentpacks import ContentPack, ContentStore, archive, publish, catalog


def a_pack(**named):
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
        pack = a_pack(sha256=archive.digest(built))
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        where = publish.install(pack, store, str(tmp_path / 'dist'))
        assert where == store.directory_for(pack)
        assert store.root_for(pack) == where
        assert os.path.isfile(os.path.join(where, 'trees', 'fir.npz'))

    def test_a_pack_already_here_is_left_alone(self, tmp_path) -> None:
        built = an_archive(tmp_path)
        pack = a_pack(sha256=archive.digest(built))
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
        first = a_pack(sha256=archive.digest(
            str(tmp_path / 'dist' / 'glisteel-ashdown.tar.gz')))
        publish.install(first, store, str(tmp_path / 'dist'))

        (tmp_path / 'build' / 'ashdown' / 'trees' / 'oak.npz').write_bytes(b'2')
        rebuilt = archive.write(str(tmp_path / 'build' / 'ashdown'),
                                str(tmp_path / 'dist' / 'glisteel-ashdown.tar.gz'))
        second = a_pack(sha256=archive.digest(rebuilt))
        where = publish.install(second, store, str(tmp_path / 'dist'),
                                replace=True)

        assert os.path.isfile(os.path.join(where, 'trees', 'oak.npz'))

    def test_replacing_leaves_nothing_of_the_pack_it_replaced(self,
                                                              tmp_path) -> None:
        """A file the new world does not have is gone, rather than surviving
        beside it as something no build accounts for."""
        built = an_archive(tmp_path)
        pack = a_pack(sha256=archive.digest(built))
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
        pack = a_pack(sha256='00' * 32)
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        with pytest.raises(archive.DigestMismatch):
            publish.install(pack, store, str(tmp_path / 'dist'))

    def test_a_pack_nobody_built_says_which(self, tmp_path) -> None:
        (tmp_path / 'dist').mkdir()
        pack = a_pack()
        store = ContentStore('glisteel', root=str(tmp_path / 'store'))
        with pytest.raises(IOError) as raised:
            publish.install(pack, store, str(tmp_path / 'dist'))
        assert 'glisteel-ashdown.tar.gz' in str(raised.value)

    def test_the_file_it_looks_for_is_the_one_the_registry_names(self
                                                                 ) -> None:
        """A registry's URL is where the file will be; its name is what it is
        called here, so what is installed is what will be served."""
        assert publish.built(a_pack(), '/tmp/dist') == \
            os.path.join('/tmp/dist', 'glisteel-ashdown.tar.gz')


class TestAttachingThemToARelease:
    def test_the_repository_comes_from_the_url_the_registry_names(self
                                                                  ) -> None:
        """One source of truth: a pack fetched from a repository is published
        to that repository."""
        assert publish.repository(a_pack().url) == 'mcfletch/glisteel'

    def test_a_url_that_is_not_a_release_asset_says_so(self) -> None:
        with pytest.raises(ValueError):
            publish.repository('https://example.com/packs/ashdown.tar.gz')

    def test_the_tag_comes_from_the_url_the_registry_names(self) -> None:
        assert publish.release_tag(a_pack().url) == 'content-v1'

    def test_a_url_that_names_no_tag_is_not_a_release_asset(self) -> None:
        with pytest.raises(ValueError):
            publish.release_tag('https://github.com/mcfletch/glisteel/releases')

    def test_the_files_a_release_lacks_are_the_ones_not_named_on_it(self
                                                                    ) -> None:
        said = json.dumps({'assets': [{'name': 'a.tar.gz'}]})
        assert publish.missing_assets(
            'mcfletch/glisteel', 'content-a-v1', ['/x/a.tar.gz', '/x/b.tar.gz'],
            ask=lambda _argv: (0, said)) == ['/x/b.tar.gz']

    def test_a_tag_with_no_release_lacks_every_file(self) -> None:
        assert publish.missing_assets(
            'mcfletch/glisteel', 'content-a-v1', ['a.tar.gz'],
            ask=lambda _argv: (1, 'release not found')) == ['a.tar.gz']

    def test_a_failure_to_ask_is_not_taken_for_a_missing_release_here_either(
            self) -> None:
        with pytest.raises(IOError, match='bad credentials'):
            publish.missing_assets(
                'mcfletch/glisteel', 'content-a-v1', ['a.tar.gz'],
                ask=lambda _argv: (4, 'bad credentials'))

    def test_without_the_command_asking_says_what_to_install(self) -> None:
        def absent(_argv):
            raise FileNotFoundError('gh')
        with pytest.raises(IOError, match='cli.github.com'):
            publish.missing_assets('mcfletch/glisteel', 'content-a-v1',
                                   ['a.tar.gz'], ask=absent)

    def after_terminator(self, argv):
        return argv[argv.index('--') + 1:]

    def test_a_tag_that_is_not_there_yet_is_created(self) -> None:
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

    def test_a_tag_that_is_there_takes_the_files_it_is_given(self) -> None:
        """A rebuilt pack replaces the one on the release rather than sitting
        beside it under a name nothing fetches."""
        ran = []

        def runner(argv):
            ran.append(argv)
            return 0

        publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                     run=runner, ask=lambda _argv: (0, '{"id": 1}'))
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
                         ask=lambda _argv: (4, 'HTTP 401: Bad credentials'))
        assert ran == [], 'it went on to create a release'
        assert 'Bad credentials' in str(raised.value)

    def test_a_path_or_tag_like_an_option_stays_an_argument(self) -> None:
        ran = []
        publish.push('mcfletch/glisteel', '-v1', ['-a.tar.gz'],
                     run=lambda argv: ran.append(argv) or 0,
                     ask=lambda _argv: (0, '{}'))
        assert self.after_terminator(ran[0]) == [
            '-v1', os.path.abspath('-a.tar.gz')]

    def test_an_upload_that_failed_is_said_rather_than_passed_over(self) -> None:
        with pytest.raises(IOError):
            publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                         run=lambda _argv: 2, ask=lambda _argv: (0, '{}'))

    def test_without_the_command_it_says_what_to_install(self) -> None:
        def ask(argv):
            raise FileNotFoundError(argv[0])

        with pytest.raises(IOError) as raised:
            publish.push('mcfletch/glisteel', 'content-v1', ['a.tar.gz'],
                         run=lambda _argv: 0, ask=ask)
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


def git(where, *arguments):
    done = subprocess.run(['git', '-C', str(where), *arguments],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def a_clone(tmp_path):
    """The game's repository: one commit, and a bare ``origin`` to push to."""
    remote = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True,
                   capture_output=True)
    game = tmp_path / 'game'
    game.mkdir(exist_ok=True)
    git(game, 'init')
    git(game, 'config', 'user.name', 'Test')
    git(game, 'config', 'user.email', 'test@example.com')
    git(game, 'remote', 'add', 'origin', str(remote))
    (game / 'source.txt').write_text('source')
    git(game, 'add', 'source.txt')
    git(game, 'commit', '-m', 'source')
    return game


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
        assert cars.url == URL % ('content-glisteel-cars-v1',
                                  'glisteel-cars.tar.gz')
        assert cars.sha256 == archive.digest(
            str(tmp_path / 'dist' / 'glisteel-cars.tar.gz'))

    def test_a_build_leaves_the_shipped_registry_alone(self,
                                                       tmp_path) -> None:
        release = a_release(tmp_path, cars_and_track(tmp_path))
        shipped = tmp_path / 'game' / 'packs.json'
        shipped.write_text('{"namespace": "glisteel", "packs": []}')
        publish.main(release, ['--install'])
        assert shipped.read_text() == '{"namespace": "glisteel", "packs": []}'

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
        def declare(_build):
            raise SystemExit('no art to pack')
        release = a_release(tmp_path, declare)
        assert publish.main(release, []) == 2
        assert 'no art to pack' in capsys.readouterr().err
        assert not (tmp_path / 'dist' / 'packs.json').exists()

    def test_other_entries_are_kept_where_the_release_says(self,
                                                           tmp_path) -> None:
        """A registry that also lists other people's packages keeps them."""
        shipped = tmp_path / 'game' / 'packs.json'
        a_clone(tmp_path)
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


def one_bundle(tmp_path, text='car'):
    """A release of one bundle whose content is ``text``."""
    cars = a_tree(tmp_path, 'cars', {'cars/hero.glb': text})

    def declare(build):
        return [build.entry('cars', build.archive(cars, 'glisteel-cars'),
                            title='The cars', copyright='ours',
                            marker='cars/hero.glb', base=True)]
    return declare


def tags_of(game):
    return git(game, 'tag', '--list', 'content-*').split()


class TestEachBundleHasItsOwnTag:
    """A bundle is released on its own schedule, under a tag that names it."""

    def test_every_url_names_the_tag_of_the_bundle_it_serves(self,
                                                             tmp_path) -> None:
        release = a_release(tmp_path, cars_and_track(tmp_path))
        publish.main(release, [])
        urls = {one.key: one.url for one in catalog.load(
            str(tmp_path / 'dist' / 'packs.json'))}
        assert urls == {
            'glisteel/cars': URL % ('content-glisteel-cars-v1',
                                    'glisteel-cars.tar.gz'),
            'glisteel/forest-art': URL % ('content-glisteel-art-v1',
                                          'glisteel-art.tar.gz'),
            'glisteel/ashdown': URL % ('content-glisteel-ashdown-v1',
                                       'glisteel-ashdown.tar.gz')}

    def test_a_draft_build_makes_no_tag(self, tmp_path) -> None:
        game = a_clone(tmp_path)
        publish.main(a_release(tmp_path, cars_and_track(tmp_path)), [])
        assert tags_of(game) == []

    def test_shipping_the_registry_tags_each_bundle_annotated(self,
                                                              tmp_path) -> None:
        game = a_clone(tmp_path)
        publish.main(a_release(tmp_path, cars_and_track(tmp_path)),
                     ['--write-registry'])
        assert tags_of(game) == ['content-glisteel-art-v1',
                                 'content-glisteel-ashdown-v1',
                                 'content-glisteel-cars-v1']
        assert git(game, 'cat-file', '-t', 'content-glisteel-cars-v1') == 'tag'
        assert git(game, 'rev-list', '-n1', 'content-glisteel-cars-v1') == \
            git(game, 'rev-parse', 'HEAD')

    def test_the_tag_says_how_to_make_the_bundle_again(self, tmp_path) -> None:
        game = a_clone(tmp_path)
        publish.main(a_release(tmp_path, one_bundle(tmp_path)),
                     ['--write-registry'])
        said = git(game, 'for-each-ref', '--format=%(contents)',
                   'refs/tags/content-glisteel-cars-v1')
        digest = archive.digest(str(tmp_path / 'dist' / 'glisteel-cars.tar.gz'))
        assert '- archive: glisteel-cars.tar.gz' in said
        assert '- sha256: %s' % (digest,) in said
        assert '- bytes: %d' % os.path.getsize(
            tmp_path / 'dist' / 'glisteel-cars.tar.gz') in said
        assert '- built with: ' in said and '--write-registry' in said

    def test_a_bundle_that_has_not_changed_keeps_its_tag(self,
                                                         tmp_path) -> None:
        game = a_clone(tmp_path)
        release = a_release(tmp_path, one_bundle(tmp_path))
        publish.main(release, ['--write-registry'])
        publish.main(release, ['--write-registry'])
        assert tags_of(game) == ['content-glisteel-cars-v1']

    def test_a_bundle_that_has_changed_takes_the_next_number(self,
                                                             tmp_path) -> None:
        game = a_clone(tmp_path)
        publish.main(a_release(tmp_path, one_bundle(tmp_path)),
                     ['--write-registry'])
        release = a_release(tmp_path, one_bundle(tmp_path, 'a new car'))
        publish.main(release, ['--write-registry'])
        assert tags_of(game) == ['content-glisteel-cars-v1',
                                 'content-glisteel-cars-v2']
        shipped = catalog.load(str(tmp_path / 'game' / 'packs.json'))
        assert shipped[0].url == URL % ('content-glisteel-cars-v2',
                                        'glisteel-cars.tar.gz')

    def test_a_change_to_one_bundle_leaves_the_others_where_they_are(
            self, tmp_path) -> None:
        game = a_clone(tmp_path)
        declare = cars_and_track(tmp_path)
        publish.main(a_release(tmp_path, declare), ['--write-registry'])
        (tmp_path / 'art' / 'ashdown' / 'tileset.json').write_text('{"v": 2}')
        publish.main(a_release(tmp_path, declare), ['--write-registry'])
        assert tags_of(game) == [
            'content-glisteel-art-v1', 'content-glisteel-ashdown-v1',
            'content-glisteel-ashdown-v2', 'content-glisteel-cars-v1']

    def test_a_draft_that_changed_is_named_for_the_number_after_the_shipped(
            self, tmp_path) -> None:
        a_clone(tmp_path)
        publish.main(a_release(tmp_path, one_bundle(tmp_path)),
                     ['--write-registry'])
        publish.main(a_release(tmp_path, one_bundle(tmp_path, 'newer')), [])
        draft = catalog.load(str(tmp_path / 'dist' / 'packs.json'))
        assert draft[0].url.endswith(
            'content-glisteel-cars-v2/glisteel-cars.tar.gz')

    def test_a_bundle_the_registry_names_under_the_old_shared_tag_keeps_it(
            self, tmp_path) -> None:
        game = a_clone(tmp_path)
        publish.main(a_release(tmp_path, one_bundle(tmp_path)), [])
        built = catalog.load(str(tmp_path / 'dist' / 'packs.json'))[0]
        shipped = json.loads((tmp_path / 'dist' / 'packs.json').read_text())
        shipped['packs'][0]['url'] = URL % ('content-v1',
                                            'glisteel-cars.tar.gz')
        (tmp_path / 'game' / 'packs.json').write_text(json.dumps(shipped))

        publish.main(a_release(tmp_path, one_bundle(tmp_path)),
                     ['--write-registry'])

        assert built.sha256 == catalog.load(
            str(tmp_path / 'game' / 'packs.json'))[0].sha256
        assert tags_of(game) == []
        assert 'content-v1/glisteel-cars.tar.gz' in (
            tmp_path / 'game' / 'packs.json').read_text()

    def test_an_entry_served_from_elsewhere_names_no_tag_of_ours(
            self, tmp_path) -> None:
        game = a_clone(tmp_path)
        elsewhere = {'key': 'glisteel/theirs', 'title': 'Theirs',
                     'url': 'https://example.com/glisteel-cars.tar.gz',
                     'directory': 'theirs', 'archive': 'tar',
                     'approximate_bytes': 10, 'copyright': 'theirs',
                     'marker': 'x', 'sha256': '00' * 32}
        (game / 'packs.json').write_text(json.dumps(
            {'namespace': 'glisteel', 'packs': [elsewhere]}))
        git(game, 'add', 'packs.json')
        git(game, 'commit', '-m', 'registry')
        publish.main(a_release(tmp_path, one_bundle(tmp_path)),
                     ['--write-registry'])
        assert tags_of(game) == ['content-glisteel-cars-v1']

    def test_a_tag_that_is_numbered_is_not_taken_twice(self, tmp_path) -> None:
        """A tag made on another clone and fetched is counted."""
        game = a_clone(tmp_path)
        git(game, 'tag', '-a', '-m', 'elsewhere', 'content-glisteel-cars-v4')
        publish.main(a_release(tmp_path, one_bundle(tmp_path)),
                     ['--write-registry'])
        assert tags_of(game) == ['content-glisteel-cars-v4',
                                 'content-glisteel-cars-v5']


class TestShippingNeedsATaggableTree:
    def test_a_directory_in_no_repository_is_refused(self, tmp_path,
                                                     capsys) -> None:
        release = a_release(tmp_path, one_bundle(tmp_path))
        assert publish.main(release, ['--write-registry']) == 2
        assert 'not in a git repository' in capsys.readouterr().err
        assert not (tmp_path / 'game' / 'packs.json').exists()

    def test_uncommitted_files_are_refused_before_anything_is_built(
            self, tmp_path, capsys) -> None:
        game = a_clone(tmp_path)
        (game / 'source.txt').write_text('edited')
        built = []

        def declare(build):
            built.append(True)
            return one_bundle(tmp_path)(build)
        assert publish.main(a_release(tmp_path, declare), ['--push']) == 2
        assert 'source.txt' in capsys.readouterr().err
        assert built == []
        assert tags_of(game) == []

    def test_the_registry_the_command_writes_is_not_an_uncommitted_file(
            self, tmp_path) -> None:
        game = a_clone(tmp_path)
        (game / 'packs.json').write_text('{"namespace": "glisteel", "packs": []}')
        git(game, 'add', 'packs.json')
        git(game, 'commit', '-m', 'registry')
        release = a_release(tmp_path, one_bundle(tmp_path))
        assert publish.main(release, ['--write-registry']) == 0
        assert publish.main(release, ['--write-registry']) == 0

    def test_a_draft_build_needs_no_repository(self, tmp_path) -> None:
        release = a_release(tmp_path, one_bundle(tmp_path))
        assert publish.main(release, []) == 0


class Gh:
    """The GitHub CLI, standing in: a release is a tag and some file names."""

    def __init__(self, releases=None):
        self.releases = releases if releases is not None else {}
        self.ran = []

    def ask(self, argv):
        tag = argv[argv.index('--') + 1]
        if tag not in self.releases:
            return 1, 'release not found'
        return 0, json.dumps({'assets': [{'name': name}
                                         for name in self.releases[tag]]})

    def run(self, argv):
        self.ran.append(argv)
        tag = argv[argv.index('--') + 1]
        names = [os.path.basename(one) for one in argv[argv.index('--') + 2:]]
        self.releases.setdefault(tag, []).extend(names)
        return 0

    def attached(self):
        """Per command, the tag and the file names it attached."""
        return [(argv[argv.index('--') + 1],
                 [os.path.basename(one)
                  for one in argv[argv.index('--') + 2:]])
                for argv in self.ran]


class TestPublishingEachBundleUnderItsTag:
    def test_each_bundle_is_attached_to_its_own_release(self,
                                                        tmp_path) -> None:
        a_clone(tmp_path)
        gh = Gh()
        release = a_release(tmp_path, cars_and_track(tmp_path))
        assert publish.main(release, ['--push'], run=gh.run, ask=gh.ask) == 0
        assert gh.attached() == [
            ('content-glisteel-cars-v1', ['glisteel-cars.tar.gz']),
            ('content-glisteel-art-v1', ['glisteel-art.tar.gz']),
            ('content-glisteel-ashdown-v1', ['glisteel-ashdown.tar.gz'])]
        assert (tmp_path / 'game' / 'packs.json').read_text() == \
            (tmp_path / 'dist' / 'packs.json').read_text()

    def test_the_tags_are_on_the_remote_before_the_releases_are_made(
            self, tmp_path) -> None:
        """``gh release create`` makes a tag that is not there, at the head of
        the default branch and not annotated."""
        a_clone(tmp_path)
        seen = []

        class Watching(Gh):
            def run(self, argv):
                seen.append(git(tmp_path / 'origin.git', 'tag').split())
                return super().run(argv)
        gh = Watching()
        publish.main(a_release(tmp_path, one_bundle(tmp_path)), ['--push'],
                     run=gh.run, ask=gh.ask)
        assert seen == [['content-glisteel-cars-v1']]
        assert git(tmp_path / 'origin.git', 'cat-file', '-t',
                   'content-glisteel-cars-v1') == 'tag'

    def test_a_bundle_already_on_its_release_is_not_attached_again(
            self, tmp_path) -> None:
        a_clone(tmp_path)
        gh = Gh()
        release = a_release(tmp_path, cars_and_track(tmp_path))
        publish.main(release, ['--push'], run=gh.run, ask=gh.ask)
        gh.ran.clear()
        publish.main(release, ['--push'], run=gh.run, ask=gh.ask)
        assert gh.ran == []

    def test_a_registry_shipped_by_an_earlier_run_is_still_published(
            self, tmp_path) -> None:
        a_clone(tmp_path)
        gh = Gh()
        release = a_release(tmp_path, one_bundle(tmp_path))
        publish.main(release, ['--write-registry'])
        publish.main(release, ['--push'], run=gh.run, ask=gh.ask)
        assert gh.attached() == [
            ('content-glisteel-cars-v1', ['glisteel-cars.tar.gz'])]

    def test_only_the_bundle_that_changed_is_published(self,
                                                       tmp_path) -> None:
        a_clone(tmp_path)
        gh = Gh()
        declare = cars_and_track(tmp_path)
        publish.main(a_release(tmp_path, declare), ['--push'],
                     run=gh.run, ask=gh.ask)
        gh.ran.clear()
        (tmp_path / 'art' / 'ashdown' / 'tileset.json').write_text('{"v": 2}')
        publish.main(a_release(tmp_path, declare), ['--push'],
                     run=gh.run, ask=gh.ask)
        assert gh.attached() == [
            ('content-glisteel-ashdown-v2', ['glisteel-ashdown.tar.gz'])]

    def test_the_registry_bundle_has_a_tag_of_its_own(self, tmp_path) -> None:
        (tmp_path / 'game' / 'previews').mkdir(parents=True)
        game = a_clone(tmp_path)
        (game / 'previews' / 'ashdown.jpg').write_bytes(b'jpg')
        git(game, 'add', 'previews')
        git(game, 'commit', '-m', 'previews')
        gh = Gh()
        release = a_release(tmp_path, cars_and_track(tmp_path), bundle=True,
                            title='glisteel content')
        publish.main(release, ['--push'], run=gh.run, ask=gh.ask)
        assert gh.attached()[-1] == (
            'content-glisteel-registry-v1', ['glisteel-registry.zip'])
        assert 'content-glisteel-registry-v1' in tags_of(game)
        assert 'glisteel-registry.zip' not in [
            name for tag, names in gh.attached()[:-1] for name in names]

    def test_the_registry_bundle_is_reissued_when_the_registry_changes(
            self, tmp_path) -> None:
        game = a_clone(tmp_path)
        gh = Gh()
        publish.main(a_release(tmp_path, one_bundle(tmp_path), bundle=True),
                     ['--push'], run=gh.run, ask=gh.ask)
        publish.main(a_release(tmp_path, one_bundle(tmp_path), bundle=True),
                     ['--push'], run=gh.run, ask=gh.ask)
        assert tags_of(game).count('content-glisteel-registry-v2') == 0
        publish.main(a_release(tmp_path, one_bundle(tmp_path, 'newer'),
                               bundle=True),
                     ['--push'], run=gh.run, ask=gh.ask)
        assert 'content-glisteel-registry-v2' in tags_of(game)

    def test_the_release_is_titled_for_the_application_and_the_tag(
            self, tmp_path) -> None:
        a_clone(tmp_path)
        gh = Gh()
        release = a_release(tmp_path, one_bundle(tmp_path),
                            title='glisteel content')
        publish.main(release, ['--push'], run=gh.run, ask=gh.ask)
        create = gh.ran[0]
        assert create[create.index('--title') + 1] == \
            'glisteel content content-glisteel-cars-v1'
