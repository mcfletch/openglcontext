"""Where a per-user file goes on each platform.

The rules are the platforms' own, and the point of testing them here is that
they are pure string work: what a Windows or a macOS install answers is decided
by the same function this container runs, so all three are checkable from one.
"""
import os
import sys

import pytest

from OpenGLContext import userpaths


@pytest.fixture
def clean(monkeypatch):
    """An environment with none of the variables the rules consult."""
    for name in ('HOME', 'XDG_PICTURES_DIR', 'XDG_CONFIG_HOME', 'APPDATA',
                 'USERPROFILE'):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestTheApplicationDataDirectory:
    def test_windows_uses_the_roaming_directory(self, clean, tmp_path):
        clean.setattr(sys, 'platform', 'win32')
        clean.setenv('APPDATA', str(tmp_path))
        assert userpaths.appdatadirectory() == str(tmp_path)

    def test_elsewhere_the_xdg_variable_wins(self, clean, tmp_path):
        clean.setattr(sys, 'platform', 'linux')
        clean.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
        clean.setenv('HOME', str(tmp_path))
        assert userpaths.appdatadirectory() == str(tmp_path / 'config')

    def test_without_it_the_xdg_default_is_used(self, clean, tmp_path):
        """Beside every other application's files, not one more dotfile."""
        clean.setattr(sys, 'platform', 'linux')
        clean.setenv('HOME', str(tmp_path))
        assert userpaths.appdatadirectory() == str(tmp_path / '.config')

    def test_with_no_environment_the_expansion_answers(self, clean, monkeypatch,
                                                       tmp_path):
        clean.setattr(sys, 'platform', 'linux')
        monkeypatch.setattr(os.path, 'expanduser', lambda path: str(tmp_path))
        assert userpaths.appdatadirectory() == str(tmp_path / '.config')

    def test_windows_with_no_environment_takes_the_profile_itself(
            self, clean, monkeypatch, tmp_path):
        """Windows puts application data in a directory of its own, not under one."""
        clean.setattr(sys, 'platform', 'win32')
        monkeypatch.setattr(os.path, 'expanduser', lambda path: str(tmp_path))
        assert userpaths.appdatadirectory() == str(tmp_path)

    def test_nothing_to_go_on_is_an_error_the_caller_can_catch(self, clean,
                                                               monkeypatch):
        """The asset cache catches this and drops to the system temp directory."""
        clean.setattr(sys, 'platform', 'linux')
        monkeypatch.setattr(os.path, 'expanduser', lambda path: path)
        with pytest.raises(OSError):
            userpaths.appdatadirectory()


class TestThePicturesDirectory:
    def test_linux_uses_the_xdg_variable_when_it_is_set(self, clean, tmp_path):
        clean.setattr(sys, 'platform', 'linux')
        clean.setenv('HOME', str(tmp_path))
        clean.setenv('XDG_PICTURES_DIR', str(tmp_path / 'Images'))
        assert userpaths.picturesdirectory() == str(tmp_path / 'Images')

    def test_linux_reads_the_user_dirs_configuration(self, clean, tmp_path):
        """The file a desktop writes when the folder has been renamed."""
        config = tmp_path / '.config'
        config.mkdir()
        (config / 'user-dirs.dirs').write_text(
            '# generated\nXDG_DESKTOP_DIR="$HOME/Bureau"\n'
            'XDG_PICTURES_DIR="$HOME/Images"\n')
        clean.setattr(sys, 'platform', 'linux')
        clean.setenv('HOME', str(tmp_path))
        assert userpaths.picturesdirectory() == str(tmp_path / 'Images')

    def test_linux_falls_back_to_the_default_name(self, clean, tmp_path):
        clean.setattr(sys, 'platform', 'linux')
        clean.setenv('HOME', str(tmp_path))
        assert userpaths.picturesdirectory() == str(tmp_path / 'Pictures')

    def test_a_malformed_user_dirs_line_is_skipped(self, clean, tmp_path):
        config = tmp_path / '.config'
        config.mkdir()
        (config / 'user-dirs.dirs').write_text('nonsense\nXDG_PICTURES_DIR\n')
        clean.setattr(sys, 'platform', 'linux')
        clean.setenv('HOME', str(tmp_path))
        assert userpaths.picturesdirectory() == str(tmp_path / 'Pictures')

    def test_macos_uses_the_home_folder(self, clean, tmp_path):
        """macOS has no XDG configuration; ~/Pictures is the Finder's own."""
        clean.setattr(sys, 'platform', 'darwin')
        clean.setenv('HOME', str(tmp_path))
        clean.setenv('XDG_PICTURES_DIR', str(tmp_path / 'ignored'))
        assert userpaths.picturesdirectory() == str(tmp_path / 'Pictures')

    def test_windows_asks_the_shell_where_it_is(self, clean, tmp_path):
        """A moved or cloud-redirected Pictures folder is only knowable there."""
        clean.setattr(sys, 'platform', 'win32')
        clean.setattr(userpaths, '_knownpicturesfolder',
                      lambda: str(tmp_path / 'OneDrive' / 'Pictures'))
        assert userpaths.picturesdirectory() == str(
            tmp_path / 'OneDrive' / 'Pictures')

    def test_windows_falls_back_to_the_profile(self, clean, tmp_path):
        clean.setattr(sys, 'platform', 'win32')
        clean.setattr(userpaths, '_knownpicturesfolder', lambda: None)
        clean.setenv('USERPROFILE', str(tmp_path))
        assert userpaths.picturesdirectory() == os.path.join(
            str(tmp_path), 'Pictures')

    def test_a_home_only_the_expansion_knows_is_used(self, clean, monkeypatch,
                                                     tmp_path):
        """A service account may have a home directory but no HOME variable."""
        clean.setattr(sys, 'platform', 'linux')
        monkeypatch.setattr(os.path, 'expanduser', lambda path: str(tmp_path))
        assert userpaths.picturesdirectory() == str(tmp_path / 'Pictures')

    def test_no_home_at_all_is_an_error_the_caller_can_catch(self, clean,
                                                             monkeypatch):
        """The caller has somewhere else to go; it needs to be told to go there."""
        clean.setattr(sys, 'platform', 'linux')
        monkeypatch.setattr(os.path, 'expanduser', lambda path: path)
        with pytest.raises(OSError):
            userpaths.picturesdirectory()
