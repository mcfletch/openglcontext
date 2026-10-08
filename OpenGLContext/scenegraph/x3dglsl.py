"""X3D's GLSL binding without GL: shader text, uniform values, attribute places

The arithmetic and text handling behind the engine's X3D shader nodes
(:mod:`OpenGLContext.scenegraph.x3dshaders`), kept apart from GL so it is
tested without a context. ISO/IEC 19775-1 component 31 and Annex I say what a
browser does with a `ComposedShader`; the names a shader reads the browser's
state through (`x3d_ModelViewMatrix`, `x3d_LightSource[i]`, ...) are the ones
X3D browsers share, which Annex I leaves to the browser.

- :func:`stage_of` reads a `ShaderPart`'s `type`; :func:`inline_source` reads
  the source a url holds in itself (a ``data:`` URI, or the text itself).
- :func:`prepare_source` makes one part's text ready for a 3.30 core
  compiler: the X3D definitions after its `#version`, a GLSL 1.10/1.20 part
  translated, a fragment stage given the engine's object-id output.
- :func:`uniform_values` turns a field's value into what Table I.3 maps it to;
  :func:`convert_uniform` fits it to the type the program declares.
- :func:`attribute_layout` places a geometry's vertex attributes at locations
  the engine's own arrays leave free.
- :func:`light_parameters`, :func:`legacy_light_parameters` and
  :func:`material_parameters` are the values of the light and material
  structures.
- :class:`LinkSchedule` says when a program is linked (Annex I.5).
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Optional

import numpy as np

from OpenGLContext.scenegraph import vertexsemantics

__all__ = [
    'STAGES', 'LANGUAGES', 'MAX_TEXTURES', 'LEGACY_OUTPUT', 'OBJECT_ID_OUTPUT',
    'OBJECT_ID_UNIFORM', 'Prepared', 'Uniform', 'LinkSchedule', 'stage_of',
    'stage_macro', 'speaks_glsl', 'inline_source', 'glsl_version',
    'prepare_source', 'packaged_stages', 'uniform_values', 'convert_uniform',
    'attribute_locations', 'attribute_layout', 'vertex_attribute', 'vertex_attributes',
    'per_vertex',
    'light_parameters', 'headlight_parameters', 'legacy_light_parameters',
    'material_parameters', 'legacy_material_parameters', 'X3D_INPUTS',
]

#: The stages a `ShaderPart` or `ShaderProgram` `type` names, in pipeline order.
STAGES = ('VERTEX', 'TESS_CONTROL', 'TESS_EVALUATION', 'GEOMETRY', 'FRAGMENT')

#: The `language` values the engine runs; '' is a ComposedShader that names none.
LANGUAGES = ('GLSL', '')

#: The texture units a shader's appearance textures are offered in:
#: `x3d_Texture2D[i]`, `x3d_TextureCube[i]`, `x3d_TextureMatrix[i]`.
MAX_TEXTURES = 4

#: What a translated fragment stage writes its colour to.
LEGACY_OUTPUT = 'oglc_FragColor'
#: The fragment output carrying the shape's object id, at location 1, where
#: the pass's picking attachment is.
OBJECT_ID_OUTPUT = 'oglc_FragObjectId'
#: The uniform the pass's object id for the shape is set in.
OBJECT_ID_UNIFORM = 'oglc_ObjectId'

#: The vertex inputs a shader reads the geometry's arrays through, and the
#: semantic each is fed from. `x3d_TexCoord` and `x3d_TexCoord0` are the same
#: first set.
X3D_INPUTS = (
    ('x3d_Vertex', 'POSITION'),
    ('x3d_Normal', 'NORMAL'),
    ('x3d_TexCoord', 'TEXCOORD_0'),
    ('x3d_TexCoord0', 'TEXCOORD_0'),
    ('x3d_TexCoord1', 'TEXCOORD_1'),
    ('x3d_Color', 'COLOR_0'),
    ('x3d_Tangent', 'TANGENT'),
)


def stage_of(type_value: Any) -> Optional[str]:
    """The stage a part's `type` names, upper-cased; None for one GL has no stage for"""
    found = str(type_value or '').strip().upper()
    return found if found in STAGES else None


def stage_macro(stage: str) -> str:
    """The macro defined while a stage's text is compiled: ``X3D_VERTEX_SHADER``, ..."""
    return 'X3D_%s_SHADER' % (stage,)


def speaks_glsl(language: Any) -> bool:
    """Whether a shader node's `language` is one the engine runs"""
    return str(language or '').strip().upper() in LANGUAGES


