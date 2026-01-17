#!/usr/bin/env python
"""Parse the Utah Teapot OBJ file and generate Python arrays for embedding.

This script converts the Newell teapot OBJ file into Python arrays that can
be embedded directly in the Teapot scenegraph node, eliminating the dependency
on GLUT's teapot rendering functions.

Usage:
    python scripts/parse_teapot_obj.py [--obj-file PATH] [--output PATH]
"""

import argparse
import os
import sys


def parse_obj(filepath):
    """Parse an OBJ file and extract vertices, texcoords, normals, and faces.

    Args:
        filepath: Path to the OBJ file

    Returns:
        Dict with 'vertices', 'texcoords', 'normals', 'faces' lists
    """
    vertices = []
    texcoords = []
    normals = []
    faces = []

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split()
            if not parts:
                continue

            if parts[0] == 'v':
                # Vertex position: v x y z
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif parts[0] == 'vt':
                # Texture coordinate: vt u v
                texcoords.append([float(parts[1]), float(parts[2])])
            elif parts[0] == 'vn':
                # Vertex normal: vn x y z
                normals.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif parts[0] == 'f':
                # Face: f v1/vt1/vn1 v2/vt2/vn2 ...
                face_verts = []
                for vert in parts[1:]:
                    indices = vert.split('/')
                    v_idx = int(indices[0]) - 1  # OBJ indices are 1-based
                    t_idx = int(indices[1]) - 1 if len(indices) > 1 and indices[1] else -1
                    n_idx = int(indices[2]) - 1 if len(indices) > 2 and indices[2] else v_idx
                    face_verts.append((v_idx, t_idx, n_idx))
                faces.append(face_verts)

    return {
        'vertices': vertices,
        'texcoords': texcoords,
        'normals': normals,
        'faces': faces
    }


def triangulate_faces(faces, reverse_winding=True):
    """Convert quad faces to triangles using fan triangulation.

    Args:
        faces: List of faces, where each face is a list of (v_idx, t_idx, n_idx) tuples
        reverse_winding: If True, reverse vertex order for OpenGL CCW front-face convention

    Returns:
        List of triangulated faces
    """
    triangles = []
    for face in faces:
        if len(face) == 3:
            if reverse_winding:
                # Reverse winding: swap vertices 1 and 2
                triangles.append([face[0], face[2], face[1]])
            else:
                triangles.append(face)
        elif len(face) == 4:
            # Quad -> 2 triangles (fan from first vertex)
            if reverse_winding:
                # Reverse winding order
                triangles.append([face[0], face[2], face[1]])
                triangles.append([face[0], face[3], face[2]])
            else:
                triangles.append([face[0], face[1], face[2]])
                triangles.append([face[0], face[2], face[3]])
        elif len(face) > 4:
            # Polygon -> fan triangulation
            for i in range(1, len(face) - 1):
                if reverse_winding:
                    triangles.append([face[0], face[i + 1], face[i]])
                else:
                    triangles.append([face[0], face[i], face[i + 1]])
    return triangles


def build_indexed_arrays(vertices, texcoords, normals, faces):
    """Build vertex and index arrays for rendering.

    Creates interleaved vertex data (texcoord + normal + position) and index array.
    Each unique (vertex, texcoord, normal) combination becomes a single vertex.

    The vertex format is T2F_N3F_V3F (matching Box and other geometry):
    - texcoord (2 floats)
    - normal (3 floats)
    - position (3 floats)
    = 8 floats = 32 bytes per vertex

    Args:
        vertices: List of [x, y, z] vertex positions
        texcoords: List of [u, v] texture coordinates
        normals: List of [x, y, z] normals
        faces: List of triangulated faces

    Returns:
        Tuple of (vertex_data, indices) where vertex_data is interleaved
        [u, v, nx, ny, nz, x, y, z, ...] and indices is the element index array
    """
    # Map (v_idx, t_idx, n_idx) -> output vertex index
    vertex_map = {}
    vertex_data = []
    indices = []

    for face in faces:
        for v_idx, t_idx, n_idx in face:
            key = (v_idx, t_idx, n_idx)
            if key not in vertex_map:
                vertex_map[key] = len(vertex_data) // 8
                v = vertices[v_idx]
                t = texcoords[t_idx] if t_idx >= 0 and t_idx < len(texcoords) else [0, 0]
                n = normals[n_idx] if n_idx < len(normals) else [0, 1, 0]
                # T2F_N3F_V3F format: texcoord, normal, position
                vertex_data.extend(t)
                vertex_data.extend(n)
                vertex_data.extend(v)
            indices.append(vertex_map[key])

    return vertex_data, indices


