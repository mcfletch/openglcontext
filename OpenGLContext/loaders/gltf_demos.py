"""Canonical per-scene metadata for the glTF demos.

One table, `DEMO_SCENES`, describes every non-trivial glTF demo we render: the
Khronos sample models plus the local Parthenon build. It is the single source of
truth shared by

* the browser demo (`OpenGLContext.bin.gltf_demo`) -- for the facing yaw and
  which materials need a lit environment,
* the doc-image gallery (`scripts/generate_doc_images.py`), and
* the regression-capture runner (`OpenGLContext.bin.gltf_regression`).

Keep new per-scene tuning here, and derive from it rather than restating it, so
every tool renders the model the same way.

The framing fields (`yaw`, `elevation`, `tilt`, `margin`) match the knobs the
viewer's auto-fit exposes (`oglc-gltf --yaw/--elevation/--tilt/--margin`); their
defaults reproduce the viewer's built-in framing, so an unlisted model still
frames sensibly and a listed model only moves for the fields it overrides.
"""
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Tuple

from OpenGLContext.loaders import resolver


@dataclass(frozen=True)
class SceneSpec:
    """How to load and frame one demo scene for capture/comparison."""

    name: str                       # Khronos sample name, or a local id (Parthenon)
    source: Optional[str] = None    # None => Khronos sample by name; else a local
                                    # path or an http(s) URL to fetch
    yaw: float = 0.0                # facing rotation about +Y (radians)
    # Default to a level, straight-on camera centred on the model. A raised camera
    # with a small fixed tilt (the old 0.22/0.10) does NOT aim at the centre, so it
    # looked above the model and cropped its bottom edge across most scenes; a hero
    # scene that wants a 3/4 look sets its own elevation/tilt.
    elevation: float = 0.0          # camera height as a fraction of the model radius
    tilt: float = 0.0               # downward camera tilt (radians)
    margin: float = 1.05            # fit factor; SMALLER => the model fills MORE of the frame
    # 'sky' (lit gradient) | 'cube' (env skybox) | 'none' (black); '' is no opinion,
    # leaving each tool its own default -- the sky for a capture, black for the
    # browser. Setting it says the *materials* need that backdrop, which is what
    # `needs_lit_backdrop` reads, so say nothing rather than restating a default.
    background: str = ''
    environment: Optional[str] = None  # cube-env face set: None => outdoor 'pimbackground';
                                       # 'studio' => the neutral studio set (bright grey
                                       # backdrop + softboxes) that the Khronos material
                                       # references use for metals/glass/anisotropy
    cameras: Tuple[int, ...] = ()   # () => one auto-framed view; else baked-camera indices
    eye: Optional[Tuple[float, float, float]] = None      # explicit camera position
    look_at: Optional[Tuple[float, float, float]] = None  # + target => interior shot
    bloom: bool = False             # HDR bloom (emissive glow halo) -- for emissive scenes
    upstream: bool = True           # a Khronos reference screenshot exists for comparison
    anim_time: Optional[float] = None  # pin animation to this time (s) for a posed,
                                       # deterministic capture; None => bind pose
    description: str = ''
    # A conformance fixture rather than something worth looking at: a bare
    # triangle, a sparse accessor, a grid of texture-transform cells. Set from
    # FEATURE_TEST_NAMES below rather than row by row, so the decision is one
    # readable list. A viewer shelves these separately; a capture run wants them
    # all the same.
    feature_test: bool = False

    @property
    def capture_background(self) -> str:
        """The backdrop a capture renders against: this scene's own choice, or the
        lit gradient sky the gallery and the regression runner default to."""
        return self.background or DEFAULT_CAPTURE_BACKGROUND

    @property
    def needs_lit_backdrop(self) -> bool:
        """Whether this scene names a backdrop that lights it, rather than black.

        Setting `background` to anything but 'none' is how a scene says its
        materials cannot be read against a black frame; every tool decides from
        this rather than from a roster of its own.
        """
        return bool(self.background) and self.background != 'none'

    def camera_ids(self) -> list[Optional[int]]:
        """The camera selectors to render: the baked indices, or a single None
        meaning 'auto-frame the model' (the `--no-cameras` path)."""
        return list(self.cameras) if self.cameras else [None]

    def slug(self, camera: Optional[int] = None) -> str:
        """Stable per-view basename: ``Name`` or ``Name__cam<NN>``."""
        if camera is None:
            return self.name
        return '%s__cam%02d' % (self.name, camera)