def inline_source(url: str) -> Optional[str]:
    """The text a url holds in itself; None for one naming a resource to fetch

    A ``data:`` URI (RFC 2397, base64 or percent-encoded) is decoded. A url
    that is shader text written into the url field, as documents for several
    browsers do, is that text: it has a line break, or both a brace and a
    semicolon, which no reference to a file has.
    """
    from OpenGLContext.loaders.resolver import decode_data_uri  # noqa: PLC0415 kept with its use
    text = str(url)
    if text.lstrip()[:5].lower() == 'data:':
        return decode_data_uri(text.strip()).decode('utf-8', 'replace')
    if '\n' in text or ('{' in text and ';' in text):
        return text
    return None


# -- source text ------------------------------------------------------------------

#: Versions written for an older compiler, translated before a 3.30 core one
#: sees them; None is a text with no `#version`, which GLSL reads as 1.10.
_LEGACY_VERSIONS = (None, 100, 110, 120, 130)
#: OpenGL ES versions and the desktop versions that compile the same text.
_ES_VERSIONS = {300: '330', 310: '430', 320: '450'}

_VERSION_LINE = re.compile(r'^\s*#\s*version\s+(\d+)\s*(\w+)?')
_DIRECTIVE = re.compile(r'^\s*#\s*(\w+)')
_MAIN = re.compile(r'\bvoid\s+main\s*\(')
_COMMENTS = re.compile(r'//[^\n]*|/\*.*?\*/', re.S)
_OUTPUT = re.compile(r'^\s*out\s+(?:(?:lowp|mediump|highp)\s+)?\w+\s+(\w+)', re.M)


def glsl_version(text: str) -> "tuple[Optional[int], str]":
    """The `#version` a text declares and its profile word; (None, '') for none"""
    for line in _COMMENTS.sub('', text).splitlines():
        if not line.strip():
            continue
        found = _VERSION_LINE.match(line)
        if found:
            return int(found.group(1)), (found.group(2) or '').lower()
        return None, ''
    return None, ''


def _header_end(lines: Sequence[str]) -> int:
    """How many of `lines` are the header: comments, `#version` and `#extension`"""
    end = 0
    in_comment = False
    for number, line in enumerate(lines):
        stripped = line.strip()
        if in_comment:
            if '*/' in stripped:
                in_comment = False
            continue
        if not stripped or stripped.startswith('//'):
            continue
        if stripped.startswith('/*'):
            in_comment = '*/' not in stripped[2:]
            continue
        directive = _DIRECTIVE.match(stripped)
        if directive and directive.group(1) in ('version', 'extension'):
            end = number + 1
            continue
        break
    return end


_STRUCTS = {
    'x3d_LightSourceParameters': (
        'struct x3d_LightSourceParameters {\n'
        '    int type; vec3 color; float intensity; float ambientIntensity;\n'
        '    vec3 attenuation; vec3 location; vec3 direction; float radius;\n'
        '    float beamWidth; float cutOffAngle; mat3 matrix;\n'
        '};\n'),
    'x3d_MaterialParameters': (
        'struct x3d_MaterialParameters {\n'
        '    float ambientIntensity; vec3 diffuseColor; vec3 specularColor;\n'
        '    vec3 emissiveColor; float shininess; float occlusionStrength;\n'
        '    float normalScale; float transparency;\n'
        '};\n'),
    'x3d_PhysicalMaterialParameters': (
        'struct x3d_PhysicalMaterialParameters {\n'
        '    vec3 baseColor; float metallic; float roughness; vec3 emissiveColor;\n'
        '    float occlusionStrength; float normalScale; float transparency;\n'
        '};\n'),
    'x3d_UnlitMaterialParameters': (
        'struct x3d_UnlitMaterialParameters {\n'
        '    vec3 emissiveColor; float normalScale; float transparency;\n'
        '};\n'),
}


def _definitions(stage: str, max_lights: int) -> str:
    return ''.join('#define %s %s\n' % pair for pair in (
        (stage_macro(stage), ''),
        ('x3d_MaxLights', max_lights),
        ('x3d_MaxTextures', MAX_TEXTURES),
        ('x3d_NoneLight', 0),
        ('x3d_DirectionalLight', 1),
        ('x3d_PointLight', 2),
        ('x3d_SpotLight', 3),
    ))


def _structs(text: str) -> str:
    """The X3D structures `text` names and does not define itself"""
    return ''.join(
        definition for name, definition in _STRUCTS.items()
        if re.search(r'\b%s\b' % name, text)
        and not re.search(r'\bstruct\s+%s\b' % name, text))


@dataclass
class Prepared:
    """One part's text, ready for a 3.30 core compiler"""

    #: The text to compile.
    text: str
    #: Whether the part was written for GLSL 1.10/1.20 (or ES 1.00) and translated.
    legacy: bool = False
    #: Identifiers renamed because GLSL 3.30 reserves them, by their own name:
    #: a field naming one sets the renamed uniform.
    renamed: "dict[str, str]" = field(default_factory=dict)
    #: Whether this part holds `main` and so writes the object id.
    has_main: bool = False
    #: The fragment outputs the part declares without a location.
    outputs: "list[str]" = field(default_factory=list)


