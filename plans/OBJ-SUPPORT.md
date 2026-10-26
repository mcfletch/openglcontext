# OBJ support

Status: landed on branch `obj-modern`, 2026-10-26. Not merged. preflight not run.

## What it is

`Loader.load('model.obj')` returns a scene of `PBRMesh` shapes in
`PhysicalMaterial` appearances, the nodes a glTF model loads as. Reading is four
modules and a handler:

- `loaders/objfile.py` reads OBJ text into arrays: triangles, line segments and
  points per part and material. No scenegraph, no GL.
- `loaders/mtlfile.py` reads MTL libraries into `MtlMaterial` records.
- `loaders/objimages.py` is the picture arithmetic: channel packing, height to
  normal map, alpha merge.
- `loaders/objmaterials.py` turns records into appearances and finds libraries
  and textures beside the model.
- `loaders/obj.py` is the loader handler that assembles the scene.

User documentation is `docs/loading.rst#loading-obj`.

## Decisions

- Materials are `PhysicalMaterial`, as STL, PLY and OFF already are. A VRML97
  `Material` cannot carry roughness, metalness, a normal map or a clearcoat, and
  the PBR pass reads only the first of those through a conversion.
- `Ns` converts to roughness as Blender does (`1 - sqrt(Ns / 1000)`). Blender is
  where most OBJ files are written and read, so an asset looks as its author saw
  it. A diffuse map replaces `Kd` for the same reason.
- A `map_Bump` that averages violet is a normal map. Exporters write normal maps
  under `map_Bump` (Blender, Quixel); a height map and a normal map separate
  cleanly on the mean colour, since a height map has no blue to spare.
- Faces with no `vn` are flat unless an `s` group says otherwise, as the format
  states. Normals are weighted by corner angle, so n-gons cut into many
  triangles weigh as one face.
- Concave polygons are cut by ear clipping. A fan from the first corner covers
  area outside a concave outline.
- `mtllib` and texture names are tried beside the library, beside the model, by
  file name alone, and with the case of each part matched to the directory. OBJ
  files travel between Windows and Linux with absolute paths and wrong-case
  names. Every candidate goes through the loader's resolver, so none leaves the
  model's directory.
- A material that is wholly transparent (`d 0` or `Tr 1`) with no opacity map is
  drawn opaque and logged. Keenan Crane's dinoshade materials say `Tr 1.0` for
  an opaque green dinosaur; read to the letter the model is invisible.
- OBJ has no demo collection or `oglc-` command: the format is kept for
  whoever needs it, and the corpus under `tests/unit/obj_corpus/` is its
  showcase of dialects. Eight of Crane's CC0 models and a 33 MB textured sofa
  were drawn through `oglc-view` and read correctly.
- The `parse_obj` and `parse_mtl` results are plain records over NumPy arrays,
  so the format's rules are tested without a window.

## Validation

- `tests/unit/test_obj_parse.py`, `test_mtl_parse.py`, `test_obj_images.py`,
  `test_obj_materials.py`, `test_obj_scene.py`: one test per statement and rule.
- `tests/unit/test_obj_render.py` draws: texture orientation, the alpha cutout,
  vertex colours, lines and points reach the screen.
- `tests/unit/test_obj_corpus.py` and `tests/unit/obj_corpus/`: 18 files in the
  dialects of Blender, Maya, 3ds Max, MeshLab and ZBrush, with triangle counts,
  areas, bounds, part and material names worked out from the geometry. Damaged
  copies (120 per file) either read to consistent arrays or raise `ValueError`.
- `tests/unit/test_obj_trimesh.py`: trimesh reads the same files and 60 random
  polygon meshes, and the two readers agree on triangle count, area,
  area-weighted normal and bounds. The module skips where trimesh is not
  installed, and `trimesh` is in the `dev` extra so CI runs it.
- trimesh differs from the format's rules on three corpus files, each recorded
  in the manifest: relative indices (it counts back from the end of the file,
  not from the last vertex read before the face), tab-separated fields after a
  byte order mark (it raises `IndexError`), and a concave comb polygon (it cuts
  a fan from the first corner and covers twice the area).
- Speed: a 53 MB file of 490,000 quads (980,000 triangles, texture coordinates
  and normals) reads in 1.6 s; trimesh reads it in 0.9 s.

## Open

- Loading an OBJ with its sidecar files from a zip is [MODEL-ARCHIVES.md](MODEL-ARCHIVES.md).

- `tests/reference_images/using_obj.png` is drawn by the PBR path now and needs
  blessing on the main checkout when this merges: wall (155, 151, 144) against
  (136, 128, 111), roof (97, 52, 49) against (64, 23, 22).
- `tools/preflight.py openglcontext`.
- `usemap`, `maplib`, `-t` (turbulence) and free-form geometry are not read.
- `map_Ka` is not used as an occlusion map: exporters write it as a copy of the
  diffuse map as often as an ambient occlusion map.
- Reading makes one Python pass over the lines to collect statements; everything after it
  is NumPy.
