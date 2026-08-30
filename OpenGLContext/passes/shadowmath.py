"""Matrix math for shadow mapping (no OpenGL dependency).

All matrices use the row-vector convention used throughout OpenGLContext and
pyvrml97: a point ``p`` (a row vector) is transformed as ``p' = p @ M``. This
matches ``transformmatrix.perspectiveMatrix`` and the way ``FlatPass`` composes
modelview/projection matrices, so the matrices produced here can be uploaded to
GLSL with ``transpose=GL_FALSE`` exactly like the existing matrices.

Keeping this module free of OpenGL imports lets the matrix logic be unit-tested
without a GL context.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple, Union

import numpy as np
from vrml.vrml97 import transformmatrix

Vec3 = Union[Sequence[float], np.ndarray]
Matrix4 = np.ndarray


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.sqrt(np.dot(v, v)))
    if n <= 1e-12:
        return v
    return v / n


def look_at_matrix(eye: Vec3, forward: Vec3, up: Vec3 = (0.0, 1.0, 0.0)) -> Matrix4:
    """World->eye view matrix for a camera at ``eye`` looking along ``forward``.

    Row-vector convention: ``eye_space = world @ look_at_matrix(...)``. The
    resulting space is right-handed with the view direction along -Z, matching
    OpenGL / gluLookAt, so it composes correctly with
    ``transformmatrix.perspectiveMatrix``.
    """
    eye = np.asarray(eye, dtype='d')[:3]
    f = _normalize(np.asarray(forward, dtype='d')[:3])
    up = np.asarray(up, dtype='d')[:3]
    # Guard against forward parallel to up
    if abs(float(np.dot(f, _normalize(up)))) > 0.999:
        up = np.array([0.0, 0.0, 1.0]) if abs(f[1]) > 0.9 else np.array([0.0, 1.0, 0.0])
    s = _normalize(np.cross(f, up))      # right
    u = np.cross(s, f)                   # true up
    m = np.zeros((4, 4), dtype='d')
    m[0, 0], m[1, 0], m[2, 0] = s[0], s[1], s[2]
    m[0, 1], m[1, 1], m[2, 1] = u[0], u[1], u[2]
    m[0, 2], m[1, 2], m[2, 2] = -f[0], -f[1], -f[2]
    m[3, 0] = -float(np.dot(s, eye))
    m[3, 1] = -float(np.dot(u, eye))
    m[3, 2] = float(np.dot(f, eye))
    m[3, 3] = 1.0
    return m.astype('f')


def perspective_matrix(fovy: float, aspect: float, near: float, far: float) -> Matrix4:
    """Row-vector perspective projection (delegates to pyvrml97)."""
    matrix: Matrix4 = transformmatrix.perspectiveMatrix(fovy, aspect, near, far)
    return matrix.astype('f')


def near_far_from_points(
    view_matrix: Matrix4,
    points: np.ndarray,
    min_near: float = 0.05,
    margin: float = 1.05,
) -> Tuple[float, float]:
    """Fit near/far planes around ``points`` as seen from a light view matrix.

    points -- (N,3) or (N,4) array of world-space points (e.g. occluder bbox
              corners). Returns (near, far) with the view direction along -Z, so
              eye-space depth is ``-z``.
    """
    pts = np.asarray(points, dtype='d')
    if pts.ndim != 2 or pts.shape[0] == 0:
        return min_near, max(min_near * 2.0, 1.0)
    if pts.shape[1] == 3:
        pts = np.concatenate([pts, np.ones((pts.shape[0], 1))], axis=1)
    eye = pts @ view_matrix.astype('d')
    depths = -eye[:, 2]                    # distance in front of the light
    near = float(np.min(depths))
    far = float(np.max(depths))
    if far <= 0:
        # everything behind the light; nothing sensible to fit
        return min_near, max(min_near * 2.0, 1.0)
    near = max(min_near, near / margin)
    far = max(near + min_near, far * margin)
    return near, far


def spot_light_view_projection(
    position: Vec3,
    direction: Vec3,
    cutoff_angle: float,
    near: float,
    far: float,
    fov_margin: float = 1.1,
    max_fov: float = np.pi * 0.95,
) -> Tuple[Matrix4, Matrix4]:
    """View and projection matrices for a spot light's shadow map.

    cutoff_angle -- VRML97 spotlight half-angle (radians). The shadow frustum
                    uses the full cone (2*cutoff) with a small margin.
    Returns (view, projection), each row-vector form.
    """
    view = look_at_matrix(position, direction)
    fovy = min(max(cutoff_angle * 2.0 * fov_margin, 1e-3), max_fov)
    proj = perspective_matrix(fovy, 1.0, near, far)
    return view, proj


def ortho_matrix(left: float, right: float, bottom: float, top: float,
                 near: float, far: float) -> Matrix4:
    """Row-vector orthographic projection (transpose of glOrtho).

    pyvrml97's ``transformmatrix.orthoMatrix`` is in column-vector form, which is
    inconsistent with ``perspectiveMatrix``; this returns the row-vector form so
    ``eye @ ortho_matrix`` yields clip coordinates, consistent with the rest of
    the pipeline.
    """
    rl = float(right - left) or 1e-6
    tb = float(top - bottom) or 1e-6
    fn = float(far - near) or 1e-6
    m = np.zeros((4, 4), dtype='d')
    m[0, 0] = 2.0 / rl
    m[1, 1] = 2.0 / tb
    m[2, 2] = -2.0 / fn
    m[3, 0] = -(right + left) / rl
    m[3, 1] = -(top + bottom) / tb
    m[3, 2] = -(far + near) / fn
    m[3, 3] = 1.0
    return m.astype('f')


def frustum_corners_world(camera_view: Matrix4, camera_projection: Matrix4,
                          near_frac: float = 0.0, far_frac: float = 1.0) -> np.ndarray:
    """World-space corners of (a depth slice of) the camera frustum.

    near_frac/far_frac select a sub-range along the NDC depth [-1, 1]. Returns an
    (8, 3) array. Used to fit cascade shadow frusta tightly to what the camera
    sees.
    """
    inv = np.linalg.inv((camera_view.astype('d') @ camera_projection.astype('d')))
    z_near = near_frac * 2.0 - 1.0
    z_far = far_frac * 2.0 - 1.0
    corners = []
    for z in (z_near, z_far):
        for x in (-1.0, 1.0):
            for y in (-1.0, 1.0):
                clip = np.array([x, y, z, 1.0])
                world = clip @ inv
                corners.append(world[:3] / world[3])
    return np.asarray(corners, dtype='d')


def cascade_splits(near: float, far: float, count: int, blend: float = 0.5) -> list:
    """Practical split scheme: blend of logarithmic and uniform partitioning.

    Returns ``count`` far-distances (the end of each cascade), in world units.
    """
    splits = []
    for i in range(1, count + 1):
        frac = i / float(count)
        log_d = near * (far / near) ** frac
        uni_d = near + (far - near) * frac
        splits.append(blend * log_d + (1.0 - blend) * uni_d)
    return splits


def directional_cascade(light_dir: Vec3, corners_world: np.ndarray,
                        texel_snap: int = 0,
                        caster_bounds: Optional[np.ndarray] = None) -> Tuple[Matrix4, Matrix4]:
    """Light view + ortho projection fitting a directional light to frustum corners.

    light_dir -- direction the light travels (world space).
    corners_world -- (N,3) world points the cascade must cover.
    texel_snap -- if > 0, snap the ortho extents to this texel resolution to
                  reduce shimmering as the camera moves.
    caster_bounds -- optional (K,8,3) array of per-caster world-space AABB
                  corners. The frustum corners bound only the *receivers* (what
                  the camera sees), so the ortho near plane would clip any caster
                  that sits between the light and the cascade -- its shadow then
                  vanishes. When supplied, the near plane is pushed toward the
                  light far enough to keep such casters (see
                  :func:`_extend_near_for_casters`).
    Returns (view, ortho_projection), row-vector form.
    """
    corners = np.asarray(corners_world, dtype='d')
    center = corners.mean(axis=0)
    radius = float(np.max(np.linalg.norm(corners - center, axis=1)))
    f = _normalize(np.asarray(light_dir, dtype='d')[:3])
    eye = center - f * (radius * 2.0)
    view = look_at_matrix(eye, f).astype('d')
    local = np.concatenate([corners, np.ones((corners.shape[0], 1))], axis=1) @ view
    mins = local[:, :3].min(axis=0)
    maxs = local[:, :3].max(axis=0)
    if texel_snap and texel_snap > 0:
        units_per_texel = (maxs[:2] - mins[:2]) / float(texel_snap)
        units_per_texel[units_per_texel == 0] = 1e-6
        mins[:2] = np.floor(mins[:2] / units_per_texel) * units_per_texel
        maxs[:2] = np.floor(maxs[:2] / units_per_texel) * units_per_texel
    # eye looks down -Z; near/far span the local z range (negated)
    near = -maxs[2] - radius
    far = -mins[2] + radius
    if caster_bounds is not None:
        near = _extend_near_for_casters(caster_bounds, view, mins, maxs, near)
    proj = ortho_matrix(mins[0], maxs[0], mins[1], maxs[1], near, far)
    return view.astype('f'), proj.astype('f')


def _extend_near_for_casters(caster_bounds: np.ndarray, view: Matrix4,
                             mins: np.ndarray, maxs: np.ndarray,
                             near: float) -> float:
    """Pull a cascade's ortho near plane toward the light to keep up-sun casters.

    ``near`` fits the receiver frustum; a caster between the light and that
    frustum would fall in front of the near plane and be clipped out of the depth
    pass. A caster only shadows this cascade if its light-space XY *box* overlaps
    the cascade footprint (a directional light projects along -Z, so a shadow
    keeps the caster's XY). For every caster that overlaps, extend ``near`` to its
    most up-sun corner; casters elsewhere in the scene cost this cascade no depth
    precision.

    caster_bounds is (K,8,3): the 8 world-space AABB corners of each of K casters.
    Testing whole boxes (not individual corners) is what makes a caster straddling
    the footprint edge count -- its up-sun corners commonly fall outside the
    footprint XY even though the box overlaps and it does shadow the cascade.
    """
    boxes = np.asarray(caster_bounds, dtype='d')
    if boxes.ndim != 3 or boxes.shape[0] == 0:
        return near
    k = boxes.shape[0]
    flat = boxes.reshape(-1, 3)
    h = np.concatenate([flat, np.ones((flat.shape[0], 1))], axis=1)
    local = (h @ np.asarray(view, dtype='d'))[:, :3].reshape(k, -1, 3)
    box_min = local[:, :, :2].min(axis=1)
    box_max = local[:, :, :2].max(axis=1)
    overlap = ((box_max[:, 0] >= mins[0]) & (box_min[:, 0] <= maxs[0]) &
               (box_max[:, 1] >= mins[1]) & (box_min[:, 1] <= maxs[1]))
    if not np.any(overlap):
        return near
    # near is a distance in front of the eye (-z); an up-sun caster has a smaller
    # (possibly negative) distance, so take the closest-to-light overlapping box.
    caster_near = float(-local[overlap][:, :, 2].max())
    return min(near, caster_near)


# Cube-map face directions and up vectors (standard GL cubemap conventions).
# The GL cube map is left-handed while look_at_matrix builds a right-handed,
# -Z-forward view; the up flips below (+X/-X/+Z/-Z use -Y, +Y/-Y use ±Z) are what
# reconcile the two so the depth comparison samples the correct face. Verified per
# face in tests/test_cube_face_handedness.py (forward -> view -Z, up -> +Y).
CUBE_FACES = [
    ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),   # +X
    ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),  # -X
    ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),    # +Y
    ((0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),  # -Y
    ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),   # +Z
    ((0.0, 0.0, -1.0), (0.0, -1.0, 0.0)),  # -Z
]


def cube_face_view(position: Vec3, face: int) -> Matrix4:
    """View matrix for one cube-map face of a point light at ``position``."""
    forward, up = CUBE_FACES[face]
    return look_at_matrix(position, forward, up).astype('f')


def cube_projection(near: float, far: float) -> Matrix4:
    """90-degree perspective projection for cube-map shadow faces."""
    return perspective_matrix(np.pi / 2.0, 1.0, near, far).astype('f')


#: Slack a receiver leaves itself before deciding it is in shadow, in shadow-map
#: texels -- the scale of what it has to clear, since the map holds one depth per
#: texel and a surface departs from the stored value by about a texel's width
#: across one. Measured against a wall a shadow map's texels cover coarsely:
#: acne goes at 2 texels and is unchanged by 16, while the shadow's grip on the
#: object casting it never loosens (the offset scales with the same texel the
#: shadow edge is quantised to). 3 sits past the knee with room for surfaces at
#: a more grazing angle to the light than that, since there is no slope-scaled
#: term. A light overrides it with its own ``shadowBias`` field.
SHADOW_DEPTH_BIAS = 3.0

#: Below this, a depth range is a light whose casters collapsed to one distance
#: rather than a light with a shallow view, and any bias it produced would be
#: worth more than the whole range.
_MIN_DEPTH_SPAN = 1e-4
_EPS = 1e-12


def _usable_span(span: float) -> bool:
    """Whether a near-to-far range is one a bias can be expressed against."""
    return bool(np.isfinite(span)) and span > _MIN_DEPTH_SPAN


def depth_bias_terms(
    projection: Matrix4,
    texel_bias: float,
    resolution: int,
) -> Tuple[float, float, float]:
    """Coefficients turning a bias in shadow texels into ``projection``'s depth.

    A receiver nudges its own depth toward the light before comparing it with the
    map. What it has to clear is the map's own quantisation: the caster's depth
    was sampled at texel centres, so across one texel a surface departs from the
    stored value by about the width of that texel in the world. The bias is
    therefore measured in texels -- a dimensionless slack that means the same
    thing for a room and for a landscape, and does not have to be retuned when a
    light moves or a map is given more resolution.

    Two conversions stand between that and what the shader subtracts. A texel is
    a fixed width in an orthographic cascade and grows with distance in a spot or
    cube map; and depth is linear in the cascade and 1/z in the others. Returns
    ``(scale, reference, constant)``, which the shader reads as::

        offset = scale * (reference - depth) + constant

    for a window depth in 0..1. For a perspective map the two conversions cancel
    to something linear in depth: a texel is ``t * k`` wide at distance ``t`` for
    ``k = 2*tan(fov/2)/resolution``, depth is ``d = B - A/t`` for
    ``A = far*near/(far-near)`` and ``B = far/(far-near)``, so ``dd/dt`` is
    ``(B-d)**2/A`` and the product is ``k * (B - d)``. For an orthographic one
    both are constant, and the whole offset is.

    A degenerate range (a light whose casters collapsed to one distance) yields a
    zero offset rather than an infinity: no bias is a shadow with acne, an
    infinity is a scene with no shadows at all.
    """
    p = np.asarray(projection, dtype='d')
    bias = float(texel_bias)
    c, d = float(p[2][2]), float(p[3][2])
    width = float(p[0][0])
    if not width or not np.isfinite(width):
        return (0.0, 0.0, 0.0)
    # Perspective m[0][0] is cot(fov/2) over a square map, orthographic m[0][0]
    # is 2/(right-left): either way this is the texel, per unit distance for the
    # first and outright for the second.
    texel = 2.0 / (width * max(1, int(resolution)))
    if p[2][3] == 0.0:                                  # orthographic
        span = -2.0 / c if c else 0.0                   # ortho_matrix: m[2][2] = -2/(far-near)
        if not _usable_span(span):
            return (0.0, 0.0, 0.0)
        return (0.0, 0.0, bias * texel / span)
    if abs(c - 1.0) < _EPS or abs(c + 1.0) < _EPS:      # perspective
        return (0.0, 0.0, 0.0)
    near, far = d / (c - 1.0), d / (c + 1.0)
    span = far - near
    if near <= 0.0 or not _usable_span(span):
        return (0.0, 0.0, 0.0)
    return (bias * texel, far / span, 0.0)


def shadow_matrix_eye(
    camera_view: Matrix4,
    light_view: Matrix4,
    light_projection: Matrix4,
) -> Matrix4:
    """Compose an eye-space -> light-clip matrix.

    Lets the lit shader reuse its existing eye-space fragment position to look
    up the shadow map without needing a separate world-space output:

        light_clip = eye_position @ shadow_matrix_eye

    where ``shadow_matrix_eye = inv(camera_view) @ light_view @ light_projection``.
    """
    inv_cam = np.linalg.inv(camera_view.astype('d'))
    m: Matrix4 = inv_cam @ light_view.astype('d') @ light_projection.astype('d')
    return m.astype('f')