def prepare_source(text: str, stage: str, max_lights: int = 8,
                   object_id: bool = True) -> Prepared:
    """`text`, one part of a shader's `stage`, as a 3.30 core compiler takes it

    After the part's `#version` and `#extension` lines come the X3D
    definitions -- ``X3D_<STAGE>_SHADER``, ``x3d_MaxLights``, the light type
    numbers -- and the structures (``x3d_LightSourceParameters``, ...) the
    part names without defining. A part with no `#version`, or a 1.x one, is
    translated (:func:`_translate_legacy`); an OpenGL ES 3 one is compiled as
    the desktop version of the same language. With `object_id`, the fragment
    part holding `main` also writes the pass's object id to location 1:
    its `main` is renamed and called from one that does.
    """
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    version, profile = glsl_version(text)
    end = _header_end(lines)
    header = [line for line in lines[:end] if not _VERSION_LINE.match(line)]
    body = ''.join(lines[end:])
    legacy = version in _LEGACY_VERSIONS
    renamed: "dict[str, str]" = {}
    declarations = ''
    if legacy:
        body, declarations, renamed = _translate_legacy(body, stage)
        version_line, compiled = '#version 330 core\n', 330
    elif profile == 'es' and version in _ES_VERSIONS:
        compiled = int(_ES_VERSIONS[version])
        version_line = '#version %d core\n' % (compiled,)
    else:
        compiled = int(version or 330)
        version_line = '#version %s%s\n' % (version, ' ' + profile if profile else '')
    has_main = bool(_MAIN.search(body))
    outputs: "list[str]" = []
    trailer = ''
    if stage == 'FRAGMENT' and has_main and object_id:
        body = _MAIN.sub('void oglc_x3d_main(', body)
        outputs = [name for name in _OUTPUT.findall(_COMMENTS.sub('', body))]
        if legacy and LEGACY_OUTPUT in declarations:
            outputs.append(LEGACY_OUTPUT)
        declarations += ('uniform uint %s;\nlayout(location = 1) out vec4 %s;\n'
                         % (OBJECT_ID_UNIFORM, OBJECT_ID_OUTPUT))
        trailer = (
            '\nvoid main() {\n'
            '    oglc_x3d_main();\n'
            '    %(out)s = vec4(float(%(id)s & 0xFFu), float((%(id)s >> 8u) & 0xFFu),\n'
            '        float((%(id)s >> 16u) & 0xFFu), float((%(id)s >> 24u) & 0xFFu)) / 255.0;\n'
            '}\n' % {'out': OBJECT_ID_OUTPUT, 'id': OBJECT_ID_UNIFORM})
    # The first line of the body keeps its own number in the compiler's log;
    # before 3.30, `#line n` numbers the line after it n + 1.
    first = end + 1
    line_directive = '#line %d\n' % (first if compiled >= 330 else first - 1)
    prelude = (_definitions(stage, max_lights) + _structs(declarations + body)
               + declarations)
    return Prepared(
        text=version_line + ''.join(header) + prelude + line_directive + body + trailer,
        legacy=legacy, renamed=renamed, has_main=has_main, outputs=outputs)


def packaged_stages(text: str) -> "list[str]":
    """The stages a packaged GLSL file holds: those whose macro it tests

    A `PackagedShader` of GLSL is one text compiled once for each stage it
    names, ``X3D_VERTEX_SHADER`` defined for the vertex stage and so on
    (:func:`stage_macro`). A text naming no stage holds a vertex and a
    fragment stage, told apart by the same macros.
    """
    found = [stage for stage in STAGES if stage_macro(stage) in text]
    return found or ['VERTEX', 'FRAGMENT']


# -- GLSL 1.x translation ---------------------------------------------------------

#: Identifiers GLSL 1.10 lets a shader use that 3.30 keeps for itself.
_RESERVED = ('texture', 'flat', 'smooth', 'noperspective', 'layout', 'centroid',
             'uint', 'sample', 'patch', 'subroutine')

_FUNCTIONS = (
    ('texture2DProjLod', 'textureProjLod'), ('texture2DProj', 'textureProj'),
    ('texture2DLod', 'textureLod'), ('texture2D', 'texture'),
    ('texture1DProj', 'textureProj'), ('texture1D', 'texture'),
    ('texture3DProj', 'textureProj'), ('texture3DLod', 'textureLod'),
    ('texture3D', 'texture'), ('textureCubeLod', 'textureLod'),
    ('textureCube', 'texture'), ('shadow2DProj', 'oglc_shadow2DProj'),
    ('shadow2D', 'oglc_shadow2D'),
)

_MATRICES = ('ModelView', 'Projection', 'ModelViewProjection')

