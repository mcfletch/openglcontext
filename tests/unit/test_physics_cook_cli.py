"""physics-cook CLI: bake OMI colliders into a glTF document (no GL)."""
import copy
import pytest

from omi_physics import model, omi_gltf
from OpenGLContext.bin.physics_cook import cook_document


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
    gltf, count = cook_document(base_gltf(), motion_type=model.STATIC)
    assert count == 2
    doc = omi_gltf.load_document(gltf)
    assert all(s.type == 'trimesh' for s in doc.shapes)
    assert doc.node_bodies[0].collider.shape == doc.shapes.index(doc.shapes[0])
    assert doc.node_bodies[0].motion.type == model.STATIC


def test_dynamic_cook_adds_convex_with_mass():
    gltf, count = cook_document(base_gltf(), motion_type=model.DYNAMIC, mass=3.0)
    doc = omi_gltf.load_document(gltf)
    assert all(s.type == 'convex' for s in doc.shapes)
    assert doc.node_bodies[1].motion.type == model.DYNAMIC
    assert doc.node_bodies[1].motion.mass == 3.0


def test_extensions_registered_and_shape_shared():
    gltf, _ = cook_document(base_gltf(), motion_type=model.STATIC)
    assert 'OMI_physics_shape' in gltf['extensionsUsed']
    assert 'OMI_physics_body' in gltf['extensionsUsed']
    assert len(gltf['extensions']['OMI_physics_shape']['shapes']) == 2


def test_idempotent_on_already_cooked_nodes():
    gltf = base_gltf()
    cook_document(gltf, motion_type=model.STATIC)
    before = copy.deepcopy(gltf)
    cook_document(gltf, motion_type=model.STATIC)   # second pass
    assert gltf == before                            # no duplicate bodies/shapes


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
