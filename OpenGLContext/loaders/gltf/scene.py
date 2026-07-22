"""Scene assembly: walk a parsed glTF node graph into an OpenGLContext scenegraph.

The high level of the loader. :class:`GLTFScene` is the loader's return value -- a
renderable ``Transform`` subtree plus the framing bounds, cameras, viewpoints,
DEF registry, animations and skins a caller needs. :class:`_SceneBuilder` does the
recursive walk: each glTF node becomes its own ``Transform`` (registered under a
DEF name so it is addressable), its mesh primitives are decoded through
:mod:`meshes`, its KHR_lights_punctual light and camera are placed in world space,
world-space bounds accumulate for framing, and EXT_mesh_gpu_instancing nodes fan
out into per-instance Transforms. Cycles in the node graph are rejected with a
located error rather than overflowing the stack.

The builder leans on the lower layers -- :mod:`meshes`, :mod:`transforms`,
:mod:`animation`, :mod:`accessors` -- and hands the assembled ``GLTFScene`` back to
the public entry points in :mod:`loader`.
"""
from __future__ import annotations

import re

import numpy as np

from OpenGLContext.scenegraph.basenodes import (
    Transform, Viewpoint, DirectionalLight, PointLight, SpotLight,
)
from OpenGLContext.scenegraph.scenegraph import SceneGraph
from OpenGLContext.loaders.gltf.accessors import _read_normalized
from OpenGLContext.loaders.gltf.meshes import _primitive_shape
from OpenGLContext.loaders.gltf.transforms import (
    _transform_for, _local_matrix_rv, _expand_bounds, look_orientation, _quat_to_xyzr,
)
from OpenGLContext.loaders.gltf.animation import (
    Player, compute_world_matrices,
    _trs_animated_nodes, _build_animations, _register_morph, _register_skin,
)


class GLTFScene(object):
    """Result of loading a glTF: a scenegraph subtree plus framing bounds.

    ``group`` is a ``Transform`` holding the glTF's root nodes (each glTF node is
    its own child ``Transform``); it is the renderable root a caller mounts in a
    scene. ``sceneGraph`` is its parent ``SceneGraph`` carrying the DEF registry,
    so ``getDEF(name)`` returns an individual imported node for manipulation.
    """

    def __init__(self, group, center, radius, camera=None, cameras=None,
                 viewpoints=None, sceneGraph=None, animations=None,
                 node_transforms=None):
        self.group = group
        self.center = center      # (x, y, z) of the bounding box centre
        self.radius = radius      # bounding-sphere radius (for camera framing)
        # animations: list of Animation objects parsed from the file, in
        # order. node_transforms: glTF node index -> the Transform built for it, so
        # a Player can write interpolated TRS straight into the scenegraph.
        self.animations = animations if animations is not None else []
        self.node_transforms = node_transforms if node_transforms is not None else {}
        # node_morph: node index -> [weight-setter callables], one per primitive of
        # the node's morphable mesh (populated by the loader when targets exist).
        self.node_morph = {}
        # skins: Skin objects; the loader also stashes the node
        # hierarchy (_skin_roots/_skin_children) for per-frame joint assembly.
        self.skins = []
        self._skin_roots = []
        self._skin_children = {}
        # camera: None, or a dict with position/forward/up/fov/near/far taken from
        # the first camera the glTF defines (so a viewer can adopt its viewpoint).
        self.camera = camera
        # cameras: list of such dicts, one per camera the glTF defines, in order
        # (each also carries a 'name'). A viewer can offer next/previous cycling.
        self.cameras = cameras if cameras is not None else ([camera] if camera else [])
        # viewpoints: one root-space Viewpoint node per glTF camera (same order),
        # DEF-registered by camera name. Mount these in the rendered scenegraph to
        # switch cameras through OpenGLContext's standard bindable mechanism.
        self.viewpoints = viewpoints if viewpoints is not None else []
        # sceneGraph: a vrml SceneGraph whose defNames registry maps each glTF
        # node's DEF (its name, or ``node<index>`` when unnamed) to the Transform
        # created for it, so a caller can grab and manipulate one node by name.
        self.sceneGraph = sceneGraph
        # Camera exposure (1.0 = neutral). Set by the loader's light meter when the
        # scene carries absolute-unit KHR_lights_punctual lights; a viewer forwards
        # it to the PBR pass so the frame doesn't clip to white.
        self.exposure = 1.0

    def getDEF(self, name):
        """Return the Transform node imported from the glTF node with this DEF
        name (its glTF ``name``, or ``node<index>`` if the glTF node was
        unnamed), or None. The name is looked up in the SceneGraph registry."""
        if self.sceneGraph is None:
            return None
        return self.sceneGraph.getDEF(name)

    def player(self, index=0, loop=True):
        """A :class:`~OpenGLContext.loaders.gltf.animation.Player` bound to animation ``index``.

        Returns None when the file defines no animations. The player writes
        interpolated TRS into ``node_transforms`` and morph weights into
        ``node_morph``; call ``player.evaluate(t)`` once per frame.
        """
        if not self.animations or not (0 <= index < len(self.animations)):
            return None
        compute_worlds = None
        if self.skins:
            roots, children, nts = (self._skin_roots, self._skin_children,
                                    self.node_transforms)
            compute_worlds = lambda: compute_world_matrices(roots, children, nts)
        return Player(self.animations[index], self.node_transforms,
                      node_morph=self.node_morph, loop=loop,
                      skins=self.skins, compute_worlds=compute_worlds)