#: Built-in state both stages read, as the uniforms or expressions that hold it.
_SHARED = [
    ('gl_%sMatrix%s' % (matrix, suffix), expression % ('x3d_%sMatrix' % matrix,))
    for matrix in _MATRICES
    for suffix, expression in (
        ('InverseTranspose', '(transpose(inverse(%s)))'),
        ('Inverse', '(inverse(%s))'),
        ('Transpose', '(transpose(%s))'),
        ('', '%s'),
    )
] + [
    ('gl_NormalMatrix', 'x3d_NormalMatrix'),
    ('gl_TextureMatrix', 'x3d_TextureMatrix'),
    ('gl_LightSource', 'oglc_LightSource'),
    ('gl_FrontMaterial', 'oglc_FrontMaterial'),
    ('gl_BackMaterial', 'oglc_FrontMaterial'),
    ('gl_LightModel', 'oglc_LightModel'),
    ('gl_FrontLightModelProduct', 'oglc_FrontLightModelProduct'),
    ('gl_BackLightModelProduct', 'oglc_FrontLightModelProduct'),
    ('gl_FrontLightProduct', 'oglc_FrontLightProduct'),
    ('gl_BackLightProduct', 'oglc_FrontLightProduct'),
    ('gl_MaxLights', 'x3d_MaxLights'),
    ('gl_MaxTextureCoords', '8'),
    ('gl_MaxTextureUnits', 'x3d_MaxTextures'),
]

_VERTEX = [
    ('gl_Vertex', 'x3d_Vertex'),
    ('gl_Normal', 'x3d_Normal'),
    ('gl_Color', 'x3d_Color'),
    ('gl_FogCoord', 'x3d_FogDepth'),
] + [('gl_MultiTexCoord%d' % n, 'x3d_TexCoord%d' % n) for n in range(8)] + [
    ('gl_FrontColor', 'oglc_FrontColor'),
    ('gl_BackColor', 'oglc_BackColor'),
    ('gl_FrontSecondaryColor', 'oglc_FrontSecondaryColor'),
    ('gl_BackSecondaryColor', 'oglc_BackSecondaryColor'),
    ('gl_TexCoord', 'oglc_TexCoord'),
    ('gl_FogFragCoord', 'oglc_FogFragCoord'),
    ('gl_ClipVertex', 'oglc_ClipVertex'),
]

_FRAGMENT = [
    ('gl_Color', 'oglc_FrontColor'),
    ('gl_SecondaryColor', 'oglc_FrontSecondaryColor'),
    ('gl_TexCoord', 'oglc_TexCoord'),
    ('gl_FogFragCoord', 'oglc_FogFragCoord'),
    ('gl_FragColor', LEGACY_OUTPUT),
    ('gl_FragData', 'oglc_FragData'),
]

_LEGACY_STRUCTS = {
    'oglc_LightSourceParameters': (
        'struct oglc_LightSourceParameters {\n'
        '    vec4 ambient; vec4 diffuse; vec4 specular; vec4 position;\n'
        '    vec4 halfVector; vec3 spotDirection; float spotExponent;\n'
        '    float spotCutoff; float spotCosCutoff; float constantAttenuation;\n'
        '    float linearAttenuation; float quadraticAttenuation;\n'
        '};\n'),
    'oglc_MaterialParameters': (
        'struct oglc_MaterialParameters {\n'
        '    vec4 emission; vec4 ambient; vec4 diffuse; vec4 specular; float shininess;\n'
        '};\n'),
    'oglc_LightModelParameters': 'struct oglc_LightModelParameters { vec4 ambient; };\n',
    'oglc_LightModelProducts': 'struct oglc_LightModelProducts { vec4 sceneColor; };\n',
    'oglc_LightProducts': (
        'struct oglc_LightProducts { vec4 ambient; vec4 diffuse; vec4 specular; };\n'),
}

