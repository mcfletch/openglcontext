"""Turning an installed application into a Debian package."""

import contextlib
import gzip
import io
import os
import subprocess
import tarfile

import pytest

from OpenGLContext.packaging import deb


class TestVersions:
    """PEP 440 is not Debian's ordering, and a pre-release has to sort first."""

    @pytest.mark.parametrize('given,expected', [
        ('3.0.0', '3.0.0'),
        ('0.1.0a1', '0.1.0~a1'),
        ('2.3.4b3', '2.3.4~b3'),
        ('1.0rc2', '1.0~rc2'),
        ('1.0.dev5', '1.0~dev5'),
        ('1.0a1.dev5', '1.0~a1~dev5'),
        ('1.0.post1', '1.0.post1'),
        ('1.2.3+g0abcdef', '1.2.3+g0abcdef'),
    ])
    def test_upstream_version(self, given, expected):
        assert deb.debian_version(given) == expected + '-1'

    def test_the_revision_is_the_packaging_of_one_upstream_release(self):
        assert deb.debian_version('1.0', revision=3) == '1.0-3'

    def test_a_prerelease_sorts_before_the_release_it_leads_to(self):
        """The whole point of the tilde: 0.1.0~a1 is older than 0.1.0."""
        older = deb.debian_version('0.1.0a1')
        newer = deb.debian_version('0.1.0')
        if not deb.have_dpkg():
            pytest.skip('dpkg is not installed to arbitrate')
        assert subprocess.call(
            ['dpkg', '--compare-versions', older, 'lt', newer]) == 0

    def test_a_version_debian_could_not_hold_is_refused(self):
        with pytest.raises(ValueError):
            deb.debian_version('not a version!')


class TestArchitecture:

    @pytest.mark.parametrize('tag,expected', [
        ('linux-x86_64', 'amd64'),
        ('linux-aarch64', 'arm64'),
        ('linux-armv7l', 'armhf'),
        ('linux-i686', 'i386'),
    ])
    def test_the_interpreters_platform_names_the_architecture(self, tag, expected):
        assert deb.debian_architecture(tag) == expected

    def test_an_architecture_with_no_debian_name_is_refused(self):
        """Better than writing `all` on a package full of compiled code."""
        with pytest.raises(ValueError, match='sparc'):
            deb.debian_architecture('linux-sparc64')


class TestControl:

    def test_the_fields_are_written_in_the_order_dpkg_expects(self):
        text = deb.control_paragraph({
            'Description': 'a game',
            'Package': 'glisteel',
            'Version': '1.0-1',
            'Architecture': 'amd64',
            'Maintainer': 'A Person <a@example.com>',
        })
        lines = [line.split(':')[0] for line in text.splitlines()]
        assert lines[0] == 'Package'
        assert lines.index('Version') < lines.index('Description')
        assert lines[-1] == 'Description'

    def test_the_paragraph_ends_with_one_newline(self):
        text = deb.control_paragraph({
            'Package': 'x', 'Version': '1-1', 'Architecture': 'amd64',
            'Maintainer': 'A <a@b.c>', 'Description': 'thing',
        })
        assert text.endswith('thing\n')
        assert not text.endswith('\n\n')

    def test_a_field_with_no_value_is_left_out(self):
        text = deb.control_paragraph({
            'Package': 'x', 'Version': '1-1', 'Architecture': 'amd64',
            'Maintainer': 'A <a@b.c>', 'Description': 'thing', 'Homepage': '',
        })
        assert 'Homepage' not in text

    def test_a_missing_required_field_is_refused(self):
        with pytest.raises(ValueError, match='Maintainer'):
            deb.control_paragraph({
                'Package': 'x', 'Version': '1-1', 'Architecture': 'amd64',
                'Description': 'thing',
            })

    def test_a_description_is_a_summary_and_an_indented_body(self):
        value = deb.describe('drive a car', 'A racing game.\n\nOn a baked world.')
        lines = value.split('\n')
        assert lines[0] == 'drive a car'
        assert lines[1] == ' A racing game.'
        assert ' .' in lines, 'a blank line in a Description is a lone full stop'
        assert lines[-1] == ' On a baked world.'

    def test_a_description_with_no_body_is_just_the_summary(self):
        assert deb.describe('drive a car') == 'drive a car'