def _scene_root_indices(g):
    """Root node indices to build, tolerant of missing/empty scenes.

    ``scene.nodes`` may be absent or ``None`` (then there are no roots, rather than
    a ``TypeError``). With no scenes declared at all, the roots are the nodes that
    are not a child of any other node -- so a node isn't built once as a root and
    again as someone's child (the old ``range(len(nodes))`` fallback did both).
    """
    nodes = g.nodes or []
    if g.scenes:
        scene = g.scenes[g.scene or 0]
        return list(getattr(scene, 'nodes', None) or [])
    child_ids = set()
    for node in nodes:
        for c in (getattr(node, 'children', None) or []):
            child_ids.add(c)
    return [i for i in range(len(nodes)) if i not in child_ids]


# VRML forbids these in a DEF token (whitespace/controls and the reserved
# delimiters); a glTF name may contain any of them, so they're replaced by '_'.
_DEF_RESERVED = re.compile(r'[\x00-\x20"#\',.\[\]{}\\+-]')


def _def_name(raw, index):
    """DEF token for a glTF node.

    Uses the node's glTF ``name`` (characters VRML forbids in a DEF replaced by
    ``_``, a leading digit prefixed) so a caller can find the node by the name the
    asset author gave it; falls back to a stable ``node<index>`` for the many glTF
    nodes that carry no name.
    """
    raw = (raw or '').strip()
    if not raw:
        return 'node%d' % index
    tok = _DEF_RESERVED.sub('_', raw)
    if tok[0].isdigit():
        tok = '_' + tok
    return tok


def _unique_def(base, used):
    """Keep DEF names unique so duplicate glTF names stay individually
    addressable (glTF node names need not be unique); appends ``_001`` ..."""
    name = base
    i = 1
    while name in used:
        name = '%s_%03d' % (base, i)
        i += 1
    used.add(name)
    return name


def gpu_instance_transforms(g, ext_dict, resolver):
    """Per-instance Transforms for an EXT_mesh_gpu_instancing node.

    The extension carries optional TRANSLATION (VEC3), ROTATION (VEC4 quaternion)
    and SCALE (VEC3) accessors, one entry per instance, all the same length. Each
    instance becomes a Transform; wrapping the node's (shared) mesh shapes in these
    lets the normal instancing path collapse them into one draw. Returns [] when
    the extension names no attributes.
    """
    attrs = (ext_dict or {}).get('attributes') or {}
    ti, ri, si = attrs.get('TRANSLATION'), attrs.get('ROTATION'), attrs.get('SCALE')
    T = R = S = None
    count = 0
    # _read_normalized honours accessor.normalized, so a quantized (normalized byte/
    # short) ROTATION quaternion is dequantized to [-1,1] instead of read as raw ints
    # (which produced garbage rotations); float accessors pass straight through.
    if ti is not None:
        T = _read_normalized(g, ti, resolver); count = len(T)
    if ri is not None:
        R = _read_normalized(g, ri, resolver); count = max(count, len(R))
    if si is not None:
        S = _read_normalized(g, si, resolver); count = max(count, len(S))
    out = []
    for i in range(count):
        t = Transform()
        if T is not None:
            t.translation = tuple(float(x) for x in T[i])
        if S is not None:
            t.scale = tuple(float(x) for x in S[i])
        if R is not None:
            t.rotation = _quat_to_xyzr([float(x) for x in R[i]])
        out.append(t)
    return out