#: How each name the translation introduces is declared, by stage: 'v' vertex,
#: 'f' fragment, '' both. The struct a declaration needs is put before it.
_DECLARATIONS = (
    ('x3d_Vertex', 'v', 'in vec4 x3d_Vertex;'),
    ('x3d_Normal', 'v', 'in vec3 x3d_Normal;'),
    ('x3d_Color', 'v', 'in vec4 x3d_Color;'),
    ('x3d_FogDepth', 'v', 'in float x3d_FogDepth;'),
) + tuple(
    ('x3d_TexCoord%d' % n, 'v', 'in vec4 x3d_TexCoord%d;' % n) for n in range(8)
) + (
    ('x3d_ModelViewMatrix', '', 'uniform mat4 x3d_ModelViewMatrix;'),
    ('x3d_ProjectionMatrix', '', 'uniform mat4 x3d_ProjectionMatrix;'),
    ('x3d_ModelViewProjectionMatrix', '', 'uniform mat4 x3d_ModelViewProjectionMatrix;'),
    ('x3d_NormalMatrix', '', 'uniform mat3 x3d_NormalMatrix;'),
    ('x3d_TextureMatrix', '', 'uniform mat4 x3d_TextureMatrix[x3d_MaxTextures];'),
    ('oglc_LightSource', '',
     'uniform oglc_LightSourceParameters oglc_LightSource[x3d_MaxLights];'),
    ('oglc_FrontMaterial', '', 'uniform oglc_MaterialParameters oglc_FrontMaterial;'),
    ('oglc_LightModel', '', 'uniform oglc_LightModelParameters oglc_LightModel;'),
    ('oglc_FrontLightModelProduct', '',
     'uniform oglc_LightModelProducts oglc_FrontLightModelProduct;'),
    ('oglc_FrontLightProduct', '',
     'uniform oglc_LightProducts oglc_FrontLightProduct[x3d_MaxLights];'),
    ('oglc_FrontColor', 'v', 'out vec4 oglc_FrontColor;'),
    ('oglc_BackColor', 'v', 'out vec4 oglc_BackColor;'),
    ('oglc_FrontSecondaryColor', 'v', 'out vec4 oglc_FrontSecondaryColor;'),
    ('oglc_BackSecondaryColor', 'v', 'out vec4 oglc_BackSecondaryColor;'),
    ('oglc_TexCoord', 'v', 'out vec4 oglc_TexCoord[8];'),
    ('oglc_FogFragCoord', 'v', 'out float oglc_FogFragCoord;'),
    ('oglc_ClipVertex', 'v', 'vec4 oglc_ClipVertex;'),
    ('oglc_FrontColor', 'f', 'in vec4 oglc_FrontColor;'),
    ('oglc_FrontSecondaryColor', 'f', 'in vec4 oglc_FrontSecondaryColor;'),
    ('oglc_TexCoord', 'f', 'in vec4 oglc_TexCoord[8];'),
    ('oglc_FogFragCoord', 'f', 'in float oglc_FogFragCoord;'),
    (LEGACY_OUTPUT, 'f', 'layout(location = 0) out vec4 %s;' % LEGACY_OUTPUT),
    ('oglc_FragData', 'f', 'layout(location = 0) out vec4 oglc_FragData[1];'),
    # 1.x's shadow lookups answer a vec4, 3.30's a float.
    ('oglc_shadow2D', '',
     'vec4 oglc_shadow2D(sampler2DShadow s, vec3 c) { return vec4(texture(s, c)); }'),
    ('oglc_shadow2DProj', '',
     'vec4 oglc_shadow2DProj(sampler2DShadow s, vec4 c) { return vec4(textureProj(s, c)); }'),
)


def _replace(text: str, pairs: Iterable["tuple[str, str]"]) -> str:
    for name, replacement in pairs:
        text = re.sub(r'\b%s\b' % name, lambda _match, r=replacement: r, text)
    return text


def _declared(name: str, text: str) -> bool:
    return bool(re.search(r'\b(?:uniform|in|out|attribute|varying)\b[^;{}]*\b%s\b' % name,
                          text))


def _translate_legacy(body: str, stage: str) -> "tuple[str, str, dict[str, str]]":
    """A GLSL 1.10/1.20 part's body, its added declarations, and what it renamed

    `attribute` and `varying` become `in` and `out`; the texture functions
    their 3.30 names; ``ftransform()`` the projection of `x3d_Vertex`; the
    built-in matrices, vertex arrays and light and material state the X3D
    uniforms and inputs, or the engine's ``oglc_`` ones where X3D names
    none; the varyings the built-ins passed (``gl_TexCoord[]``,
    ``gl_FrontColor``/``gl_Color``) outputs and inputs of the engine's
    names; ``gl_FragColor`` and ``gl_FragData[0]`` the output at location 0.
    """
    original = _COMMENTS.sub('', body)
    renamed = {name: 'oglc_%s' % name for name in _RESERVED
               if re.search(r'\b%s\b' % name, original)}
    code = _replace(body, renamed.items())
    if stage == 'VERTEX':
        code = _replace(code, [('attribute', 'in'), ('varying', 'out')])
    else:
        code = _replace(code, [('varying', 'in')])
    code = _replace(code, _FUNCTIONS)
    code = re.sub(r'\bftransform\s*\(\s*\)',
                  '(x3d_ProjectionMatrix * (x3d_ModelViewMatrix * x3d_Vertex))', code)
    code = _replace(code, _SHARED)
    code = _replace(code, _VERTEX if stage == 'VERTEX' else _FRAGMENT)
    letter = 'v' if stage == 'VERTEX' else 'f'
    plain = _COMMENTS.sub('', code)
    wanted = [(name, declaration) for name, stages, declaration in _DECLARATIONS
              if stages in ('', letter) and re.search(r'\b%s\b' % name, plain)
              and not _declared(name, original)]
    lines: "list[str]" = []
    for struct, definition in _LEGACY_STRUCTS.items():
        if any(struct in declaration for _name, declaration in wanted):
            lines.append(definition)
    lines.extend(declaration + '\n' for _name, declaration in wanted)
    return code, ''.join(lines), renamed