class TestArchive:

    def _tree(self, tmp_path):
        root = tmp_path / 'data'
        (root / 'usr' / 'games').mkdir(parents=True)
        (root / 'usr' / 'games' / 'drive').write_text('#!/bin/sh\nexec true\n')
        os.chmod(str(root / 'usr' / 'games' / 'drive'), 0o755)
        return root

    def test_the_sums_name_every_file_and_no_directory(self, tmp_path):
        root = self._tree(tmp_path)
        sums = deb.md5sums(str(root))
        assert sums.split()[1] == 'usr/games/drive'
        assert len(sums.splitlines()) == 1

    def test_the_installed_size_is_reported_in_kibibytes(self, tmp_path):
        root = self._tree(tmp_path)
        assert deb.installed_size(str(root)) >= 1

    def test_a_written_package_is_an_ar_archive_dpkg_can_read(self, tmp_path):
        root = self._tree(tmp_path)
        control = deb.control_paragraph({
            'Package': 'drive-test', 'Version': '1.0-1', 'Architecture': 'all',
            'Maintainer': 'A Person <a@example.com>', 'Description': 'a test',
        })
        path = str(tmp_path / 'drive-test.deb')
        deb.write_deb(str(root), {'control': control, 'md5sums': deb.md5sums(str(root))},
                      path)

        with open(path, 'rb') as stream:
            assert stream.read(8) == b'!<arch>\n'
        members = dict(deb.read_deb(path))
        assert members['debian-binary'] == b'2.0\n'
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(members['control.tar.gz']))) as tar:
            assert './control' in tar.getnames()
            assert './md5sums' in tar.getnames()

    def test_the_files_in_the_package_are_owned_by_root(self, tmp_path):
        """Built by an ordinary user; installed as the system's own files."""
        root = self._tree(tmp_path)
        path = str(tmp_path / 'x.deb')
        deb.write_deb(str(root), {'control': 'Package: x\n'}, path)
        members = dict(deb.read_deb(path))
        with tarfile.open(fileobj=io.BytesIO(members['data.tar.xz']), mode='r:xz') as tar:
            entry = tar.getmember('./usr/games/drive')
            assert (entry.uid, entry.gid) == (0, 0)
            assert (entry.uname, entry.gname) == ('root', 'root')
            assert entry.mode == 0o755

    def test_dpkg_reads_back_what_was_written(self, tmp_path):
        if not deb.have_dpkg():
            pytest.skip('dpkg-deb is not installed to arbitrate')
        root = self._tree(tmp_path)
        control = deb.control_paragraph({
            'Package': 'drive-test', 'Version': '1.0-1', 'Architecture': 'all',
            'Maintainer': 'A Person <a@example.com>', 'Description': 'a test',
        })
        path = str(tmp_path / 'drive-test.deb')
        deb.write_deb(str(root), {'control': control, 'md5sums': deb.md5sums(str(root))},
                      path)
        listing = subprocess.check_output(['dpkg-deb', '--contents', path], text=True)
        assert 'usr/games/drive' in listing
        info = subprocess.check_output(['dpkg-deb', '--field', path, 'Package'], text=True)
        assert info.strip() == 'drive-test'


class TestNames:

    @pytest.mark.parametrize('given,expected', [
        ('glisteel', 'glisteel'),
        ('twig-bb', 'twig-bb'),
        ('twig_bb', 'twig-bb'),
        ('OpenGLContext', 'openglcontext'),
        ('OpenGLContext-editor', 'openglcontext-editor'),
    ])
    def test_a_distribution_name_becomes_a_package_name(self, given, expected):
        """Debian names are lower case and hold no underscore."""
        assert deb.debian_name(given) == expected

    def test_a_name_debian_would_refuse_is_refused_here(self):
        with pytest.raises(ValueError):
            deb.debian_name('-leading-dash')

    def test_a_name_needs_more_than_one_character(self):
        with pytest.raises(ValueError):
            deb.debian_name('x')


class TestDesktopEntry:

    def test_it_names_the_command_and_the_menu_section(self):
        text = deb.desktop_entry(
            name='GLinting Steel', command='/usr/games/glisteel',
            summary='drive a car', categories='Game;ActionGame;')
        assert text.startswith('[Desktop Entry]\n')
        assert 'Exec=/usr/games/glisteel\n' in text
        assert 'Name=GLinting Steel\n' in text
        assert 'Comment=drive a car\n' in text
        assert 'Categories=Game;ActionGame;\n' in text
        assert 'Type=Application\n' in text

    def test_without_an_icon_of_its_own_it_names_a_stock_one(self):
        """A dangling Icon draws a broken image; the stock name always resolves."""
        text = deb.desktop_entry(name='X', command='/usr/games/x', summary='s')
        assert 'Icon=applications-games\n' in text

    def test_an_icon_of_its_own_is_named_by_the_package(self):
        text = deb.desktop_entry(name='X', command='/usr/games/x', summary='s',
                                 icon='glisteel')
        assert 'Icon=glisteel\n' in text


