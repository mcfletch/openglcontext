"""The git tags that record what each content bundle was built from.

Real repositories: a working clone with a bare repository as its ``origin``,
so a pushed tag is read back from where it was sent.
"""

import subprocess

import pytest

from OpenGLContext.contentpacks import bundletags
from OpenGLContext.contentpacks.bundletags import BundleRepository


def git(where, *arguments):
    done = subprocess.run(['git', '-C', str(where), *arguments],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repository(tmp_path):
    """A clone with one commit and a bare ``origin``."""
    remote = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True,
                   capture_output=True)
    work = tmp_path / 'work'
    work.mkdir()
    git(work, 'init')
    git(work, 'config', 'user.name', 'Test')
    git(work, 'config', 'user.email', 'test@example.com')
    git(work, 'remote', 'add', 'origin', str(remote))
    (work / 'art.txt').write_text('art')
    git(work, 'add', 'art.txt')
    git(work, 'commit', '-m', 'art')
    return BundleRepository.containing(str(work))


class TestNamingATag:
    def test_a_bundle_s_tags_are_numbered_from_one(self) -> None:
        assert bundletags.next_tag('textures', []) == 'content-textures-v1'

    def test_the_next_tag_follows_the_highest(self) -> None:
        taken = ['content-textures-v2', 'content-textures-v10',
                 'content-textures-v9']
        assert bundletags.next_tag('textures', taken) == 'content-textures-v11'
        assert bundletags.latest_tag('textures', taken) == 'content-textures-v10'

    def test_another_bundle_s_tags_do_not_count(self) -> None:
        taken = ['content-textures-extra-v4', 'content-v1', 'v3.0.0',
                 'content-textures-vx']
        assert bundletags.next_tag('textures', taken) == 'content-textures-v1'
        assert bundletags.latest_tag('textures', taken) is None

    def test_a_bundle_tag_is_told_from_the_shared_tag_of_old(self) -> None:
        assert bundletags.is_bundle_tag('content-gallery-world-v3')
        assert not bundletags.is_bundle_tag('content-v1')
        assert not bundletags.is_bundle_tag('v1.2.3')


class TestFindingTheRepository:
    def test_a_directory_in_a_clone_finds_its_root(self, repository,
                                                   tmp_path) -> None:
        (tmp_path / 'work' / 'pkg').mkdir()
        inside = BundleRepository.containing(str(tmp_path / 'work' / 'pkg'))
        assert inside is not None
        assert inside.root == repository.root

    def test_a_directory_in_no_repository_finds_none(self, tmp_path) -> None:
        assert BundleRepository.containing(str(tmp_path)) is None

    def test_a_directory_that_is_not_there_finds_none(self, tmp_path) -> None:
        assert BundleRepository.containing(str(tmp_path / 'absent')) is None


    def test_without_git_there_is_no_repository(self, tmp_path,
                                                monkeypatch) -> None:
        monkeypatch.setenv('PATH', '')
        assert BundleRepository.containing(str(tmp_path)) is None


class TestTagging:
    def test_a_tag_is_annotated_and_says_what_it_records(self,
                                                         repository) -> None:
        repository.annotate('content-textures-v1',
                            'textures\n\n- sha256: abc')
        assert repository.tags() == ['content-textures-v1']
        assert git(repository.root, 'cat-file', '-t',
                   'content-textures-v1') == 'tag'
        assert '- sha256: abc' in git(repository.root, 'tag', '-n9', '--list',
                                      'content-textures-v1')
        assert git(repository.root, 'rev-list', '-n1',
                   'content-textures-v1') == git(repository.root, 'rev-parse',
                                                 'HEAD')

    def test_tags_that_are_not_bundles_are_not_listed(self,
                                                      repository) -> None:
        git(repository.root, 'tag', 'v1.0.0')
        assert repository.tags() == []

    def test_pushing_sends_the_tag_to_the_remote(self, repository,
                                                 tmp_path) -> None:
        repository.annotate('content-textures-v1', 'textures')
        repository.push(['content-textures-v1'])
        assert 'refs/tags/content-textures-v1' in git(
            tmp_path / 'origin.git', 'show-ref', '--tags')

    def test_pushing_a_tag_the_remote_holds_changes_nothing(self, repository,
                                                            tmp_path) -> None:
        repository.annotate('content-textures-v1', 'textures')
        repository.push(['content-textures-v1'])
        before = git(tmp_path / 'origin.git', 'show-ref', '--tags')
        repository.push(['content-textures-v1'])
        assert git(tmp_path / 'origin.git', 'show-ref', '--tags') == before

    def test_pushing_no_tags_does_not_run_git(self, repository,
                                              monkeypatch) -> None:
        ran = []
        monkeypatch.setattr(bundletags.subprocess, 'run',
                            lambda argv, **_named: ran.append(argv))
        repository.push([])
        assert ran == []

    def test_a_failure_is_raised_with_what_git_said(self, repository) -> None:
        repository.annotate('content-textures-v1', 'textures')
        with pytest.raises(IOError, match='tag failed.*already exists'):
            repository.annotate('content-textures-v1', 'again')

    def test_git_that_is_not_installed_is_said(self, repository,
                                               monkeypatch) -> None:
        monkeypatch.setenv('PATH', '')
        with pytest.raises(IOError, match='git is not installed'):
            repository.tags()


class TestUncommittedChanges:
    def test_a_clean_clone_has_none(self, repository) -> None:
        assert repository.uncommitted() == []

    def test_an_edited_tracked_file_is_named(self, repository,
                                             tmp_path) -> None:
        (tmp_path / 'work' / 'art.txt').write_text('edited')
        assert repository.uncommitted() == [
            str(tmp_path / 'work' / 'art.txt')]

    def test_a_staged_new_file_is_named(self, repository, tmp_path) -> None:
        (tmp_path / 'work' / 'new.txt').write_text('new')
        git(repository.root, 'add', 'new.txt')
        assert repository.uncommitted() == [str(tmp_path / 'work' / 'new.txt')]

    def test_an_untracked_file_is_not_a_change(self, repository,
                                               tmp_path) -> None:
        (tmp_path / 'work' / 'stray.txt').write_text('stray')
        assert repository.uncommitted() == []

    def test_the_command_s_own_output_is_not_a_change(self, repository,
                                                      tmp_path) -> None:
        registry = tmp_path / 'work' / 'art.txt'
        registry.write_text('rewritten by the release command')
        assert repository.uncommitted(ignoring=[str(registry)]) == []


class TestRefusal:
    def test_no_repository_is_refused(self, tmp_path) -> None:
        said = bundletags.refusal(None, str(tmp_path))
        assert said is not None and 'not in a git repository' in said

    def test_a_clean_clone_is_not_refused(self, repository) -> None:
        assert bundletags.refusal(repository, repository.root) is None

    def test_uncommitted_files_are_named(self, repository, tmp_path) -> None:
        (tmp_path / 'work' / 'art.txt').write_text('edited')
        said = bundletags.refusal(repository, repository.root)
        assert said is not None
        assert 'art.txt' in said and 'commit them first' in said

    def test_a_long_list_is_cut_and_counted(self, repository, tmp_path) -> None:
        for number in range(8):
            (tmp_path / 'work' / ('f%d.txt' % number)).write_text('x')
        git(repository.root, 'add', '.')
        said = bundletags.refusal(repository, repository.root)
        assert said is not None and 'and 3 more' in said
