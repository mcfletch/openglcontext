"""``physics-cook`` — bake OMI physics colliders into a glTF.

Annotates every mesh-bearing node that has no physics body with an
``OMI_physics_shape`` (``convex`` for dynamic bodies, ``trimesh`` for static
world geometry) and an ``OMI_physics_body`` collider, so the asset imports with
collision for free (mirrors the ``parthenon-bake`` tool).  Because OMI
``convex`` / ``trimesh`` reference the glTF mesh by index, no geometry is
duplicated.  Runs on ``.gltf`` JSON documents.
"""
import argparse
import json
import sys

from omi_physics import model


def cook_document(gltf, motion_type=model.STATIC, mass=1.0):
    """Add OMI shapes + colliders to mesh nodes lacking a physics body.

    Mutates and returns ``gltf`` (a parsed glTF dict).  Idempotent: nodes that
    already carry ``OMI_physics_body`` are left untouched.
    """
    ext = gltf.setdefault('extensions', {})
    shape_ext = ext.setdefault('OMI_physics_shape', {})
    shapes = shape_ext.setdefault('shapes', [])
    used = gltf.setdefault('extensionsUsed', [])
    for name in ('OMI_physics_shape', 'OMI_physics_body'):
        if name not in used:
            used.append(name)

    shape_type = 'trimesh' if motion_type == model.STATIC else 'convex'
    shape_for_mesh = {}

    def shape_index(mesh):
        if mesh not in shape_for_mesh:
            shape_for_mesh[mesh] = len(shapes)
            shapes.append({'type': shape_type, shape_type: {'mesh': mesh}})
        return shape_for_mesh[mesh]

    count = 0
    for node in gltf.get('nodes', []):
        mesh = node.get('mesh')
        if mesh is None:
            continue
        node_ext = node.setdefault('extensions', {})
        if 'OMI_physics_body' in node_ext:
            continue
        body = {'collider': {'shape': shape_index(mesh)}}
        if motion_type != model.STATIC:
            body['motion'] = {'type': motion_type, 'mass': mass}
        else:
            body['motion'] = {'type': model.STATIC}
        node_ext['OMI_physics_body'] = body
        count += 1
    return gltf, count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='input .gltf document')
    parser.add_argument('-o', '--output', help='output path (default: overwrite)')
    parser.add_argument('--motion', choices=[model.STATIC, model.DYNAMIC],
                        default=model.STATIC, help='body type for cooked colliders')
    parser.add_argument('--mass', type=float, default=1.0)
    args = parser.parse_args(argv)

    with open(args.input) as f:
        gltf = json.load(f)
    gltf, count = cook_document(gltf, motion_type=args.motion, mass=args.mass)
    out = args.output or args.input
    with open(out, 'w') as f:
        json.dump(gltf, f, indent=2)
    print('physics-cook: added %d collider(s) -> %s' % (count, out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