#: Backdrop a capture renders against when the scene expresses no preference.
DEFAULT_CAPTURE_BACKGROUND = 'sky'

# Local Parthenon build (sibling project). Resolved lazily so importing this
# module never touches the filesystem; see `parthenon_source()`.
PARTHENON_RELATIVE = ('../parthenon/parthenon.glb', '../../parthenon/parthenon.glb')

#: An authored environment from the XR Publisher project: a valley with a village
#: in it, carrying ``OMI_collider`` bodies and a document-level audio block under
#: the pre-rename ``KHR_audio`` name (so its two positional emitters are not the
#: ``KHR_audio_emitter`` the loader reads).  It is the roster's one scene that is
#: neither a Khronos sample nor built here, so it is fetched from where it is
#: published rather than vendored into a BSD tree.
XR_PUBLISHER_EXAMPLE_SCENE = (
    'https://xrpublisher.com/wp-content/uploads/2022/02/ExampleScene-26.glb')


def _cube(name: str, **kw: Any) -> SceneSpec:
    """A SceneSpec for a model that needs the image-cube environment."""
    kw.setdefault('background', 'cube')
    return SceneSpec(name, **kw)


def _studio(name: str, **kw: Any) -> SceneSpec:
    """A cube-env SceneSpec that reflects the neutral studio set, like the
    Khronos material references (metals/glass/anisotropy on a grey backdrop)."""
    kw.setdefault('background', 'cube')
    kw.setdefault('environment', 'studio')
    return SceneSpec(name, **kw)

def _studiobright(name: str, **kw: Any) -> SceneSpec:
    """A cube-env SceneSpec reflecting the near-white studio set -- for showcase
    metals/glass whose Khronos reference is shot against a bright white cyclorama
    (the lamp/dish read gold, the mirror row reads silver)."""
    kw.setdefault('background', 'cube')
    kw.setdefault('environment', 'studiobright')
    return SceneSpec(name, **kw)


def _hdr(name: str, panorama: str, **kw: Any) -> SceneSpec:
    """A cube-env SceneSpec lit and backed by a specific CC0 Poly Haven HDR panorama.

    ``panorama`` is a Poly Haven catalogue name (see :mod:`OpenGLContext.loaders.hdri`)
    or an ``.hdr`` URL/path; the capture runner loads it as both the reflected IBL
    environment and the visible skybox. Use for scenes whose reference is shot in a
    specific setting -- an indoor mirrored hall or an outdoor street for glass."""
    kw.setdefault('background', 'cube')
    kw['environment'] = panorama
    return SceneSpec(name, **kw)


