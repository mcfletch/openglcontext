"""physics-cook CLI: bake OMI colliders into a glTF document (no GL)."""
import copy
import json

import pytest

from OpenGLContext.bin.physics_cook import DYNAMIC, STATIC, cook_document, main
from OpenGLContext.physics import omigltf


def base_gltf():
    return {
        'asset': {'version': '2.0'},
        'meshes': [{'primitives': []}, {'primitives': []}],
        'nodes': [
            {'name': 'terrain', 'mesh': 0},
            {'name': 'prop', 'mesh': 1},
            {'name': 'empty'},                      # no mesh: skipped
        ],
    }


def test_static_cook_adds_trimesh_colliders():
    gltf, count = cook_document(base_gltf(), motion_type=STATIC)
    assert count == 2
    doc = omigltf.load_document(gltf)
    assert all(s.kind == 'trimesh' for s in doc.shapes)
    assert doc.node_bodies[0].collider.shape == doc.shapes.index(doc.shapes[0])
    assert doc.node_bodies[0].motion.type == STATIC


def test_dynamic_cook_adds_convex_with_mass():
    gltf, count = cook_document(base_gltf(), motion_type=DYNAMIC, mass=3.0)
    doc = omigltf.load_document(gltf)
    assert all(s.kind == 'convex' for s in doc.shapes)
    assert doc.node_bodies[1].motion.type == DYNAMIC
    assert doc.node_bodies[1].motion.mass == 3.0


def test_extensions_registered_and_shape_shared():
    gltf, _ = cook_document(base_gltf(), motion_type=STATIC)
    assert 'OMI_physics_shape' in gltf['extensionsUsed']
    assert 'OMI_physics_body' in gltf['extensionsUsed']
    assert len(gltf['extensions']['OMI_physics_shape']['shapes']) == 2


def test_idempotent_on_already_cooked_nodes():
    gltf = base_gltf()
    cook_document(gltf, motion_type=STATIC)
    before = copy.deepcopy(gltf)
    cook_document(gltf, motion_type=STATIC)   # second pass
    assert gltf == before                            # no duplicate bodies/shapes


class TestMainCli:
    def test_overwrites_input_in_place_and_reports_count(self, tmp_path, capsys):
        doc = tmp_path / 'scene.gltf'
        doc.write_text(json.dumps(base_gltf()))
        rc = main([str(doc)])
        assert rc == 0
        cooked = json.loads(doc.read_text())
        # both mesh nodes got a static (trimesh) collider baked in place
        bodies = [n['extensions']['OMI_physics_body']
                  for n in cooked['nodes'] if 'extensions' in n]
        assert len(bodies) == 2
        assert all(b['motion']['type'] == STATIC for b in bodies)
        out = capsys.readouterr().out
        assert 'added 2 collider(s)' in out
        assert str(doc) in out

    def test_writes_to_separate_output_leaving_input_untouched(self, tmp_path):
        src = tmp_path / 'in.gltf'
        src.write_text(json.dumps(base_gltf()))
        dst = tmp_path / 'out.gltf'
        rc = main(['-o', str(dst), str(src)])
        assert rc == 0
        assert 'OMI_physics_shape' not in src.read_text()       # input left alone
        assert 'OMI_physics_body' in dst.read_text()            # colliders in the copy

    def test_dynamic_motion_bakes_convex_bodies_with_mass(self, tmp_path):
        src = tmp_path / 'in.gltf'
        src.write_text(json.dumps(base_gltf()))
        main([str(src), '--motion', DYNAMIC, '--mass', '2.5'])
        doc = omigltf.load_document(json.loads(src.read_text()))
        assert all(s.kind == 'convex' for s in doc.shapes)
        assert doc.node_bodies[0].motion.mass == 2.5


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