class TestSummarising:
    """A control file wants a paragraph, and a README is not one."""

    README = (
        '# GLinting Steel\n'
        '\n'
        'A racing game on OpenGLContext: a car, a forest road, and a world too\n'
        'big to load.\n'
        '\n'
        '```bash\n'
        'pip install glisteel\n'
        '```\n'
        '\n'
        '## Driving\n'
        '\n'
        'Steer with the arrow keys.\n'
    )

    def test_the_leading_prose_is_what_is_kept(self):
        assert deb.summarise(self.README) == (
            'A racing game on OpenGLContext: a car, a forest road, and a world too\n'
            'big to load.')

    def test_a_title_is_dropped_because_the_package_already_has_a_name(self):
        assert not deb.summarise(self.README).startswith('#')

    def test_it_stops_at_the_first_thing_that_is_not_prose(self):
        assert 'pip install' not in deb.summarise(self.README)
        assert 'Driving' not in deb.summarise(self.README)

    def test_a_long_paragraph_is_cut_to_a_readable_length(self):
        text = '\n'.join('line %d' % index for index in range(50))
        assert len(deb.summarise(text, lines=6).splitlines()) == 6

    def test_a_description_that_is_only_a_title_comes_back_empty(self):
        assert deb.summarise('# GLinting Steel\n') == ''

    def test_nothing_summarises_to_nothing(self):
        assert deb.summarise('') == ''


class TestMaintainer:

    def test_a_quoted_name_is_unquoted(self):
        """Metadata round-trips an author through an email header."""
        assert deb.maintainer_field('"Mike C. Fletcher" <mcfletch@vrplumber.com>') == (
            'Mike C. Fletcher <mcfletch@vrplumber.com>')

    def test_a_plain_name_and_address_is_left_alone(self):
        assert deb.maintainer_field('A Person <a@example.com>') == (
            'A Person <a@example.com>')

    def test_an_address_on_its_own_is_kept(self):
        assert deb.maintainer_field('a@example.com') == 'a@example.com'

    def test_no_author_at_all_is_refused(self):
        with pytest.raises(ValueError):
            deb.maintainer_field('')


class TestWhichBackendThePackageIsFor:
    """Tk lives in the interpreter, so a package for a Tk application has to
    keep what a package for any other one throws away."""

    def test_the_command_line_takes_a_backend(self):
        # The parser is built inside main(), so it is read from --help rather
        # than reached for directly.
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            with pytest.raises(SystemExit):
                deb.main(['--help'])
        assert '--backend' in printed.getvalue()

    def test_a_backend_nobody_has_heard_of_is_refused(self, capsys):
        with pytest.raises(SystemExit):
            deb.main(['--runtime', 'runtime', '--backend', 'nonesuch'])
        assert 'nonesuch' in capsys.readouterr().err

    def test_a_tk_package_is_built_keeping_tk(self, monkeypatch):
        asked = {}

        def built(**named):
            asked.update(named)
            return '/dist/demo_1.0-1_amd64.deb'

        monkeypatch.setattr(deb, 'build', lambda **named: built(**named))
        deb.main(['--runtime', 'runtime', '--backend', 'tk', '--quiet'])
        assert asked['keep_backends'] == ['tk']

    def test_a_package_that_names_no_backend_keeps_none(self, monkeypatch):
        asked = {}
        monkeypatch.setattr(deb, 'build',
                            lambda **named: (asked.update(named), '/x.deb')[1])
        deb.main(['--runtime', 'runtime', '--quiet'])
        assert asked['keep_backends'] == []

    def test_the_environment_is_built_with_those_patterns(self, monkeypatch,
                                                          tmp_path):
        """Everything past the environment needs a real one, so the build is
        stopped where the question is answered."""
        from OpenGLContext.packaging import appdir

        class Stop(Exception):
            pass

        asked = {}

        def stopping(**named):
            asked.update(named)
            raise Stop

        monkeypatch.setattr(appdir, 'build', stopping)
        with pytest.raises(Stop):
            deb.build(project='.', runtime='runtime', distribution='demo',
                      keep_backends=['tk'],
                      build_directory=str(tmp_path / 'deb'))
        assert asked['keep'] == ['tk']