import math

def rotate_y_neg90(x, z):
    """Rotate a point -90 degrees (270 degrees) around the Y axis.

    -90 degree rotation: (x, z) -> (-z, x)
    """
    return -z, x


def normalize_and_center(vertices, glut_scale=1.0):
    """Normalize vertex positions to match GLUT teapot sizing.

    The GLUT teapot with size=1.0 has these approximate dimensions:
        X (width):  -1.3 to 1.3  (total ~2.6) - spout points +X
        Y (height): -0.75 to 0.75 (total ~1.5) - lid on top
        Z (depth):  -1.575 to 1.575 (total ~3.15) - body depth

    Args:
        vertices: List of [x, y, z] positions
        glut_scale: Equivalent GLUT size parameter (default 1.0)

    Returns:
        Tuple of (normalized_vertices, scale_factor, center)
    """
    if not vertices:
        return vertices, 1.0, [0, 0, 0]

    # Find bounding box of input mesh
    min_x = min(v[0] for v in vertices)
    max_x = max(v[0] for v in vertices)
    min_y = min(v[1] for v in vertices)
    max_y = max(v[1] for v in vertices)
    min_z = min(v[2] for v in vertices)
    max_z = max(v[2] for v in vertices)

    # Center the mesh at origin (GLUT teapot is centered)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    center_z = (min_z + max_z) / 2

    center = [center_x, center_y, center_z]

    # Calculate input dimensions
    size_x = max_x - min_x  # OBJ: 4.0
    size_y = max_y - min_y  # OBJ: 3.15
    size_z = max_z - min_z  # OBJ: 6.434

    # GLUT teapot target dimensions for size=1.0
    # From freeglut source code analysis
    glut_depth = 3.15  # Z dimension of GLUT teapot with size=1.0

    # Scale to match GLUT teapot depth (Z is the defining dimension)
    # The OBJ mesh depth is ~6.434, GLUT depth is ~3.15
    # Scale factor = target / source = 3.15 / 6.434 ≈ 0.49
    scale = (glut_depth * glut_scale) / size_z if size_z > 0 else 1.0

    print(f"  Input dimensions: X={size_x:.3f}, Y={size_y:.3f}, Z={size_z:.3f}")
    print(f"  GLUT target depth: {glut_depth * glut_scale:.3f}")
    print(f"  Scale factor: {scale:.6f}")

    # Normalize vertices: center and scale (rotation applied later with normals)
    normalized = []
    for v in vertices:
        normalized.append([
            (v[0] - center[0]) * scale,
            (v[1] - center[1]) * scale,
            (v[2] - center[2]) * scale
        ])

    # Report output dimensions
    out_xs = [n[0] for n in normalized]
    out_ys = [n[1] for n in normalized]
    out_zs = [n[2] for n in normalized]
    print(f"  Output dimensions: X={max(out_xs)-min(out_xs):.3f}, Y={max(out_ys)-min(out_ys):.3f}, Z={max(out_zs)-min(out_zs):.3f}")

    return normalized, scale, center


def rotate_mesh_y_neg90(vertices, normals):
    """Rotate vertices and normals -90 degrees around Y axis.

    This orients the teapot so the spout points along +X (matching GLUT).
    The OBJ file has the spout along +Z.

    -90 degree Y rotation: (x, y, z) -> (-z, y, x)
    """
    print("Rotating mesh -90 degrees around Y axis...")

    rotated_vertices = []
    for v in vertices:
        new_x, new_z = rotate_y_neg90(v[0], v[2])
        rotated_vertices.append([new_x, v[1], new_z])

    rotated_normals = []
    for n in normals:
        new_x, new_z = rotate_y_neg90(n[0], n[2])
        rotated_normals.append([new_x, n[1], new_z])

    return rotated_vertices, rotated_normals


def negate_normals(normals):
    """Negate all normals to flip them outward.

    The OBJ file has inward-facing normals; we need outward-facing.
    """
    print("Negating normals (flipping to face outward)...")
    return [[-n[0], -n[1], -n[2]] for n in normals]