def _one_camera_pose(world, cam):
    """World pose + perspective params for a single (world_matrix, camera_def).

    World matrices are row-vector (p' = p @ M). A glTF camera looks down its
    local -Z with +Y up; we report world-space position/forward/up.
    """
    pos = (np.array([0, 0, 0, 1.0]) @ world)[:3]
    forward = (np.array([0, 0, -1.0, 0.0]) @ world)[:3]
    up = (np.array([0, 1.0, 0, 0.0]) @ world)[:3]
    persp = getattr(cam, 'perspective', None)
    fov = float(persp.yfov) if (persp and persp.yfov) else np.pi / 4.0
    near = float(persp.znear) if (persp and persp.znear) else None
    far = float(persp.zfar) if (persp and getattr(persp, 'zfar', None)) else None
    return {
        'name': getattr(cam, 'name', None) or 'camera',
        'position': tuple(float(v) for v in pos),
        'forward': tuple(float(v) for v in (forward / (np.linalg.norm(forward) or 1))),
        'up': tuple(float(v) for v in (up / (np.linalg.norm(up) or 1))),
        'fov': fov, 'near': near, 'far': far,
    }


def _camera_poses(cameras):
    """World poses for every (world_matrix, camera_def), in node order."""
    return [_one_camera_pose(world, cam) for world, cam in cameras]


def _viewpoints_for_poses(poses, scene_graph, used_defs):
    """Build one root-space ``Viewpoint`` node per camera pose, in order.

    Each Viewpoint is authored in world space (the loader already resolved the
    camera's world pose), so mounted directly under the scene root it reproduces
    the glTF camera exactly. It is DEF-registered under the camera's name (made
    unique) so it is addressable, and carries ``near``/``far`` as plain attributes
    for :meth:`Viewpoint.moveTo` to apply. Prefer names over indices, per the
    glTF-camera intent.
    """
    viewpoints = []
    for i, pose in enumerate(poses):
        vp = Viewpoint(
            position=tuple(pose['position']),
            orientation=look_orientation(pose['forward'], pose['up']),
            fieldOfView=pose['fov'],
            description=pose.get('name') or 'camera',
        )
        vp.near = pose.get('near')
        vp.far = pose.get('far')
        scene_graph.regDefName(
            _unique_def(_def_name(pose.get('name'), i), used_defs), vp)
        viewpoints.append(vp)
    return viewpoints


def _camera_pose(cameras):
    """World pose of the first glTF camera, or None (back-compat helper)."""
    poses = _camera_poses(cameras)
    return poses[0] if poses else None


def _meter_exposure(light_meter, center):
    """A camera exposure that stops absolute-unit punctual scenes down, else 1.0.

    glTF KHR_lights_punctual intensities are physical (point/spot candela,
    directional lux); a scene authored with real values (hundreds to thousands)
    clips to white without a camera exposure, exactly the job a light meter does.
    Estimate the strongest illuminance any light delivers near the scene centre --
    directional is illuminance directly, point/spot is intensity / d^2 -- and expose
    so that peak maps to a fixed target. Never brightens (result <= 1.0), so
    normalized test scenes (intensity ~1) and IBL/analytic-lit scenes stay at 1.0.
    """
    if not light_meter:
        return 1.0
    c = np.asarray(center, dtype='d')
    key = 0.0
    for light, wpos in light_meter:
        intensity = float(light.intensity)
        if wpos is None:                      # directional: illuminance == intensity
            key = max(key, intensity)
        else:
            d2 = float(np.sum((np.asarray(wpos, dtype='d') - c) ** 2))
            key = max(key, intensity / max(d2, 1e-3))
    # Only stop down scenes whose lights genuinely overexpose. Modestly-lit scenes
    # (a few lux -- e.g. the Parthenon rig, IridescenceSuzanne) already read right at
    # neutral exposure and must stay at 1.0 so their baselines don't shift; only the
    # absolute-unit test scenes (hundreds+ of lux/candela) cross this threshold.
    TARGET = 6.0
    return min(1.0, TARGET / max(key, TARGET))


