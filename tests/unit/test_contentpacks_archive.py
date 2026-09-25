"""Unpacking an archive nobody here wrote.

A content pack arrives from a URL a registry named, and an archive decides its
own member names. So every name is checked against the destination before
anything is written: an entry that would land outside it stops the extraction
rather than overwriting whatever it pointed at.
"""

import io
import os
import tarfile
import zipfile

import pytest

from OpenGLContext.contentpacks import archive


def zip_of(path, names, data=b'x'):
    with zipfile.ZipFile(path, 'w') as handle:
        for name in names:
            handle.writestr(name, data)
    return str(path)


def tar_of(path, names, mode='w:gz', size=1):
    with tarfile.open(path, mode) as handle:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = size
            handle.addfile(info, io.BytesIO(b'x' * size))
    return str(path)


class TestAnArchiveThatIsWhatItSays:
    def test_a_zip_lands_where_it_was_told(self, tmp_path) -> None:
        source = zip_of(tmp_path / 'a.zip', ['tileset.json', 'tiles/t_0.glb'])
        where = str(tmp_path / 'out')
        assert archive.extract(source, where, 'zip') == where
        assert os.path.isfile(os.path.join(where, 'tileset.json'))
        assert os.path.isfile(os.path.join(where, 'tiles', 't_0.glb'))

    def test_a_tarball_lands_where_it_was_told(self, tmp_path) -> None:
        source = tar_of(tmp_path / 'a.tar.gz', ['world.json', 'tiles/t_0.glb'])
        where = str(tmp_path / 'out')
        archive.extract(source, where, 'tar')
        assert os.path.isfile(os.path.join(where, 'world.json'))
        assert os.path.isfile(os.path.join(where, 'tiles', 't_0.glb'))

    @pytest.mark.parametrize('mode,suffix', [('w', '.tar'), ('w:gz', '.tar.gz'),
                                             ('w:bz2', '.tar.bz2'),
                                             ('w:xz', '.tar.xz')])
    def test_every_compression_a_tarball_arrives_under(self, tmp_path, mode,
                                                       suffix) -> None:
        """`tar` names the container; the reader detects the compression."""
        source = tar_of(tmp_path / ('a' + suffix), ['world.json'], mode=mode)
        where = str(tmp_path / ('out' + suffix))
        archive.extract(source, where, 'tar')
        assert os.path.isfile(os.path.join(where, 'world.json'))

    def test_the_destination_is_made_if_it_is_not_there(self, tmp_path) -> None:
        source = zip_of(tmp_path / 'a.zip', ['x'])
        where = str(tmp_path / 'deep' / 'nested' / 'out')
        archive.extract(source, where, 'zip')
        assert os.path.isfile(os.path.join(where, 'x'))


class TestAnEntryThatWouldEscape:
    """Nothing is written when any member would land outside the destination.

    Refused wholesale rather than per entry: an archive carrying one such name
    is not an archive to take the rest of on trust.
    """

    @pytest.mark.parametrize('name', [
        '../outside',
        'tiles/../../outside',
        'a/b/../../../outside',
    ])
    def test_a_zip_climbing_out_is_refused(self, tmp_path, name) -> None:
        source = zip_of(tmp_path / 'a.zip', ['fine.json', name])
        where = str(tmp_path / 'out')
        with pytest.raises(archive.UnsafeArchive) as raised:
            archive.extract(source, where, 'zip')
        assert 'outside' in str(raised.value)

    def test_an_absolute_name_in_a_zip_is_refused(self, tmp_path) -> None:
        source = zip_of(tmp_path / 'a.zip', ['/etc/passwd'])
        with pytest.raises(archive.UnsafeArchive):
            archive.extract(source, str(tmp_path / 'out'), 'zip')

    @pytest.mark.parametrize('name', ['../outside', '/etc/passwd'])
    def test_a_tarball_climbing_out_is_refused(self, tmp_path, name) -> None:
        source = tar_of(tmp_path / 'a.tar.gz', [name])
        with pytest.raises(archive.UnsafeArchive):
            archive.extract(source, str(tmp_path / 'out'), 'tar')

    def test_nothing_is_written_when_one_entry_is_refused(self, tmp_path) -> None:
        source = zip_of(tmp_path / 'a.zip', ['fine.json', '../outside'])
        where = str(tmp_path / 'out')
        with pytest.raises(archive.UnsafeArchive):
            archive.extract(source, where, 'zip')
        assert not os.path.exists(os.path.join(where, 'fine.json'))

    def test_a_symlink_out_of_the_tree_is_refused(self, tmp_path) -> None:
        """A link is a write to wherever it points, the next time anything
        follows it."""
        path = tmp_path / 'a.tar.gz'
        with tarfile.open(path, 'w:gz') as handle:
            info = tarfile.TarInfo('escape')
            info.type = tarfile.SYMTYPE
            info.linkname = '/etc/passwd'
            handle.addfile(info)
        with pytest.raises(archive.UnsafeArchive):
            archive.extract(str(path), str(tmp_path / 'out'), 'tar')

    def test_a_device_node_is_refused(self, tmp_path) -> None:
        path = tmp_path / 'a.tar.gz'
        with tarfile.open(path, 'w:gz') as handle:
            info = tarfile.TarInfo('dev/null')
            info.type = tarfile.CHRTYPE
            info.devmajor, info.devminor = 1, 3
            handle.addfile(info)
        with pytest.raises(archive.UnsafeArchive):
            archive.extract(str(path), str(tmp_path / 'out'), 'tar')