# -- uniform values ---------------------------------------------------------------

class Uniform(NamedTuple):
    """A value as Table I.3 maps it: numbers, and how many make one element"""

    #: Flat values, element after element.
    values: np.ndarray
    #: Values per element: 1, 2, 3, 4, 9 or 16.
    width: int
    #: Whether the values are integers (SFBool, SFInt32, SFImage).
    integer: bool


_WIDTHS = {
    'Bool': (1, True), 'Int32': (1, True), 'Float': (1, False), 'Double': (1, False),
    'Time': (1, False), 'Vec2f': (2, False), 'Vec2d': (2, False),
    'Vec3f': (3, False), 'Vec3d': (3, False), 'Color': (3, False),
    'Vec4f': (4, False), 'Vec4d': (4, False), 'ColorRGBA': (4, False),
    'Rotation': (4, False), 'Matrix3f': (9, False), 'Matrix3d': (9, False),
    'Matrix4f': (16, False), 'Matrix4d': (16, False), 'Image': (1, True),
}


def uniform_values(type_name: str, value: Any) -> Optional[Uniform]:
    """A field's value as Table I.3 maps it to GLSL; None for a type it does not map

    SFBool and SFInt32 are integers, the floating and double types floats;
    vectors, colours and rotations one element of 2, 3 or 4; matrices 9 or
    16 values in X3D's (column-major) order; an SFImage its integers, width
    and height and components first. MF types are arrays of the same.
    Strings and nodes are not values (a texture node is a sampler, set
    apart).
    """
    kind = str(type_name)[2:]
    found = _WIDTHS.get(kind)
    if found is None or value is None:
        return None
    width, integer = found
    if kind == 'Image':
        values = _image_values(value, multiple=str(type_name).startswith('MF'))
    else:
        values = np.asarray(value, dtype=np.int64 if integer else np.float64).ravel()
    if not integer and not np.isfinite(values).all():
        values = np.nan_to_num(values, nan=0.0, posinf=3.4e38, neginf=-3.4e38)
    return Uniform(values.astype(np.int32 if integer else np.float32), width, integer)


def _image_values(value: Any, multiple: bool) -> np.ndarray:
    images = value if multiple else [value]
    flat: "list[int]" = []
    for image in images:
        flat.extend(int(number) for number in np.asarray(image).ravel())
    return np.asarray(flat, dtype=np.int64)