def _light_node(light_def, world):
    """Build a scenegraph light from a KHR_lights_punctual light + world matrix.

    Intensities/colours are passed through as authored. Directional lights cast
    shadows by default (the usual key light); point/spot lights do not, so a
    scene can add fill lights without multiplying the shadow cost.
    """
    if not isinstance(light_def, dict):
        return None
    kind = (light_def.get('type') or 'point').lower()
    color = tuple(light_def.get('color', (1.0, 1.0, 1.0)))[:3]
    intensity = float(light_def.get('intensity', 1.0))
    # The light is mounted as a child of its glTF node's Transform, so the render
    # pass applies that node's world matrix to these coordinates. Keep them LOCAL
    # -- the KHR light sits at its node origin (0,0,0) pointing down local -Z.
    # (Baking the world position here as well would transform the light twice, which
    # left off-centre lights displaced past their targets.)
    pos = (0.0, 0.0, 0.0)
    direction = (0.0, 0.0, -1.0)
    shadows = bool(light_def.get('castShadows', kind == 'directional'))
    if kind == 'directional':
        # Directional intensity is illuminance (lux); no distance falloff.
        return DirectionalLight(direction=direction, color=color,
                                intensity=intensity, castShadows=shadows)
    # KHR_lights_punctual point/spot intensity is luminous intensity (candela) and
    # falls off inverse-square, windowed by an optional `range`. VRML attenuation
    # (constant, linear, quadratic) expresses that as pure quadratic (0,0,1); the
    # `range` is stashed for the shader's range-window (`_gltf_range` -> lightRange).
    # An explicit `attenuation` (non-standard bake field) still overrides.
    atten = tuple(float(v) for v in light_def.get('attenuation', (0, 0, 1)))[:3]
    rng = float(light_def.get('range', 0.0) or 0.0)
    if kind == 'spot':
        # KHR spot.*ConeAngle are half-angles measured from the axis, which is
        # exactly the VRML SpotLight.cutOffAngle/beamWidth convention (the outer
        # bound of the cone). Store them as-is; the shader's spot attenuation reads
        # cos(cutOffAngle) directly and the shadow projection uses the full cone FOV
        # = 2*cutOffAngle. (Previously these were doubled, which lit -- and needed
        # the shadow matrix to re-halve -- a cone twice the authored width.)
        spot = light_def.get('spot') or {}
        outer = float(spot.get('outerConeAngle', np.pi / 4.0))
        inner = float(spot.get('innerConeAngle', 0.0))
        light = SpotLight(location=pos, direction=direction, color=color,
                          intensity=intensity, castShadows=shadows, attenuation=atten,
                          cutOffAngle=outer, beamWidth=inner)
    else:
        light = PointLight(location=pos, color=color, intensity=intensity,
                           castShadows=shadows, attenuation=atten)
    light._gltf_range = rng
    return light


