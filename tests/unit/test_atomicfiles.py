"""A file or directory written through `atomicfiles` is whole or absent.

What each case checks is the state a *later* reader finds after a write that
did not finish, since that is the reader the module is for.
"""

import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from OpenGLContext import atomicfiles


class Interrupted(Exception):
    """Stands for a crash, a full disk or Ctrl-C part way through."""


class TestAFile:
    def test_it_is_replaced_whole(self, tmp_path):
        path = tmp_path / 'record.json'
        path.write_text('old')
        atomicfiles.write_text(str(path), 'new')
        assert path.read_text() == 'new'

    def test_an_interrupted_write_leaves_the_old_content(self, tmp_path):
        path = tmp_path / 'record.json'
        path.write_text('old')
        with pytest.raises(Interrupted):
            with atomicfiles.staged_file(str(path), 'w') as target:
                target.write('half of the n')
                raise Interrupted
        assert path.read_text() == 'old'
        assert os.listdir(tmp_path) == ['record.json'], 'a temporary was left'

    def test_bytes_and_a_copy(self, tmp_path):
        source = tmp_path / 'a.bin'
        atomicfiles.write_bytes(str(source), b'\x00\x01')
        copied = atomicfiles.copy_file(str(source), str(tmp_path / 'b.bin'))
        with open(copied, 'rb') as handle:
            assert handle.read() == b'\x00\x01'

    def test_its_directory_is_made(self, tmp_path):
        path = tmp_path / 'not' / 'yet' / 'there.txt'
        atomicfiles.write_text(str(path), 'x')
        assert path.read_text() == 'x'

    @pytest.mark.skipif(sys.platform == 'win32', reason='POSIX modes')
    def test_an_existing_files_mode_is_kept(self, tmp_path):
        path = tmp_path / 'script.sh'
        path.write_text('old')
        os.chmod(path, 0o750)
        atomicfiles.write_text(str(path), 'new')
        assert os.stat(path).st_mode & 0o777 == 0o750

    @pytest.mark.skipif(sys.platform == 'win32', reason='POSIX modes')
    def test_a_new_file_gets_the_umask_not_the_temporarys(self, tmp_path):
        umask = os.umask(0o022)
        try:
            atomicfiles.write_text(str(tmp_path / 'new.txt'), 'x')
        finally:
            os.umask(umask)
        assert os.stat(tmp_path / 'new.txt').st_mode & 0o777 == 0o644

    def test_a_read_mode_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            with atomicfiles.staged_file(str(tmp_path / 'x'), 'rb'):
                pass