class TestAnArchiveThatCannotBeRead:
    def test_a_kind_nothing_reads(self, tmp_path) -> None:
        source = zip_of(tmp_path / 'a.zip', ['x'])
        with pytest.raises(ValueError):
            archive.extract(source, str(tmp_path / 'out'), 'rar')

    def test_a_file_that_is_not_the_archive_it_claims(self, tmp_path) -> None:
        path = tmp_path / 'a.zip'
        path.write_bytes(b'not a zip at all')
        with pytest.raises(archive.UnreadableArchive):
            archive.extract(str(path), str(tmp_path / 'out'), 'zip')

    @pytest.mark.parametrize('mode,suffix', [('w:gz', '.tar.gz'),
                                             ('w:bz2', '.tar.bz2'),
                                             ('w:xz', '.tar.xz')])
    def test_a_download_that_stopped_early(self, tmp_path, mode, suffix) -> None:
        """Every compression, because they do not fail the same way.

        A truncated gzip or xz reaches the decompressor and raises EOFError,
        while a bzip2 tarball raises a tarfile error; a caller has one exception
        to catch either way.
        """
        source = tar_of(tmp_path / ('a' + suffix),
                        ['a/%d.bin' % n for n in range(40)], mode=mode,
                        size=5000)
        whole = os.path.getsize(source)
        with open(source, 'r+b') as handle:
            handle.truncate(whole // 2)
        with pytest.raises(archive.UnreadableArchive):
            archive.extract(source, str(tmp_path / ('out' + suffix)), 'tar')

    def test_an_uncompressed_tarball_has_no_integrity_of_its_own(
            self, tmp_path) -> None:
        """Truncated at a member boundary it reads as a shorter archive.

        Nothing in the container says how long it was meant to be, so a short
        download arrives as content with files missing rather than as an error.
        The digest is what catches this, which is why a pack we publish carries
        one -- and why one that arrives without a digest is only as trustworthy
        as the host that served it.
        """
        source = tar_of(tmp_path / 'a.tar',
                        ['a/%d.bin' % n for n in range(40)], mode='w',
                        size=5000)
        # At a member boundary -- 512 bytes of header plus the content rounded
        # up to a block -- so what is left is a whole number of entries and the
        # reader has nothing to object to.
        per_member = 512 + ((5000 + 511) // 512) * 512
        with open(source, 'r+b') as handle:
            handle.truncate(10 * per_member)
        where = str(tmp_path / 'out')
        archive.extract(source, where, 'tar')
        arrived = os.listdir(os.path.join(where, 'a'))
        assert 0 < len(arrived) < 40, 'a short archive, read as one'
        with pytest.raises(archive.DigestMismatch):
            archive.check_digest(source, 'ab' * 32)


class TestWhatItSaysAboutADigest:
    def test_a_file_that_matches_passes(self, tmp_path) -> None:
        path = tmp_path / 'a.bin'
        path.write_bytes(b'hello')
        import hashlib
        archive.check_digest(str(path), hashlib.sha256(b'hello').hexdigest())

    def test_one_that_does_not_is_refused_naming_both(self, tmp_path) -> None:
        path = tmp_path / 'a.bin'
        path.write_bytes(b'hello')
        with pytest.raises(archive.DigestMismatch) as raised:
            archive.check_digest(str(path), '00' * 32)
        assert '00' * 32 in str(raised.value)

    def test_no_digest_asked_for_is_no_check(self, tmp_path) -> None:
        path = tmp_path / 'a.bin'
        path.write_bytes(b'hello')
        archive.check_digest(str(path), '')

    def test_it_reads_in_blocks_rather_than_whole(self, tmp_path) -> None:
        """A base pack is tens of megabytes; it is not held in memory to hash."""
        path = tmp_path / 'big.bin'
        path.write_bytes(b'ab' * 200_000)
        import hashlib
        archive.check_digest(str(path),
                             hashlib.sha256(b'ab' * 200_000).hexdigest())


class TestAnArchiveThatWouldFillTheDisk:
    """The download is capped; what it expands to is a separate question.

    A megabyte of zeroes deflates to almost nothing, so an archive well inside
    any download cap can write hundreds of gigabytes. Nothing about the transfer
    says so -- the size has to be read out of the archive and judged before a
    byte is written.
    """

    def bomb(self, path, members=4, each=8 * 1024 * 1024, kind='zip'):
        if kind == 'zip':
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as handle:
                for n in range(members):
                    handle.writestr('f%d.bin' % n, b'\0' * each)
        else:
            with tarfile.open(path, 'w:gz') as handle:
                for n in range(members):
                    info = tarfile.TarInfo('f%d.bin' % n)
                    info.size = each
                    handle.addfile(info, io.BytesIO(b'\0' * each))
        return str(path)

    @pytest.mark.parametrize('kind,name', [('zip', 'b.zip'), ('tar', 'b.tar.gz')])
    def test_it_is_refused_by_what_it_would_write(self, tmp_path, kind,
                                                  name) -> None:
        source = self.bomb(tmp_path / name, kind=kind)
        where = str(tmp_path / 'out')
        with pytest.raises(archive.TooLarge) as raised:
            archive.extract(source, where, kind, max_bytes=1024 * 1024)
        assert 'unpack' in str(raised.value).lower()

    @pytest.mark.parametrize('kind,name', [('zip', 'b.zip'), ('tar', 'b.tar.gz')])
    def test_nothing_is_written_before_it_is_refused(self, tmp_path, kind,
                                                     name) -> None:
        """Judged from the archive's own sizes, so the refusal costs no disk."""
        source = self.bomb(tmp_path / name, kind=kind)
        where = str(tmp_path / 'out')
        with pytest.raises(archive.TooLarge):
            archive.extract(source, where, kind, max_bytes=1024 * 1024)
        assert not os.path.exists(where) or not os.listdir(where)

    def test_an_archive_inside_its_budget_is_extracted(self, tmp_path) -> None:
        source = self.bomb(tmp_path / 'small.zip', members=2, each=1024)
        where = str(tmp_path / 'out')
        archive.extract(source, where, 'zip', max_bytes=1024 * 1024)
        assert len(os.listdir(where)) == 2

    def test_an_archive_of_countless_entries_is_refused(self, tmp_path) -> None:
        """Millions of empty files is its own denial of service."""
        source = zip_of(tmp_path / 'many.zip',
                        ['f%d' % n for n in range(200)], data=b'')
        with pytest.raises(archive.TooLarge) as raised:
            archive.extract(source, str(tmp_path / 'out'), 'zip',
                            max_entries=50)
        assert 'entries' in str(raised.value)

    def test_the_budget_follows_what_the_pack_said_it_was(self) -> None:
        """Content is mostly already compressed, so the headroom is generous
        and still nowhere near what a bomb needs."""
        assert archive.unpacked_limit(100 * 1024 * 1024) == \
            100 * 1024 * 1024 * archive.MAX_EXPANSION
        assert archive.unpacked_limit(1) == archive.MINIMUM_UNPACKED

    def test_a_real_pack_is_comfortably_inside_it(self, tmp_path) -> None:
        """A glisteel track measures 57 MB unpacked against 48 MB compressed."""
        assert archive.unpacked_limit(48 * 1024 * 1024) > 57 * 1024 * 1024


class TestWritingAPack:
    """The other half: making the archive a registry then names.

    A registry records a digest, so what is published has to be a function of
    the content and of nothing else. Two builds of the same files, minutes
    apart and from different checkouts, are the same bytes.
    """

    def content(self, root):
        (root / 'trees').mkdir(parents=True)
        (root / 'trees' / 'fir.glb').write_bytes(b'glb' * 100)
        (root / 'tileset.json').write_text('{"asset": {}}')
        return str(root)

    def test_it_writes_what_was_there(self, tmp_path) -> None:
        where = self.content(tmp_path / 'track')
        path = archive.write(where, str(tmp_path / 'track.tar.gz'))
        out = str(tmp_path / 'out')
        archive.extract(path, out, 'tar')
        assert os.path.isfile(os.path.join(out, 'tileset.json'))
        assert os.path.isfile(os.path.join(out, 'trees', 'fir.glb'))

    def test_the_same_content_twice_is_the_same_bytes(self, tmp_path) -> None:
        """Nothing about *when* it was built may reach the file.

        The gzip container carries a timestamp of its own, above the tar
        entries, so fixing the entries' own times is not enough on its own.
        """
        where = self.content(tmp_path / 'track')
        one = archive.write(where, str(tmp_path / 'one.tar.gz'))
        os.utime(os.path.join(where, 'tileset.json'), (0, 0))
        two = archive.write(where, str(tmp_path / 'two.tar.gz'))
        assert archive.digest(one) == archive.digest(two)

    def test_the_name_it_was_given_is_not_in_the_bytes(self, tmp_path) -> None:
        """Two names for one pack are one digest: gzip stores a filename."""
        where = self.content(tmp_path / 'track')
        one = archive.write(where, str(tmp_path / 'ashdown.tar.gz'))
        two = archive.write(where, str(tmp_path / 'glisteel-ashdown.tar.gz'))
        assert archive.digest(one) == archive.digest(two)

    def test_who_built_it_is_not_in_the_bytes(self, tmp_path) -> None:
        """Owner, group and mode are facts about a build machine."""
        where = self.content(tmp_path / 'track')
        os.chmod(os.path.join(where, 'tileset.json'), 0o600)
        one = archive.digest(archive.write(where, str(tmp_path / 'one.tar.gz')))
        os.chmod(os.path.join(where, 'tileset.json'), 0o755)
        two = archive.digest(archive.write(where, str(tmp_path / 'two.tar.gz')))
        assert one == two
        with tarfile.open(str(tmp_path / 'one.tar.gz')) as handle:
            for member in handle:
                assert member.uname == member.gname == ''
                assert member.uid == member.gid == 0
                assert member.mtime == archive.EPOCH

    def test_the_order_is_settled_rather_than_the_disk_s(self, tmp_path) -> None:
        """Two checkouts hand os.walk their entries in different orders."""
        where = self.content(tmp_path / 'track')
        (tmp_path / 'track' / 'a.txt').write_text('a')
        (tmp_path / 'track' / 'z.txt').write_text('z')
        path = archive.write(where, str(tmp_path / 'track.tar.gz'))
        with tarfile.open(path) as handle:
            assert handle.getnames() == sorted(handle.getnames())

    def test_the_digest_is_of_the_file(self, tmp_path) -> None:
        import hashlib
        path = tmp_path / 'a.bin'
        path.write_bytes(b'hello')
        assert archive.digest(str(path)) == hashlib.sha256(b'hello').hexdigest()

    def test_the_names_are_spelled_as_a_tar_spells_them(self, tmp_path) -> None:
        """A path, not the platform's idea of one.

        Windows' separator sorts on the other side of the digits and capitals
        from `/`, so ordering the local spelling would give two machines two
        archives of one tree.
        """
        where = self.content(tmp_path / 'track')
        (tmp_path / 'track' / 'trees0.txt').write_text('0')
        assert archive._entries(where) == [
            'tileset.json', 'trees/fir.glb', 'trees0.txt']
        path = archive.write(where, str(tmp_path / 'track.tar.gz'))
        with tarfile.open(path) as handle:
            assert 'trees/fir.glb' in handle.getnames()


class TestReadingNoMoreThanItMust:
    def test_a_tarball_of_countless_entries_is_refused_early(self, tmp_path,
                                                              monkeypatch):
        """The count is kept while the headers are read, and the reading stops
        at the first entry over it rather than after all of them."""
        source = tar_of(tmp_path / 'many.tar.gz',
                        ['f%d' % n for n in range(2000)], size=0)
        read = []
        real = tarfile.TarFile.next

        def counting(self):
            read.append(1)
            return real(self)

        monkeypatch.setattr(tarfile.TarFile, 'next', counting)
        with pytest.raises(archive.TooLarge) as raised:
            archive.extract(source, str(tmp_path / 'out'), 'tar',
                            max_entries=50)
        assert 'entries' in str(raised.value)
        assert len(read) < 100, 'every header was read before the refusal'

    def test_a_tarball_over_its_size_stops_at_the_first_overrun(
            self, tmp_path, monkeypatch):
        source = tar_of(tmp_path / 'big.tar.gz',
                        ['f%d' % n for n in range(500)], size=1024)
        read = []
        real = tarfile.TarFile.next

        def counting(self):
            read.append(1)
            return real(self)

        monkeypatch.setattr(tarfile.TarFile, 'next', counting)
        with pytest.raises(archive.TooLarge):
            archive.extract(source, str(tmp_path / 'out'), 'tar',
                            max_bytes=10 * 1024)
        assert len(read) < 20

    def test_the_unpacking_cap_applies_unless_it_is_lifted(self, tmp_path):
        """Safe by default: ``None`` is how a caller asks for no cap."""
        bomb = TestAnArchiveThatWouldFillTheDisk().bomb(
            tmp_path / 'b.zip', members=9, each=8 * 1024 * 1024)
        with pytest.raises(archive.TooLarge):
            archive.extract(bomb, str(tmp_path / 'out'), 'zip')

    def test_an_interpreter_without_extraction_filters_says_so(
            self, tmp_path, monkeypatch):
        source = tar_of(tmp_path / 'a.tar.gz', ['a'])
        monkeypatch.delattr(tarfile, 'data_filter')
        with pytest.raises(archive.UnreadableArchive) as raised:
            archive.extract(source, str(tmp_path / 'out'), 'tar')
        assert 'Python' in str(raised.value)

    def test_a_cancel_stops_the_unpacking(self, tmp_path):
        from OpenGLContext.loaders import resolver
        source = tar_of(tmp_path / 'a.tar.gz', ['f%d' % n for n in range(20)])
        with pytest.raises(resolver.FetchCancelled):
            archive.extract(source, str(tmp_path / 'out'), 'tar',
                            cancel=lambda: True)
        source = zip_of(tmp_path / 'a.zip', ['f%d' % n for n in range(20)])
        with pytest.raises(resolver.FetchCancelled):
            archive.extract(source, str(tmp_path / 'out2'), 'zip',
                            cancel=lambda: True)


class TestWritingAPackFromATreeWithLinks:
    @pytest.mark.skipif(not hasattr(os, 'symlink'), reason='no symlinks')
    def test_a_linked_file_is_refused_by_name(self, tmp_path):
        tree = tmp_path / 'tree'
        tree.mkdir()
        (tree / 'real.txt').write_text('x')
        os.symlink(str(tree / 'real.txt'), str(tree / 'link.txt'))
        with pytest.raises(IOError) as raised:
            archive.write(str(tree), str(tmp_path / 'a.tar.gz'))
        assert 'link.txt' in str(raised.value)

    @pytest.mark.skipif(not hasattr(os, 'symlink'), reason='no symlinks')
    def test_a_linked_directory_is_refused_rather_than_left_out(self,
                                                                tmp_path):
        tree = tmp_path / 'tree'
        (tree / 'real').mkdir(parents=True)
        (tree / 'real' / 'a.txt').write_text('x')
        os.symlink(str(tree / 'real'), str(tree / 'dirlink'))
        with pytest.raises(IOError) as raised:
            archive.write(str(tree), str(tmp_path / 'a.tar.gz'))
        assert 'dirlink' in str(raised.value)

    @pytest.mark.skipif(not hasattr(os, 'symlink'), reason='no symlinks')
    def test_a_refused_write_leaves_no_archive(self, tmp_path):
        tree = tmp_path / 'tree'
        tree.mkdir()
        (tree / 'real.txt').write_text('x')
        os.symlink(str(tree / 'real.txt'), str(tree / 'zlink.txt'))
        out = tmp_path / 'dist'
        out.mkdir()
        (out / 'a.tar.gz').write_bytes(b'the last good build')
        with pytest.raises(IOError):
            archive.write(str(tree), str(out / 'a.tar.gz'))
        assert (out / 'a.tar.gz').read_bytes() == b'the last good build'
        assert os.listdir(out) == ['a.tar.gz']


class TestWritingAPackFromACheckoutWithoutItsLargeFiles:
    """A checkout made without ``git lfs pull`` holds a small text pointer in
    place of each large file, under the file's own name."""

    POINTER = (b'version https://git-lfs.github.com/spec/v1\n'
               b'oid sha256:' + b'0' * 64 + b'\nsize 12345\n')

    def test_a_pointer_is_refused_by_name(self, tmp_path):
        tree = tmp_path / 'tree'
        (tree / 'trees').mkdir(parents=True)
        (tree / 'heightmap.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        (tree / 'trees' / 'fir.npz').write_bytes(self.POINTER)
        with pytest.raises(IOError) as raised:
            archive.write(str(tree), str(tmp_path / 'a.tar.gz'))
        assert 'trees/fir.npz' in str(raised.value)
        assert 'git lfs pull' in str(raised.value)
        assert not (tmp_path / 'a.tar.gz').exists()

    def test_a_file_that_only_mentions_one_is_packed(self, tmp_path):
        tree = tmp_path / 'tree'
        tree.mkdir()
        (tree / 'README.txt').write_bytes(b'see ' + self.POINTER)
        archive.write(str(tree), str(tmp_path / 'a.tar.gz'))
        assert (tmp_path / 'a.tar.gz').exists()