# The roster. Framing overrides (tighter `margin`, `cube` background) are the ones
# dialed in during the conformance pass; everything else takes the viewer defaults.
# The wide, flat test grids overestimate their bounding sphere, so a margin < 1
# pulls the camera in until the model fills the frame instead of floating small.
DEMO_SCENES: Tuple[SceneSpec, ...] = (
    # -- conformance set: the models the QA pass flagged --------------------
    _studio('MetalRoughSpheres', margin=0.9,
          description='Metal/rough sphere grid; metals reflect the HDR studio.'),
    _studio('MetalRoughSpheresNoTextures', margin=0.9,
          description='Textureless metal/rough spheres.'),
    _studio('NegativeScaleTest', margin=0.9,
          description='Mirrored instances; normals stay outward, metals reflect env.'),
    _studio('EnvironmentTest', margin=0.9,
          description='Environment-mapping orientation reference.'),
    _studio('IridescenceMetallicSpheres', margin=0.9,
          description='KHR_materials_iridescence thin-film over metal spheres.'),
    _studio('IridescenceSuzanne', margin=0.9,
          description='Iridescence on the Suzanne head.'),
    _studio('TransmissionRoughnessTest', margin=0.9, elevation=0.15,
          description='KHR_materials_transmission with roughness frosting.'),
    _studio('TransmissionTest', margin=0.9, elevation=0.18,
          description='Transmission grid (clear glass).'),
    _studio('NormalTangentTest', margin=0.9,
              description='Computed-tangent normal mapping (no supplied TANGENT).'),
    SceneSpec('TextureTransformTest', margin=0.9,
              description='KHR_texture_transform offset/scale/rotation cells.'),
    _studio('SpecularTest', margin=0.9, description='KHR_materials_specular grid.'),
    _studio('ClearCoatTest', margin=0.9, description='KHR_materials_clearcoat grid.'),
    SceneSpec('EmissiveStrengthTest', margin=0.95, background='none', bloom=True,
              description='KHR_materials_emissive_strength; dark backdrop so the '
                          'emissive progression (dim -> blazing) reads.'),
    SceneSpec('OrientationTest', margin=1.0,
              description='Axis/orientation reference.'),
    # -- object gallery: single hero shots ---------------------------------
    _studio('DamagedHelmet', yaw=-0.6, elevation=0.05, margin=0.9,
              description='PBR helmet, visor facing camera.'),
    _studio('WaterBottle', yaw=-0.6, elevation=0.05, margin=0.9,
              description='Metallic bottle.'),
    _studio('BoomBox', yaw=-0.6, elevation=0.05, margin=0.9, description='Boom box.'),
    SceneSpec('BarramundiFish', yaw=-0.6, elevation=0.05, margin=0.9,
              description='Fish.'),
    SceneSpec('Duck', yaw=-0.6, elevation=0.05, margin=0.9,
              description='The classic duck.'),
    _studio('IridescentDishWithOlives', yaw=-0.5, elevation=0.5, tilt=-0.32,
          margin=0.9,
          description='Look down into the iridescent dish.'),
    _studio('ToyCar', yaw=-0.6, elevation=0.05, margin=0.9,
            description='Clearcoat toy car.'),
    SceneSpec('Avocado', yaw=-0.6, elevation=0.05, description='Avocado.'),
    SceneSpec('Lantern', yaw=-0.6, elevation=0.05, description='Lantern.'),
    # -- full glTF-Sample-Assets coverage ----------------------------------
    # Every remaining Khronos sample that ships a self-contained .glb. These use
    # default (or grid-tightened) framing; reflective/transmissive materials get
    # the image-cube env. Animated/skinned/morph models render their t=0 frame,
    # so the captured view is a starting pose, not a canonical animation still.
    # Baselines here are captured but NOT yet blessed -- review before --bless.
    _cube('ABeautifulGame', yaw=0.6, elevation=0.12, tilt=0.05, margin=0.9,
          description='Marble chess set; close low 3/4 hero angle.'),
    SceneSpec('AlphaBlendModeTest', margin=0.95),
    SceneSpec('AnimatedColorsCube'),
    SceneSpec('AnimatedMorphCube', anim_time=1.0),
    _studio('AnimationPointerUVs', margin=0.95, anim_time=1.0,
            description='KHR_animation_pointer driving UV transforms across a panel '
                        'grid; lit against the studio so the textured spheres read '
                        '(a black backdrop hid them).'),
    SceneSpec('AnisotropyBarnLamp', background='sky',
              description='Barn lamp modelled against a wall; neutral backdrop, not '
                          'the busy studio skybox.'),
    _studio('AnisotropyDiscTest', margin=0.95),
    _studio('AnisotropyRotationTest', margin=0.95),
    _studio('AnisotropyStrengthTest', margin=0.95),
    SceneSpec('AntiqueCamera'),
    _studio('AttenuationTest', margin=0.95),
    SceneSpec('Box'),
    SceneSpec('BoxAnimated', anim_time=1.0),
    SceneSpec('BoxInterleaved'),
    SceneSpec('BoxTextured'),
    SceneSpec('BoxTexturedNonPowerOfTwo'),
    SceneSpec('BoxVertexColors'),
    SceneSpec('BrainStem', anim_time=0.6),
    SceneSpec('CarConcept'),
    _studio('CarbonFibre', margin=0.9),
    SceneSpec('CesiumMan', anim_time=0.6),
    SceneSpec('CesiumMilkTruck', anim_time=0.6),
    _studio('ChairDamaskPurplegold'),
    _cube('ChronographWatch'),
    _cube('ClearCoatCarPaint'),
    _cube('ClearcoatWicker'),
    _cube('CommercialRefrigerator'),
    SceneSpec('CompareAlphaCoverage', margin=0.95),
    SceneSpec('CompareAmbientOcclusion', margin=0.9),
    _studio('CompareAnisotropy', margin=0.9),
    SceneSpec('CompareBaseColor', margin=0.95),
    _studio('CompareClearcoat', margin=0.95),
    _studio('CompareDispersion', margin=0.95),
    _studio('CompareEmissiveStrength', margin=0.9, bloom=True),
    _studio('CompareIor', margin=0.9),
    _studio('CompareIridescence', margin=0.95),
    _studio('CompareMetallic', margin=0.95),
    SceneSpec('CompareNormal', margin=0.95),
    SceneSpec('CompareRoughness', margin=0.95),
    _studio('CompareSheen', margin=0.95),
    _studio('CompareSpecular', margin=0.95),
    _studio('CompareTransmission', margin=0.9),
    _studio('CompareVolume', margin=0.95),
    SceneSpec('Corset'),
    SceneSpec('CubeVisibility'),
    _studio('DiffuseTransmissionPlant', margin=0.9),
    _studio('DiffuseTransmissionTeacup', yaw=0.5, elevation=0.35, tilt=-0.18,
          margin=0.9),
    _cube('DiffuseTransmissionTest', margin=0.9),
    SceneSpec('DirectionalLight', background='none',
              description='Carries its own light; render on black, no sky IBL.'),
    _studio('DispersionTest', margin=0.9, elevation=0.25, tilt=-0.15),
    _cube('DragonAttenuation', margin=0.9),
    _studio('DragonDispersion', margin=0.9),
    SceneSpec('Fox', anim_time=0.6, description='Walk-cycle character, posed mid-stride.'),
    _studio('GlamVelvetSofa'),
    _hdr('GlassBrokenWindow', 'little_paris_eiffel_tower', margin=0.9,
         description='Broken glass window; refracts/reflects an outdoor street.'),
    _hdr('GlassHurricaneCandleHolder', 'mirrored_hall', margin=0.9,
         description='Glass hurricane candle holder; indoor mirrored-hall reflections.'),
    _hdr('GlassVaseFlowers', 'mirrored_hall', margin=0.9,
         description='Glass vase of flowers; indoor reflections/refraction.'),
    _studio('IORTestGrid', margin=0.95),
    SceneSpec('InterpolationTest', margin=0.95, anim_time=1.2,
              description='Interpolation modes (step/linear/cubicspline); posed '
                          'mid-animation so the paths read (upstream is animated).'),
    _cube('IridescenceAbalone'),
    _cube('IridescenceLamp'),
    _studio('LightVisibility', anim_time=0.75,
              description='Red light node is authored invisible (its child lights '
                          'inherit that); the blue light blinks via '
                          'KHR_animation_pointer. Captured at t=0.75 (blue off) so '
                          'only the green light shows on the studio-lit wall.'),
    _studiobright('LightsPunctualLamp',
          description='Brass lamp; reflects the env (its own bulb only lights the '
                      'shade), so render against the image-cube, not black.'),
    SceneSpec('MaterialsVariantsShoe'),
    SceneSpec('MorphPrimitivesTest', margin=0.95),
    SceneSpec('MorphStressTest', margin=0.95),
    _studio('MosquitoInAmber'),
    SceneSpec('MultiUVTest', margin=0.95),
    SceneSpec('NodePerformanceTest', margin=0.95),
    SceneSpec('NormalTangentMirrorTest', margin=0.95),
    SceneSpec('PlaysetLightTest', margin=0.95, background='none'),
    SceneSpec('PointLightIntensityTest', margin=0.95, background='none'),
    _cube('PotOfCoals', elevation=0.55, tilt=-0.42, margin=1.05, bloom=True,
          description='Look down into the pot to see the glowing coals.'),
    _cube('PotOfCoalsAnimationPointer', elevation=0.55, tilt=-0.42, margin=1.05,
          anim_time=1.0, bloom=True),
    SceneSpec('RecursiveSkeletons', margin=2.6, anim_time=0.6,
              description='Recursive skeleton fractal; pull back to clear the '
                          'huge bounds (a tight margin traps the camera inside). '
                          'The clip is pinned: without a time the captured pose '
                          'is wherever the settle happened to reach, which is a '
                          'different pose on a busy machine.'),
    SceneSpec('RiggedFigure', anim_time=0.6),
    SceneSpec('RiggedSimple'),
    _studio('ScatteringSkull', yaw=-0.6, elevation=0.12, margin=0.9),
    _studio('SheenChair'),
    _studio('SheenTestGrid', margin=0.95),
    _studio('SheenWoodLeatherSofa'),
    SceneSpec('SimpleInstancing'),
    _cube('SpecGlossVsMetalRough', margin=0.95),
    _studio('SpecularSilkPouf', elevation=0.6, tilt=-0.5, margin=0.9),
    _cube('SunglassesKhronos'),
    SceneSpec('TextureCoordinateTest', margin=0.95),
    SceneSpec('TextureEncodingTest', margin=0.95),
    SceneSpec('TextureLinearInterpolationTest', margin=0.95),
    SceneSpec('TextureSettingsTest', margin=0.95),
    SceneSpec('TextureTransformMultiTest', margin=0.95),
    _studio('TransmissionOrderTest', margin=0.95),
    _studio('TransmissionThinwallTestGrid', margin=0.95),
    _studio('USDShaderBallForGltf'),
    SceneSpec('Unicode❤♻Test', margin=0.95),
    SceneSpec('UnlitTest', margin=0.95),
    SceneSpec('VertexColorTest', margin=0.95),
    SceneSpec('VirtualCity', cameras=(8,),
              description='Panoramic city dome; camera 0 is authored with a ~90 deg '
                          'roll (up ~ world +X), so use the upright aerial camera 8.'),
    SceneSpec('XmpMetadataRoundedCube'),
    # -- remaining glTF-Sample-Assets: full catalogue coverage -------------
    # The rest of the Khronos sample set (basic feature/geometry tests, the two
    # high-poly PBR helmets, Sponza, and a few material models). Default framing
    # unless the model is reflective/transmissive (cube/studio env) or wide.
    SceneSpec('AnimatedCube', anim_time=1.0),
    SceneSpec('AnimatedTriangle', anim_time=1.0, margin=0.95),
    _studio('BoomBoxWithAxes', yaw=-0.6, elevation=0.05, margin=0.9,
            description='Boom box with axis gizmos; metallic, reflects env.'),
    SceneSpec('Box With Spaces', description='Path/name with spaces (encoding test).'),
    SceneSpec('Cameras', margin=0.95, description='Two authored cameras; auto-framed here.'),
    SceneSpec('Cube', description='Textured cube, KHR_mesh_quantization.'),
    SceneSpec('FlightHelmet', yaw=-0.6, elevation=0.05, margin=0.68,
              description='Multi-file high-poly PBR helmet.'),
    _hdr('IridescenceDielectricSpheres', 'procedural_studio', yaw=0.5,
         elevation=0.28, tilt=-0.12, margin=1.2,
         description='Iridescence over dielectric spheres (3/4 view of the '
                     'thickness x IOR grid); neutral grey studio so the subtle '
                     'thin-film tint reads instead of washing to white.'),
    SceneSpec('MandarinOrange', yaw=-0.6, elevation=0.05,
              description='Diffuse-transmission mandarin.'),
    SceneSpec('MeshPrimitiveModes', margin=0.95,
              description='POINTS/LINES/TRIANGLES primitive modes.'),
    SceneSpec('MeshoptCubeTest', description='Quantized cube (KHR_mesh_quantization).'),
    SceneSpec('MultipleScenes', description='Document with several scenes; scene 0 shown.'),
    _studio('PrimitiveModeNormalsTest', margin=0.95,
            description='Per-primitive-mode normal handling; the PBR row is '
                        'metal (metallic=1), so reflect the studio env.'),
    SceneSpec('SciFiHelmet', yaw=-0.6, elevation=0.05, margin=0.68,
              description='Multi-file high-poly PBR helmet.'),
    SceneSpec('SheenCloth', margin=0.9, background='sky',
              description='Sheen cloth swatch modelled on a plane; neutral backdrop.'),
    _studio('SimpleMaterial', margin=1.0,
            description='Minimal metallic-roughness material (metallic=0.5); '
                        'reflect the studio env for the specular highlight.'),
    SceneSpec('SimpleMeshes', description='Two triangles sharing a buffer.'),
    SceneSpec('SimpleMorph', anim_time=1.0, description='Minimal morph target.'),
    SceneSpec('SimpleSkin', anim_time=0.6, description='Minimal skinned mesh.'),
    SceneSpec('SimpleSparseAccessor', margin=0.95, description='Sparse accessor override.'),
    SceneSpec('SimpleTexture', description='Minimal textured triangle.'),
    SceneSpec('Sponza', eye=(11.0, -3.5, 1.5), look_at=(-13.0, 1.0, -5.0),
              description='Sponza atrium: standing in the courtyard near one end, '
                          'looking down the arcade to the opposite second-storey corner.'),
    _studio('StainedGlassLamp', description='Transmissive stained-glass lamp.'),
    SceneSpec('Suzanne', description='Blender Suzanne, base-color material.'),
    SceneSpec('Triangle', margin=0.95, description='The minimal single triangle.'),
    SceneSpec('TriangleWithoutIndices', margin=0.95,
              description='Single triangle, non-indexed.'),
    SceneSpec('TwoSidedPlane', margin=0.95, description='Double-sided plane.'),
    # -- published elsewhere: fetched by URL, no upstream reference ---------
    SceneSpec('XRPublisherExampleScene', source=XR_PUBLISHER_EXAMPLE_SCENE,
              background='sky', upstream=False, cameras=(0,),
              description='An authored environment: a village in a valley, with '
                          'colliders and audio emitters. Shot from its own camera '
                          'because the terrain is ~700 units across, so a fit of '
                          'the whole model renders the village as a speck.'),
    # -- local Parthenon: every baked camera, no upstream reference --------
    SceneSpec('Parthenon', source='@parthenon', background='sky', upstream=False,
              cameras=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
              description='Local Parthenon build, one shot per baked camera.'),
)

