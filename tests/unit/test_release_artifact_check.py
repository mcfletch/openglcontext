"""The check that a built wheel or sdist carries nothing the source tree lost.

A stale ``build/lib`` staging directory keeps files that have since been deleted
from the source, and setuptools copies that directory into the wheel without
pruning it -- so a module removed for a reason can be published anyway, and an
import-level regression test cannot see it because the source tree is correct.

:mod:`scripts.check_release_artifact` compares the artifact against the tree it
was built from: every module in the artifact must still exist. That catches the
whole class rather than one named file.
"""
import zipfile

import pytest

from scripts.check_release_artifact import stale_members


def _wheel(tmp_path, names):
    path = tmp_path / "pkg-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, b"")
    return str(path)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "src"
    (root / "OpenGLContext" / "loaders").mkdir(parents=True)
    (root / "OpenGLContext" / "__init__.py").write_text("")
    (root / "OpenGLContext" / "loaders" / "__init__.py").write_text("")
    (root / "OpenGLContext" / "loaders" / "resolver.py").write_text("")
    return root


class TestStaleMembers:
    def test_an_artifact_matching_the_tree_is_clean(self, tmp_path, source):
        w = _wheel(tmp_path, ["OpenGLContext/__init__.py",
                              "OpenGLContext/loaders/resolver.py"])
        assert stale_members(w, str(source)) == []

    def test_a_module_the_tree_no_longer_has_is_reported(self, tmp_path, source):
        w = _wheel(tmp_path, ["OpenGLContext/__init__.py",
                              "OpenGLContext/loaders/gzpickle.py"])
        assert stale_members(w, str(source)) == ["OpenGLContext/loaders/gzpickle.py"]

    def test_a_whole_removed_package_is_reported(self, tmp_path, source):
        w = _wheel(tmp_path, ["OpenGLContext/browser/__init__.py",
                              "OpenGLContext/browser/visual.py"])
        assert stale_members(w, str(source)) == [
            "OpenGLContext/browser/__init__.py",
            "OpenGLContext/browser/visual.py"]

    def test_metadata_is_not_mistaken_for_a_stale_module(self, tmp_path, source):
        w = _wheel(tmp_path, ["OpenGLContext/__init__.py",
                              "pkg-1.0.dist-info/METADATA",
                              "pkg-1.0.dist-info/RECORD"])
        assert stale_members(w, str(source)) == []

    def test_data_files_are_checked_too(self, tmp_path, source):
        # A shader or a cube-map face left behind is the same bug as a module.
        w = _wheel(tmp_path, ["OpenGLContext/shaders/gone.frag"])
        assert stale_members(w, str(source)) == ["OpenGLContext/shaders/gone.frag"]

    def test_an_sdist_is_checked_through_its_top_level_prefix(self, tmp_path, source):
        import tarfile
        path = tmp_path / "openglcontext-3.0.0a1.tar.gz"
        with tarfile.open(path, "w:gz") as t:
            for name in ("openglcontext-3.0.0a1/OpenGLContext/__init__.py",
                         "openglcontext-3.0.0a1/OpenGLContext/loaders/gzpickle.py"):
                info = tarfile.TarInfo(name)
                t.addfile(info, __import__("io").BytesIO(b""))
        assert stale_members(str(path), str(source)) == [
            "OpenGLContext/loaders/gzpickle.py"]

    def test_files_outside_the_package_are_ignored(self, tmp_path, source):
        # readme/licence live at the sdist root, not in the tree's package dir.
        import tarfile
        path = tmp_path / "openglcontext-3.0.0a1.tar.gz"
        with tarfile.open(path, "w:gz") as t:
            for name in ("openglcontext-3.0.0a1/readme.txt",
                         "openglcontext-3.0.0a1/PKG-INFO"):
                t.addfile(tarfile.TarInfo(name), __import__("io").BytesIO(b""))
        assert stale_members(str(path), str(source)) == []