class TestADirectory:
    def old(self, tmp_path):
        where = tmp_path / 'pack'
        (where / 'sub').mkdir(parents=True)
        (where / 'stale.txt').write_text('from the last version')
        (where / 'sub' / 'kept.txt').write_text('old')
        return where

    def test_the_new_one_replaces_the_old_as_a_whole(self, tmp_path):
        where = self.old(tmp_path)
        with atomicfiles.staged_directory(str(where)) as staging:
            os.mkdir(os.path.join(staging, 'sub'))
            with open(os.path.join(staging, 'sub', 'kept.txt'), 'w') as f:
                f.write('new')
        assert (where / 'sub' / 'kept.txt').read_text() == 'new'
        assert not (where / 'stale.txt').exists(), 'an old file survived'
        assert os.listdir(tmp_path) == ['pack']

    def test_an_interrupted_one_leaves_the_old_untouched(self, tmp_path):
        where = self.old(tmp_path)
        with pytest.raises(Interrupted):
            with atomicfiles.staged_directory(str(where)) as staging:
                with open(os.path.join(staging, 'first.txt'), 'w') as f:
                    f.write('written before the failure')
                raise Interrupted
        assert sorted(os.listdir(where)) == ['stale.txt', 'sub']
        assert os.listdir(tmp_path) == ['pack'], 'the staging was left'

    def test_an_interrupted_first_one_leaves_nothing(self, tmp_path):
        where = tmp_path / 'pack'
        with pytest.raises(Interrupted):
            with atomicfiles.staged_directory(str(where)) as staging:
                open(os.path.join(staging, 'first.txt'), 'w').close()
                raise Interrupted
        assert os.listdir(tmp_path) == []

    def test_what_a_killed_process_left_is_cleared(self, tmp_path):
        where = tmp_path / 'pack'
        leftover = tmp_path / ('.pack' + atomicfiles.PARTIAL + 'dead')
        leftover.mkdir()
        (leftover / 'half.bin').write_bytes(b'x')
        retired = tmp_path / ('.pack' + atomicfiles.RETIRED + 'dead')
        retired.mkdir()
        with atomicfiles.staged_directory(str(where)):
            pass
        assert os.listdir(tmp_path) == ['pack']

    def test_another_targets_staging_is_left_alone(self, tmp_path):
        other = tmp_path / ('.pack2' + atomicfiles.PARTIAL + 'busy')
        other.mkdir()
        with atomicfiles.staged_directory(str(tmp_path / 'pack')):
            pass
        assert other.is_dir()

    def test_a_failed_move_puts_the_old_one_back(self, tmp_path, monkeypatch):
        where = self.old(tmp_path)
        staging = tmp_path / 'staging'
        staging.mkdir()
        real = os.replace

        def refuse_the_new_one(source, target):
            if str(source) == str(staging):
                raise OSError('no')
            return real(source, target)

        monkeypatch.setattr(atomicfiles.os, 'replace', refuse_the_new_one)
        with pytest.raises(OSError):
            atomicfiles.replace_directory(str(staging), str(where))
        assert (where / 'stale.txt').exists()


class TestALock:
    def test_a_second_thread_waits_for_the_first(self, tmp_path):
        lock = str(tmp_path / 'x.lock')
        order = []
        holding = threading.Event()

        def first():
            with atomicfiles.file_lock(lock):
                holding.set()
                time.sleep(0.2)
                order.append('first out')

        thread = threading.Thread(target=first)
        thread.start()
        holding.wait(5)
        with atomicfiles.file_lock(lock):
            order.append('second in')
        thread.join(5)
        assert order == ['first out', 'second in']

    def test_a_second_process_waits_for_the_first(self, tmp_path):
        lock = str(tmp_path / 'x.lock')
        ready = tmp_path / 'holding'
        script = textwrap.dedent('''
            import sys, time
            from OpenGLContext import atomicfiles
            with atomicfiles.file_lock(sys.argv[1]):
                open(sys.argv[2], 'w').close()
                time.sleep(1.0)
        ''')
        child = subprocess.Popen([sys.executable, '-c', script, lock,
                                  str(ready)])
        try:
            deadline = time.monotonic() + 30
            while not ready.exists():
                assert time.monotonic() < deadline, 'the child never locked'
                time.sleep(0.01)
            started = time.monotonic()
            with atomicfiles.file_lock(lock):
                waited = time.monotonic() - started
        finally:
            child.wait(30)
        assert waited > 0.3, 'the lock did not hold off a second process'

    def test_the_lock_is_released_by_an_exception(self, tmp_path):
        lock = str(tmp_path / 'x.lock')
        with pytest.raises(Interrupted):
            with atomicfiles.file_lock(lock):
                raise Interrupted
        with atomicfiles.file_lock(lock):
            pass


class TestRemovingADirectory:
    def test_it_is_gone_whole(self, tmp_path):
        where = tmp_path / 'pack'
        (where / 'sub').mkdir(parents=True)
        (where / 'sub' / 'a.txt').write_text('x')
        atomicfiles.remove_directory(str(where))
        assert os.listdir(tmp_path) == []

    def test_one_that_is_not_there_is_nothing_to_do(self, tmp_path):
        atomicfiles.remove_directory(str(tmp_path / 'absent'))