#: The roster entries that exist to exercise **one glTF feature** rather than to
#: be looked at.  They are the bulk of the Khronos sample set and they are noise
#: on a shelf somebody is browsing, so the viewer gives them a section of their
#: own and the capture harness treats them exactly as before.
#:
#: Written out in full rather than matched by pattern: `Box` is a fixture and
#: `BoomBox` is a demo, `Cube` is a fixture and `AnimatedCube` is too but
#: `CarConcept` is not, and a prefix that quietly caught one more model would be
#: a model nobody could find again.
FEATURE_TEST_NAMES = (
    # Geometry and mesh basics
    'Triangle', 'TriangleWithoutIndices', 'SimpleMeshes', 'SimpleTexture',
    'SimpleMorph', 'SimpleSkin', 'SimpleSparseAccessor', 'MeshPrimitiveModes',
    'MeshoptCubeTest', 'MorphPrimitivesTest', 'MultipleScenes',
    'NodePerformanceTest', 'RiggedSimple',
    # The box/cube family: the smallest possible case of each feature
    'Box', 'Box With Spaces', 'BoxAnimated', 'BoxInterleaved', 'BoxTextured',
    'BoxTexturedNonPowerOfTwo', 'BoxVertexColors', 'Cube', 'CubeVisibility',
    'AnimatedCube', 'AnimatedTriangle', 'AnimatedColorsCube',
    'AnimatedMorphCube',
    # Texturing and colour
    'TextureCoordinateTest', 'TextureEncodingTest',
    'TextureLinearInterpolationTest', 'TextureSettingsTest',
    'TextureTransformTest', 'TextureTransformMultiTest', 'MultiUVTest',
    'NormalTangentTest', 'NormalTangentMirrorTest', 'VertexColorTest',
    'TwoSidedPlane', 'UnlitTest',
    # Lighting, cameras and orientation
    'AlphaBlendModeTest', 'Cameras', 'DirectionalLight', 'EmissiveStrengthTest',
    'InterpolationTest', 'OrientationTest', 'PointLightIntensityTest',
    # Metadata and encoding
    'XmpMetadataRoundedCube', 'Unicode❤♻Test',
    # The smallest case of a material, an instancing set-up, a winding order
    'SimpleMaterial', 'SimpleInstancing', 'NegativeScaleTest',
    'PrimitiveModeNormalsTest', 'LightVisibility',
)