def convert_uniform(found: Uniform, components: int, integer: bool,
                    count: int) -> Optional[np.ndarray]:
    """`found` as `count` elements of `components` values the program declares

    `integer` is whether the declaration is an int, uint or bool type. The
    values are cut or padded with zeros to whole elements and to at most
    `count` of them; None where they make no element.
    """
    values = found.values.astype(np.int32 if integer else np.float32)
    elements = min(len(values) // components, int(count))
    if elements < 1:
        return None
    return np.ascontiguousarray(values[:elements * components])


# -- vertex attributes ------------------------------------------------------------

def attribute_locations(maximum: int) -> "list[int]":
    """The attribute locations a shape drawn by its own shader may use, best first

    Those from :data:`~OpenGLContext.scenegraph.vertexsemantics.FIRST_FREE_LOCATION`
    up to the driver's `maximum`, then the ones the engine's programs read
    per instance (5 to 10, and 14): a shape drawn by its own shader is never
    drawn instanced, and the engine's programs read those only while drawing
    instances.
    """
    found = list(range(vertexsemantics.FIRST_FREE_LOCATION, int(maximum)))
    found.extend(range(vertexsemantics.INSTANCE_MODELVIEW, vertexsemantics.INSTANCE_MATERIAL + 1))
    found.append(vertexsemantics.INSTANCE_JOINT_BASE)
    return [location for location in found if location < int(maximum)]


def attribute_layout(widths: Sequence["tuple[str, int]"],
                     maximum: int) -> "tuple[tuple[str, int], ...]":
    """Where each named attribute is read, as (name, first location)

    `widths` are (name, locations it takes) in the geometry's `attrib`
    order: one for a vector, three for a 3x3 matrix, four for a 4x4. Each is
    put at the first run of free locations (:func:`attribute_locations`) long
    enough for it; one that does not fit is left out, as is a second of the
    same name.
    """
    free = attribute_locations(maximum)
    layout: "list[tuple[str, int]]" = []
    names: "set[str]" = set()
    for name, width in widths:
        if not name or name in names or width < 1:
            continue
        for start in free:
            run = list(range(start, start + width))
            if all(location in free for location in run):
                layout.append((name, start))
                names.add(name)
                free = [location for location in free if location not in run]
                break
    return tuple(layout)


def vertex_attribute(node: Any) -> "Optional[tuple[str, np.ndarray, int]]":
    """A vertex attribute node as (name, values one row per vertex, locations)

    `FloatVertexAttribute` has `numComponents` values a vertex and takes one
    location; `Matrix3VertexAttribute` nine (a column a location) and
    `Matrix4VertexAttribute` sixteen. None for a node with no name or no
    values.
    """
    name = str(getattr(node, 'name', '') or '')
    values = np.asarray(getattr(node, 'value', ()), dtype=np.float32).ravel()
    if not name or not len(values):
        return None
    if hasattr(node, 'numComponents'):
        width = min(max(int(node.numComponents), 1), 4)
        locations = 1
    else:
        width = 9 if 'Matrix3' in type(node).__name__ else 16
        locations = 3 if width == 9 else 4
    rows = len(values) // width
    if rows < 1:
        return None
    return name, values[:rows * width].reshape(rows, width), locations


def vertex_attributes(nodes: Any) -> "list[tuple[str, np.ndarray, int]]":
    """Each of a geometry's `attrib` nodes as :func:`vertex_attribute` describes it, in order"""
    found = (vertex_attribute(entry) for entry in (nodes or ()) if entry)
    return [entry for entry in found if entry is not None]


def per_vertex(attributes: Sequence["tuple[str, np.ndarray, int]"], index: np.ndarray,
               ) -> "tuple[list[tuple[str, np.ndarray, int]], list[str]]":
    """The attributes taken at `index`, one row per drawn vertex, and the names left out

    `index` gives the coordinate each drawn vertex is: the attributes have one
    row per coordinate. One with fewer rows than `index` reaches is left out.
    """
    index = np.asarray(index, dtype=np.int64)
    found: "list[tuple[str, np.ndarray, int]]" = []
    short: "list[str]" = []
    reach = int(index.max()) + 1 if len(index) else 0
    for name, values, locations in attributes:
        if len(values) < reach:
            short.append(name)
            continue
        found.append((name, np.ascontiguousarray(values[index], dtype=np.float32), locations))
    return found, short


# -- lights and materials ---------------------------------------------------------

def _row(vector: Sequence[float], matrix: np.ndarray) -> np.ndarray:
    return np.asarray(vector, dtype=np.float64) @ matrix


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    return vector / length if length > 0 else vector


def _kind(light: Any) -> int:
    if hasattr(light, 'cutOffAngle'):
        return 3
    if hasattr(light, 'location'):
        return 2
    return 1


def light_parameters(light: Any, matrix: np.ndarray) -> "dict[str, Any]":
    """`x3d_LightSourceParameters` for `light` under its eye-space `matrix`

    `matrix` is the light's modelview, row-vector convention (``p @ M``).
    `location` and `direction` are in eye space, `radius` -1 for a
    directional light, angles in radians; `matrix` turns an eye-space vector
    into the light's own space, where its `radius` is measured.
    """
    matrix = np.asarray(matrix, dtype=np.float64).reshape(4, 4)
    kind = _kind(light)
    rotation = matrix[:3, :3]
    try:
        local = np.linalg.inv(rotation)
    except np.linalg.LinAlgError:
        local = np.eye(3)
    location = _row(tuple(getattr(light, 'location', (0.0, 0.0, 0.0))) + (1.0,), matrix)[:3]
    direction = _unit(_row(getattr(light, 'direction', (0.0, 0.0, -1.0)), rotation))
    return {
        'type': kind,
        'color': np.asarray(light.color, dtype=np.float32),
        'intensity': float(light.intensity),
        'ambientIntensity': float(getattr(light, 'ambientIntensity', 0.0)),
        'attenuation': np.asarray(getattr(light, 'attenuation', (1.0, 0.0, 0.0)),
                                  dtype=np.float32),
        'location': location.astype(np.float32),
        'direction': direction.astype(np.float32),
        'radius': float(getattr(light, 'radius', -1.0)) if kind != 1 else -1.0,
        'beamWidth': float(getattr(light, 'beamWidth', 0.0)),
        'cutOffAngle': float(getattr(light, 'cutOffAngle', 0.0)),
        'matrix': local.astype(np.float32),
    }


def headlight_parameters() -> "dict[str, Any]":
    """`x3d_LightSourceParameters` for the headlight: white, along the view"""
    return {
        'type': 1, 'color': np.ones(3, np.float32), 'intensity': 1.0,
        'ambientIntensity': 0.0, 'attenuation': np.array((1.0, 0.0, 0.0), np.float32),
        'location': np.zeros(3, np.float32), 'direction': np.array((0.0, 0.0, -1.0), np.float32),
        'radius': -1.0, 'beamWidth': 0.0, 'cutOffAngle': 0.0,
        'matrix': np.eye(3, dtype=np.float32),
    }


def legacy_light_parameters(light: "dict[str, Any]") -> "dict[str, Any]":
    """GLSL 1.x's `gl_LightSource[i]` for the light :func:`light_parameters` describes

    A directional light's `position` is the direction towards it with w 0.
    Colours are the light's colour times its intensity (ambient times its
    ambient intensity); a light that is not a spot has a `spotCutoff` of 180.
    """
    color = np.asarray(light['color'], np.float32)
    diffuse = np.append(color * float(light['intensity']), 1.0).astype(np.float32)
    ambient = np.append(color * float(light['ambientIntensity']), 1.0).astype(np.float32)
    if light['type'] == 1:
        towards = -np.asarray(light['direction'], np.float64)
        position = np.append(towards, 0.0)
    else:
        towards = -np.asarray(light['location'], np.float64)
        position = np.append(light['location'], 1.0)
    half = _unit(_unit(-towards if light['type'] != 1 else towards)
                 + np.array((0.0, 0.0, 1.0)))
    spot = light['type'] == 3
    cutoff = math.degrees(float(light['cutOffAngle'])) if spot else 180.0
    constant, linear, quadratic = (float(v) for v in light['attenuation'])
    return {
        'ambient': ambient, 'diffuse': diffuse, 'specular': diffuse.copy(),
        'position': position.astype(np.float32),
        'halfVector': np.append(half, 0.0).astype(np.float32),
        'spotDirection': np.asarray(light['direction'], np.float32),
        'spotExponent': 0.0, 'spotCutoff': cutoff,
        'spotCosCutoff': math.cos(math.radians(cutoff)) if spot else -1.0,
        'constantAttenuation': constant, 'linearAttenuation': linear,
        'quadraticAttenuation': quadratic,
    }


#: X3D's Material when an appearance has none: drawn unlit, in white.
_UNLIT = {
    'ambientIntensity': 0.0, 'diffuseColor': (0.0, 0.0, 0.0),
    'specularColor': (0.0, 0.0, 0.0), 'emissiveColor': (1.0, 1.0, 1.0),
    'shininess': 0.0, 'occlusionStrength': 1.0, 'normalScale': 1.0,
    'transparency': 0.0, 'baseColor': (0.0, 0.0, 0.0), 'metallic': 0.0,
    'roughness': 1.0,
}


def material_parameters(material: Any) -> "dict[str, Any]":
    """The members of the material structures for `material`, by name

    Every member of `x3d_MaterialParameters`, `x3d_PhysicalMaterialParameters`
    and `x3d_UnlitMaterialParameters` the node has a field for; the rest at
    the values of an appearance with no material, which X3D draws unlit and
    white. A shader declares the structure that matches its material, and the
    members it does not declare are not set.
    """
    found = dict(_UNLIT)
    if material:
        for name in found:
            value = getattr(material, name, None)
            if value is not None:
                found[name] = value
        if not hasattr(material, 'emissiveColor'):
            found['emissiveColor'] = (0.0, 0.0, 0.0)
    return {name: (np.asarray(value, np.float32) if isinstance(value, (tuple, list, np.ndarray))
                   else float(value)) for name, value in found.items()}


def legacy_material_parameters(material: "dict[str, Any]") -> "dict[str, Any]":
    """GLSL 1.x's `gl_FrontMaterial` for the material :func:`material_parameters` describes"""
    diffuse = np.asarray(material['diffuseColor'], np.float32)
    alpha = 1.0 - float(material['transparency'])
    return {
        'emission': np.append(material['emissiveColor'], 1.0).astype(np.float32),
        'ambient': np.append(diffuse * float(material['ambientIntensity']), 1.0).astype(np.float32),
        'diffuse': np.append(diffuse, alpha).astype(np.float32),
        'specular': np.append(material['specularColor'], 1.0).astype(np.float32),
        'shininess': float(material['shininess']) * 128.0,
    }


# -- linking ----------------------------------------------------------------------

class LinkSchedule:
    """When a shader's program is linked, as Annex I.5 has it

    A program is linked once every part's source is to hand, and again for
    each `activate` TRUE. A part whose source changes later is compiled
    (and a failure reported) but the running program is kept until the next
    `activate`; until a program has linked, a change to the sources is tried
    at once.
    """

    def __init__(self) -> None:
        #: The sources of the last link tried, or None.
        self.tried: Optional[Any] = None
        #: Whether a program from an earlier link is running.
        self.running = False
        #: Whether an `activate` has asked for a link since the last one.
        self.requested = False

    def activate(self) -> None:
        """An `activate` TRUE: link again at the next chance"""
        self.requested = True

    def due(self, sources: Any) -> bool:
        """Whether to link `sources` now; None sources are not all to hand"""
        if sources is None:
            return False
        if self.requested:
            return True
        return not self.running and sources != self.tried

    def linked(self, sources: Any, ok: bool) -> None:
        """Record a link of `sources`, and whether it made a program"""
        self.tried = sources
        self.requested = False
        if ok:
            self.running = True