def generate_python_module(vertex_data, indices, output_path):
    """Generate a Python module with embedded teapot data.

    Args:
        vertex_data: Interleaved vertex data [u, v, nx, ny, nz, x, y, z, ...]
        indices: Triangle indices
        output_path: Path to write the Python module
    """
    # Format arrays for Python
    num_vertices = len(vertex_data) // 8
    num_triangles = len(indices) // 3

    module_content = f'''"""Utah Teapot mesh data for shader-based rendering.

This module contains pre-processed mesh data from the classic Utah Teapot,
originally created by Martin Newell in 1975 at the University of Utah.

Source:
    Original OBJ file from the Utah Teapot archive:
    https://www.cs.utah.edu/~natevm/newell_teaset/newell_teaset.zip

    The Utah Teapot is a standard reference object in computer graphics,
    created by Martin Newell. The original data is in the public domain.

Processing:
    - Parsed from teapot.obj in the newell_teaset archive
    - Centered at origin
    - Scaled to approximately match GLUT's glutSolidTeapot(1.0) sizing
    - Triangulated from quad faces
    - Texture coordinates and normals preserved from original OBJ

Data format:
- VERTEX_DATA: Interleaved array in T2F_N3F_V3F format:
  - Texture coordinate (2 floats: u, v)
  - Normal (3 floats: nx, ny, nz)
  - Position (3 floats: x, y, z)
  = 8 floats = 32 bytes per vertex
- INDICES: Triangle indices into the vertex array

Statistics:
- Vertices: {num_vertices}
- Triangles: {num_triangles}
"""

# Interleaved vertex data: T2F_N3F_V3F format
# texcoord (2) + normal (3) + position (3) = 8 floats per vertex
# Total: {num_vertices} vertices, {len(vertex_data)} floats
VERTEX_DATA = [
'''

    # Write vertex data in rows of 8 (one vertex per row)
    for i in range(0, len(vertex_data), 8):
        row = vertex_data[i:i+8]
        formatted = ', '.join(f'{v:.6f}' for v in row)
        module_content += f'    {formatted},\n'

    module_content += f''']\n
# Triangle indices: {num_triangles} triangles, {len(indices)} indices
INDICES = [
'''

    # Write indices in rows of 12 (4 triangles per row)
    for i in range(0, len(indices), 12):
        row = indices[i:i+12]
        formatted = ', '.join(str(idx) for idx in row)
        module_content += f'    {formatted},\n'

    module_content += ']\n'

    with open(output_path, 'w') as f:
        f.write(module_content)

    print(f"Generated {output_path}")
    print(f"  Vertices: {num_vertices}")
    print(f"  Triangles: {num_triangles}")
    print(f"  Vertex data size: {len(vertex_data) * 4} bytes")
    print(f"  Index data size: {len(indices) * 4} bytes")


def main():
    parser = argparse.ArgumentParser(description='Parse teapot OBJ file')
    parser.add_argument('--obj-file', '-i',
                       default=os.path.expanduser('~/Downloads/teapot/newell_teaset/teapot.obj'),
                       help='Path to input OBJ file')
    parser.add_argument('--output', '-o',
                       default='OpenGLContext/scenegraph/teapot_data.py',
                       help='Path to output Python module')
    parser.add_argument('--glut-scale', '-s',
                       type=float, default=1.0,
                       help='GLUT equivalent size parameter (default: 1.0)')

    args = parser.parse_args()

    if not os.path.exists(args.obj_file):
        print(f"Error: OBJ file not found: {args.obj_file}")
        sys.exit(1)

    print(f"Parsing {args.obj_file}...")
    data = parse_obj(args.obj_file)

    print(f"  Raw vertices: {len(data['vertices'])}")
    print(f"  Raw texcoords: {len(data['texcoords'])}")
    print(f"  Raw normals: {len(data['normals'])}")
    print(f"  Raw faces: {len(data['faces'])}")

    # Normalize vertices to match GLUT teapot dimensions
    print(f"Normalizing vertices (GLUT scale: {args.glut_scale})...")
    data['vertices'], scale, center = normalize_and_center(data['vertices'], args.glut_scale)
    print(f"  Original center: {center}")

    # Rotate mesh -90 degrees around Y to match GLUT orientation (spout along +X)
    data['vertices'], data['normals'] = rotate_mesh_y_neg90(data['vertices'], data['normals'])

    # Note: We reverse face winding order in triangulate_faces() to match OpenGL's
    # CCW front-face convention. The OBJ normals are correct (outward-facing).

    # Triangulate faces
    print("Triangulating faces...")
    triangles = triangulate_faces(data['faces'])
    print(f"  Triangles: {len(triangles)}")

    # Build indexed arrays
    print("Building indexed arrays...")
    vertex_data, indices = build_indexed_arrays(
        data['vertices'], data['texcoords'], data['normals'], triangles
    )

    # Generate Python module
    generate_python_module(vertex_data, indices, args.output)


if __name__ == '__main__':
    main()
