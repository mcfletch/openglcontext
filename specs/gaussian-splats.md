# Gaussian splats: the facts the engine relies on

Sources:

- glTF extension `KHR_gaussian_splatting`, Khronos, status "Complete, Ratified"
  (`extensions/2.0/Khronos/KHR_gaussian_splatting/README.md` in the
  KhronosGroup/glTF repository, read 2026-10-09).
- X3D 4.1 Committee Draft, ISO/IEC 19775-1 clause 43 "Gaussian splats
  component" (`Part01/components/gaussianSplats.html`, read 2026-10-09), and
  the X3D 4.1 XML schema `x3d-4.1.xsd`.

Used by `OpenGLContext/scenegraph/splatmath.py`,
`OpenGLContext/scenegraph/gaussiansplats.py`,
`OpenGLContext/shaders/gaussian_splat.vert`, `gaussian_splat.frag` and
`OpenGLContext/loaders/gltf/splats.py`.

## glTF primitive

- The extension object sits on a mesh primitive. Properties: `kernel`
  (required string), `colorSpace` (required string), `projection` (optional,
  default `"perspective"`), `sortingMethod` (optional, default
  `"cameraDistance"`). Each may carry `extensions` of its own.
- Defined values: kernel `"ellipse"`; colour spaces `"srgb_rec709_display"`
  and `"lin_rec709_display"`; projection `"perspective"`; sorting method
  `"cameraDistance"`. A renderer not recognising a kernel should fall back to
  `"ellipse"`.
- The primitive's `mode` must be POINTS (0). Its material, if any, is ignored
  for splat rendering; a renderer without the extension draws a point cloud
  with that material.
- Attributes, one value per splat:

  | Semantic | Type | Component types | Required |
  |---|---|---|---|
  | `POSITION` | VEC3 | as glTF | yes |
  | `KHR_gaussian_splatting:ROTATION` | VEC4 | float; signed byte or short, normalized | yes |
  | `KHR_gaussian_splatting:SCALE` | VEC3 | float; unsigned byte or short, plain or normalized | yes |
  | `KHR_gaussian_splatting:OPACITY` | SCALAR | float; unsigned byte or short, normalized | yes |
  | `KHR_gaussian_splatting:SH_DEGREE_0_COEF_0` | VEC3 | float | yes |
  | `KHR_gaussian_splatting:SH_DEGREE_l_COEF_n`, l 1 to 3, n 0 to 2l | VEC3 | float | when that degree is used |

- Rotation is a unit quaternion in glTF order (x, y, z, w). Scale is linear
  and non-negative. Opacity is linear in [0, 1].
- Coefficients within a degree are ordered from m = -l to m = l. A degree is
  either wholly present with every lower degree, or absent.
- `COLOR_0` may carry a fallback colour for point-cloud rendering.

## Covariance and projection

- Covariance: Sigma = M C C^T M^T, M the upper 3x3 of the node's global
  transform, C = R(q) diag(s), R(q) the usual rotation matrix of the
  quaternion.
- The node's global transform should decompose into translation, rotation
  and positive scale; rendering under any other transform, or under a
  non-perspective camera, is undefined.
- Screen covariance: Sigma' = J W Sigma W^T J^T, W the view's 3x3, J the
  Jacobian of the perspective projection at the splat's view-space centre.
- The kernel is cut off at a Mahalanobis distance of 3.

## Colour

- Real spherical harmonics with the Condon-Shortley phase. Basis constants:
  0.2820947917738781 (l 0); 0.4886025119029199 for l 1 with signs -y, +z, -x;
  for l 2: 1.092548430592079 xy, -1.092548430592079 yz,
  0.3153915652525200 (2z^2 - x^2 - y^2), -1.092548430592079 xz,
  0.5462742152960395 (x^2 - y^2); for l 3: -0.5900435899266435 y(3x^2 - y^2),
  2.890611442640554 xyz, -0.4570457994644657 y(4z^2 - x^2 - y^2),
  0.3731763325901154 z(2z^2 - 3x^2 - 3y^2), -0.4570457994644657 x(4z^2 - x^2 - y^2),
  1.445305721320277 z(x^2 - y^2), -0.5900435899266435 x(x^2 - 3y^2).
- Colour = sum of each coefficient times its basis term + 0.5. The direction
  is the unit vector from the camera position to the splat's centre, in
  global space. Negative colours are clamped to zero.
- The coefficients should be turned by the rotation part of the node's global
  transform.
- Implementations may ignore the higher degrees.
- The colour is display-referred: scene lighting, exposure and tone mapping
  do not apply. Blending is done before any colour-space or transfer
  conversion.

## Composition

- Splats are sorted back to front by the distance from the camera position
  to each splat's centre in global space, and alpha blended:
  C = sum_i c_i a_i prod_{j<i} (1 - a_j), with a_i the opacity times the
  projected Gaussian at the pixel centre.
- With a normalized colour buffer, blending passes the premultiplied c_i a_i
  with a source factor of one.

## X3D node

- `GaussianSplats : X3DGaussianSplatsNode` (X3DChildNode, X3DBoundedObject),
  component GaussianSplats level 1, prerequisites Core 1, Grouping 1, Shape 1,
  Rendering 1, Texturing 1.
- Fields: `bboxDisplay`, `castShadow`, `colorSpace` ("SRGB_REC709_DISPLAY" or
  "LIN_REC709_DISPLAY", default the first), `metadata`, `opacities` (MFFloat),
  `orientations` (MFQuaternion, x y z w), `pointerEvents`, `positions`
  (MFVec3f), `scales` (MFVec3f, non-negative), the sixteen
  `sphericalHarmonicsDegree<l>Coef<n>` (MFVec3f), `visible`, `bboxCenter`,
  `bboxSize`.
- The clause defers the field semantics and formulas to
  `KHR_gaussian_splatting`. `castShadow` says whether the node casts shadows;
  a node with `visible` false casts none. `pointerEvents` false leaves the
  node out of pointer picking.
- Defaults differ between the draft's text and its schema: the text gives
  `castShadow` and `pointerEvents` FALSE, the schema `true`. pyvrml97
  declares the schema's.