#: ``*TestGrid`` is a grid of one material parameter swept across cells -- a
#: reference to check a renderer against, not a scene, exactly like ``Compare*``.
_GRID_SUFFIX = 'TestGrid'

#: Every ``Compare*`` entry is a side-by-side reference grid for one material
#: parameter, so the whole family is marked without listing each one.
_COMPARISON_PREFIX = 'Compare'


def _marked(spec: SceneSpec) -> SceneSpec:
    """``spec``, flagged if it is a conformance fixture rather than a demo."""
    from dataclasses import replace
    if (spec.name in FEATURE_TEST_NAMES
            or spec.name.startswith(_COMPARISON_PREFIX)
            or spec.name.endswith(_GRID_SUFFIX)):
        return replace(spec, feature_test=True)
    return spec


DEMO_SCENES = tuple(_marked(spec) for spec in DEMO_SCENES)

_BY_NAME = {s.name: s for s in DEMO_SCENES}

# Materials that only read correctly against a lit environment: metals reflect it
# and transmissive glass refracts it (a black backdrop renders rough glass opaque),
# and a scene lit only by its own KHR_lights_punctual bulb meters an exposure that
# leaves the rest of the model black. A scene names that need by setting
# `background`; the roster is derived from the table so the browser demo and the
# capture runner cannot drift on which models must not be shown on black. The
# browser lights them with the cheap analytic 'sky'; the capture runner honours the
# scene's own choice, so the reflection/refraction matches the Khronos reference.
ENV_BACKGROUND_MODELS = frozenset(
    s.name for s in DEMO_SCENES if s.needs_lit_backdrop)


