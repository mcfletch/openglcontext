"""Regression: the OBJ loader parses and resolves textures on Python 3 (no GL).

Two Python-2 remnants broke ``loaders/obj.py``:
  * ``md5(baseURL)`` -- hashing a str raises ``TypeError`` in Py3, so parse()
    crashed on its very first line for every OBJ.
  * ``urllib.basejoin`` -- does not exist in Py3 (``AttributeError``), and the
    failure was swallowed by a bare ``except:``, so textured OBJ models silently
    loaded *without* their textures instead of failing loudly.
"""
import os

import pytest

from OpenGLContext.loaders.obj import OBJHandler
from OpenGLContext.scenegraph import basenodes

MINIMAL_OBJ = """\
v 0 0 0
v 1 0 0
v 0 1 0
vn 0 0 1
f 1//1 2//1 3//1
"""


class TestParse:
    def test_minimal_obj_parses(self, tmp_path):
        base = str(tmp_path / 'model.obj')
        ok, sg = OBJHandler().parse(MINIMAL_OBJ, base)
        assert ok is True
        shapes = [c for t in sg.children for c in getattr(t, 'children', [])
                  if isinstance(c, basenodes.Shape)]
        assert shapes, "expected at least one Shape from the OBJ faces"


class TestMaterialTexture:
    def test_map_kd_resolves_to_joined_url(self, tmp_path):
        obj = tmp_path / 'model.obj'
        obj.write_text(MINIMAL_OBJ)
        mtl = tmp_path / 'model.mtl'
        mtl.write_text('newmtl mat\nKd 1 0 0\nmap_Kd brick.png\n')
        # a genuine 1x1 PNG so the ImageTexture's async load doesn't log noise
        from PIL import Image
        Image.new('RGB', (1, 1), (255, 0, 0)).save(str(tmp_path / 'brick.png'))

        handler = OBJHandler()
        materials = {}
        handler.load_material_library('model.mtl', materials, baseURL=str(obj))

        assert 'mat' in materials
        appearance = materials['mat']
        assert appearance.texture is not None, "map_Kd should attach an ImageTexture"
        assert isinstance(appearance.texture, basenodes.ImageTexture)
        joined = appearance.texture.url
        assert any(u.endswith('brick.png') for u in joined), joined
        # the joined URL must be an absolute resolution of the sibling texture
        assert any(os.path.basename(u) == 'brick.png' and ('/' in u) for u in joined), joined