class _SceneBuilder:
    """Builds a :class:`GLTFScene` from a parsed glTF document.

    ``build`` walks the node graph recursively, accumulating the render Transform
    tree, world-space bounds, cameras, lights, morph/skin registries and the DEF
    registry as explicit instance state.

    KHR_animation_pointer is driven LIVE by the Player, so ``pointer_time`` is
    accepted for API compatibility and ignored -- the Player, pinned to the
    capture time, reproduces a posed still.
    """

    def __init__(self, g, resolver, pointer_time=None):
        self.g = g
        self.resolver = resolver
        self.mat_cache = {}
        self.tex_cache = {}
        self.mesh_cache = {}   # decoded mesh shapes + local bounds per mesh index
        # SceneGraph holds the DEF registry; every node's Transform is registered
        # under a DEF so a caller can grab it by name (see _def_name).
        self.scene_graph = SceneGraph()
        self.used_defs = set()
        self.world_min = np.array([np.inf] * 3)
        self.world_max = np.array([-np.inf] * 3)
        self.cameras = []       # (world_matrix, camera_def)
        self.light_meter = []   # (light_node, world_position or None) for auto-exposure
        self.node_transforms = {}   # node index -> the Transform built for it
        self.node_light = {}        # node index -> the light node built for it
        self.node_morph = {}        # node index -> [morph-weight setter callables]
        self.skins = []             # Skin, one per skinned mesh node
        # TRS-animated nodes must be plain Transforms (glTF forbids a ``matrix`` on
        # an animated node) so a Player's TRS writes drive the localMatrix.
        self.trs_animated = _trs_animated_nodes(g)
        # KHR_lights_punctual light defs (raw dicts), or [] if the ext is absent.
        top_ext = getattr(g, 'extensions', None) or {}
        self.light_defs = []
        if isinstance(top_ext, dict):
            self.light_defs = (top_ext.get('KHR_lights_punctual', {}) or {}).get('lights', []) or []

    def mesh_shapes(self, mesh_index):
        if mesh_index in self.mesh_cache:
            return self.mesh_cache[mesh_index]
        shapes = []
        dynamic = False
        for prim in self.g.meshes[mesh_index].primitives:
            shape, bounds = _primitive_shape(
                self.g, prim, self.resolver, self.mat_cache, self.tex_cache)
            if shape is not None:
                shapes.append((shape, bounds))
                geo = shape.geometry
                if getattr(geo, 'morph_targets', None) or \
                        getattr(geo, 'skin_joints', None) is not None:
                    dynamic = True
        # A morphed/skinned mesh carries its own deformed vertex state, so nodes
        # that reference it must each get their own copy (independent weights /
        # joint matrices) -- never share it via the cache.
        if not dynamic:
            self.mesh_cache[mesh_index] = shapes
        return shapes

    def build(self, node_index, parent_world, ancestry=(), parent_visible=True):
        # A glTF node graph is meant to be a forest, but nothing in the format
        # prevents a node from listing an ancestor as a child. Walking that with
        # plain recursion stack-overflows; track the current path and reject a
        # revisit with a located error instead.
        if node_index in ancestry:
            raise ValueError(
                "glTF node graph has a cycle: node %d is its own ancestor via %s"
                % (node_index, list(ancestry)))
        ancestry = ancestry + (node_index,)
        node = self.g.nodes[node_index]
        group = _transform_for(node, force_trs=node_index in self.trs_animated)
        self.node_transforms[node_index] = group
        # regDefName stamps group.DEF and registers it in scene_graph.defNames.
        self.scene_graph.regDefName(
            _unique_def(_def_name(getattr(node, 'name', None), node_index), self.used_defs),
            group)
        # row-vector world matrix, identical to what the Transform node applies
        # at render time (p_world = p_local @ local @ parent), so bounds match.
        world = _local_matrix_rv(group) @ parent_world
        # Accumulate children into one list and assign once: repeatedly rebuilding
        # ``group.children`` was O(n^2) in the node/primitive count.
        children = list(group.children)
        node_ext = getattr(node, 'extensions', None) or {}
        # KHR_node_visibility: an invisible node -- or any descendant of one --
        # contributes no drawn geometry or light and isn't counted in the framing
        # bounds. Visibility is the AND of this node's flag and its ancestors'
        # (the spec requires a node drawn only if it and every ancestor is visible),
        # so the flag threads down the recursion as `parent_visible`. The authored
        # initial flag may itself be a KHR_animation_pointer target baked in above.
        node_visible = parent_visible
        gpu_inst = None
        if isinstance(node_ext, dict):
            nv = node_ext.get('KHR_node_visibility')
            if isinstance(nv, dict):
                node_visible = node_visible and bool(nv.get('visible', True))
            gi_ext = node_ext.get('EXT_mesh_gpu_instancing')
            if gi_ext:
                gpu_inst = gpu_instance_transforms(self.g, gi_ext, self.resolver)
        if node.mesh is not None and node_visible:
            shapes = self.mesh_shapes(node.mesh)
            if gpu_inst:
                # One Transform per instance, all wrapping the SAME shared mesh
                # shapes -> the instancing path draws them in one call.
                for inst_t in gpu_inst:
                    inst_world = _local_matrix_rv(inst_t) @ world
                    inst_kids = list(inst_t.children)
                    for shape, bounds in shapes:
                        inst_kids.append(shape)
                        _expand_bounds(inst_world, bounds, self.world_min, self.world_max)
                    inst_t.children = inst_kids
                    children.append(inst_t)
            else:
                for shape, bounds in shapes:
                    children.append(shape)
                    _expand_bounds(world, bounds, self.world_min, self.world_max)
                _register_morph(node, node_index, shapes, self.g, self.node_morph)
                _register_skin(node, node_index, shapes, self.g, self.resolver, self.skins)
        if getattr(node, 'camera', None) is not None and self.g.cameras:
            self.cameras.append((world, self.g.cameras[node.camera]))
        if isinstance(node_ext, dict) and self.light_defs and node_visible:
            li = (node_ext.get('KHR_lights_punctual', {}) or {}).get('light')
            if li is not None and 0 <= li < len(self.light_defs):
                light = _light_node(self.light_defs[li], world)
                if light is not None:
                    children.append(light)
                    self.node_light[node_index] = light   # for KHR_animation_pointer visibility
                    wpos = (None if isinstance(light, DirectionalLight) else
                            tuple(float(v) for v in (np.array([0, 0, 0, 1.0]) @ world)[:3]))
                    self.light_meter.append((light, wpos))
        for child in (node.children or []):
            children.append(self.build(child, world, ancestry, node_visible))
        group.children = children
        return group

    def run(self) -> GLTFScene:
        g = self.g
        # SceneGraph -> Transform -> [glTF root nodes]. The Transform is the single
        # renderable container (GLTFScene.group); the SceneGraph is its parent and
        # carries the DEF registry for by-name lookup.
        root = Transform()
        root.children = [self.build(ni, np.eye(4)) for ni in _scene_root_indices(g)]
        self.scene_graph.children = [root]

        if not np.isfinite(self.world_min).all():
            center, radius = (0.0, 0.0, 0.0), 1.0
        else:
            center = tuple((self.world_min + self.world_max) / 2.0)
            radius = float(np.linalg.norm(self.world_max - self.world_min) / 2.0) or 1.0
        poses = _camera_poses(self.cameras)
        viewpoints = _viewpoints_for_poses(poses, self.scene_graph, self.used_defs)
        animations = _build_animations(
            g, self.resolver, self.node_transforms, self.node_light, self.mat_cache)
        scene = GLTFScene(root, center, radius,
                          camera=(poses[0] if poses else None), cameras=poses,
                          viewpoints=viewpoints, sceneGraph=self.scene_graph,
                          animations=animations, node_transforms=self.node_transforms)
        scene.node_morph = self.node_morph
        scene.exposure = _meter_exposure(self.light_meter, center)
        scene.skins = self.skins
        # Node hierarchy for per-frame joint world-matrix assembly.
        scene._skin_roots = _scene_root_indices(g)
        scene._skin_children = {i: list(getattr(n, 'children', None) or [])
                                for i, n in enumerate(g.nodes or [])}
        if self.skins:
            # Deform to the rest/bind pose once so a static (unanimated) skinned
            # model renders posed, not in raw undeformed vertices.
            worlds = compute_world_matrices(scene._skin_roots, scene._skin_children,
                                            self.node_transforms)
            for skin in self.skins:
                skin.apply(worlds)
        return scene


def _build_scene(g, resolver, pointer_time=None) -> GLTFScene:
    return _SceneBuilder(g, resolver, pointer_time).run()