def iter_scenes() -> Iterator[SceneSpec]:
    """Iterate the demo scenes in canonical order."""
    return iter(DEMO_SCENES)


def scene_for(name: str) -> SceneSpec:
    """The :class:`SceneSpec` for ``name`` (a default-framed spec if unlisted)."""
    return _BY_NAME.get(name) or SceneSpec(name)


def yaw_for(name: str) -> float:
    """Facing yaw (radians) for a model -- shared with the browser demo."""
    return scene_for(name).yaw


def needs_env_background(name: str) -> bool:
    """Whether the model's materials need a lit environment to read correctly."""
    return scene_for(name).needs_lit_backdrop


def find_parthenon(start: Optional[str] = None) -> Optional[str]:
    """Absolute path to a local Parthenon ``.glb``, or None if not present.

    Looked up relative to the OpenGLContext repo root so the demo/regression
    tools find the sibling ``parthenon`` project without configuration.
    """
    import os
    if start is None:
        # .../OpenGLContext/loaders/gltf_demos.py -> repo root is three up.
        start = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
    for rel in PARTHENON_RELATIVE:
        p = os.path.normpath(os.path.join(start, rel))
        if os.path.exists(p):
            return p
    return None


def resolve_source(spec: SceneSpec, parthenon: Optional[str] = None) -> Tuple[Optional[str], bool]:
    """Resolve a spec's model source to something loadable.

    Returns (source, is_local), where `is_local` says the source is a path to
    open and anything else is fetched. A Khronos sample (`source is None`)
    resolves to ``(name, False)`` -- the caller downloads/caches by name. An
    http(s) `source` is returned unchanged for the caller to fetch, which is how
    a scene published outside the Khronos catalogue joins the roster without
    being vendored into the tree. The Parthenon sentinel `'@parthenon'` resolves
    to the local ``.glb`` path (or None if the build is absent), and any other
    `source` is a local path.
    """
    if spec.source is None:
        return spec.name, False
    if spec.source == '@parthenon':
        return (parthenon or find_parthenon()), True
    if resolver.is_url(spec.source):
        return spec.source, False
    return spec.source, True
