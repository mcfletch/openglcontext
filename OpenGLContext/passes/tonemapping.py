"""What the PBR pass writes for a colour: tone curve, exposure and colour space

The arithmetic and the choice need no GL; :func:`upload_display` hands the
choice to a bound program.

Three settings decide it, each a :class:`~OpenGLContext.contextdefinition.ContextDefinition`
field with an environment variable as its default:

``toneMapping`` (``OPENGLCONTEXT_TONE_MAPPING``)
    The curve that takes a lit colour to the range [0, 1]: one of
    :data:`OPERATORS`, or ``auto``.  ``auto`` draws a scene read from a VRML97
    or X3D document with no curve, as X_ITE draws one by default, and every
    other scene with the ACES fit of Krzysztof Narkowicz.
``exposure`` (``OPENGLCONTEXT_EXPOSURE``)
    A multiplier on the colour before the curve, 1.0 by default.  It
    multiplies the exposure a glTF scene's light meter sets.
``colorSpace`` (``OPENGLCONTEXT_COLOR_SPACE``)
    Which materials are lit in linear light, as X_ITE's ``ColorSpace``
    option says: one of :data:`COLOR_SPACES`, or ``auto``, which is
    ``linear_when_physical_material``.  A material lit in linear light has
    its textures decoded from sRGB and its result encoded to sRGB; one lit
    in sRGB uses its texel values as they are and writes its result as it is.

The curves are X_ITE 16.4.3's (``ToneMapping2.glsl``, MIT licence, copyright
Holger Seelig and contributors), which are the published fits: Narkowicz's
ACES fit, Stephen Hill's ACES fit with its two matrices, the same with
exposure divided by 0.6, and the Khronos PBR Neutral curve.  The shaders'
copy is ``shaders/_tonemap_inc.glsl``; :func:`tone_map` and :func:`untone`
here are the same arithmetic in numpy, for the tests and for a caller
working out a colour on the CPU.

In a document scene the curve and the exposure also apply to the colours X3D
gives as they are displayed (a ``Material`` lit by X3D's Phong equation, an
unlit appearance, a ``Background``), as X_ITE applies them.  In any other
scene those colours are written as they are.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    'OPERATORS', 'TONE_MAPPING_CHOICES', 'COLOR_SPACES', 'COLOR_SPACE_CHOICES',
    'DOCUMENT_OPERATOR', 'ENGINE_OPERATOR', 'Display', 'display', 'operator_code',
    'color_space_code', 'resolve_operator', 'resolve_color_space', 'tone_map',
    'untone', 'default_tone_mapping', 'default_exposure', 'default_color_space',
    'ENGINE', 'display_uniforms', 'frame_display', 'upload_display',
]

#: The tone curves, in the order of their codes in the shaders.
OPERATORS: tuple[str, ...] = (
    'none', 'aces_narkowicz', 'aces_hill', 'aces_hill_exposure_boost', 'khr_pbr_neutral',
)
#: What ``ContextDefinition.toneMapping`` accepts.
TONE_MAPPING_CHOICES: tuple[str, ...] = ('auto',) + OPERATORS
#: What a settings screen shows for each of those.
TONE_MAPPING_LABELS: tuple[str, ...] = (
    'By the scene', 'None', 'ACES (Narkowicz)', 'ACES (Hill)',
    'ACES (Hill, exposure boost)', 'Khronos PBR Neutral',
)
#: The colour spaces materials are lit in, in the order of their codes in the shaders.
COLOR_SPACES: tuple[str, ...] = ('srgb', 'linear_when_physical_material', 'linear')
#: What ``ContextDefinition.colorSpace`` accepts.
COLOR_SPACE_CHOICES: tuple[str, ...] = ('auto',) + COLOR_SPACES
#: What a settings screen shows for each of those.
COLOR_SPACE_LABELS: tuple[str, ...] = (
    'By the scene', 'sRGB', 'Linear for physical materials', 'Linear',
)

#: The curve ``auto`` draws a VRML97 or X3D document with: X_ITE's default.
DOCUMENT_OPERATOR = 'none'
#: The curve ``auto`` draws every other scene with.
ENGINE_OPERATOR = 'aces_narkowicz'
#: The colour space ``auto`` lights every scene in.
AUTO_COLOR_SPACE = 'linear_when_physical_material'

#: Hill's fit works in the ACES colour space: sRGB primaries in, by this
#: matrix (rows are output channels), and back out by the next.
ACES_INPUT = np.array([
    [0.59719, 0.35458, 0.04823],
    [0.07600, 0.90834, 0.01566],
    [0.02840, 0.13383, 0.83777],
])
ACES_OUTPUT = np.array([
    [1.60475, -0.53108, -0.07367],
    [-0.10208, 1.10813, -0.00605],
    [-0.00327, -0.07276, 1.07602],
])
#: What ``aces_hill_exposure_boost`` divides the colour by before Hill's fit.
EXPOSURE_BOOST = 0.6
#: The Khronos PBR Neutral curve's constants: compression starts at 0.76 and
#: desaturates highlights by 0.15.
NEUTRAL_START = 0.8 - 0.04
NEUTRAL_DESATURATION = 0.15


def default_tone_mapping() -> str:
    """``OPENGLCONTEXT_TONE_MAPPING``, one of :data:`TONE_MAPPING_CHOICES`, else ``auto``"""
    from OpenGLContext import renderoptions
    return renderoptions.env_choice_once('OPENGLCONTEXT_TONE_MAPPING',
                                         TONE_MAPPING_CHOICES, {}, 'auto')


def default_exposure() -> float:
    """``OPENGLCONTEXT_EXPOSURE``, else 1.0"""
    from OpenGLContext import renderoptions
    return renderoptions.env_number_once('OPENGLCONTEXT_EXPOSURE', 1.0)


def default_color_space() -> str:
    """``OPENGLCONTEXT_COLOR_SPACE``, one of :data:`COLOR_SPACE_CHOICES`, else ``auto``"""
    from OpenGLContext import renderoptions
    return renderoptions.env_choice_once('OPENGLCONTEXT_COLOR_SPACE',
                                         COLOR_SPACE_CHOICES, {}, 'auto')


def resolve_operator(chosen: str, document: bool) -> str:
    """The curve ``chosen`` draws with: itself, or for ``auto`` the scene's"""
    chosen = str(chosen).lower()
    if chosen == 'auto':
        return DOCUMENT_OPERATOR if document else ENGINE_OPERATOR
    if chosen not in OPERATORS:
        raise ValueError('toneMapping is one of %s, not %r' % (TONE_MAPPING_CHOICES, chosen))
    return chosen


def resolve_color_space(chosen: str) -> str:
    """The colour space ``chosen`` lights with: itself, or for ``auto`` :data:`AUTO_COLOR_SPACE`"""
    chosen = str(chosen).lower()
    if chosen == 'auto':
        return AUTO_COLOR_SPACE
    if chosen not in COLOR_SPACES:
        raise ValueError('colorSpace is one of %s, not %r' % (COLOR_SPACE_CHOICES, chosen))
    return chosen


def operator_code(operator: str) -> int:
    """The shaders' ``toneMapping`` value for ``operator``"""
    return OPERATORS.index(operator)


def color_space_code(space: str) -> int:
    """The shaders' ``colorSpace`` value for ``space``"""
    return COLOR_SPACES.index(space)


@dataclass(frozen=True)
class Display:
    """How a frame turns a lit colour into what is written.

    ``operator`` is one of :data:`OPERATORS`, ``exposure`` the multiplier
    before it, ``color_space`` one of :data:`COLOR_SPACES`, and ``document``
    whether the curve and the exposure also apply to colours X3D gives as
    displayed.
    """

    operator: str = ENGINE_OPERATOR
    exposure: float = 1.0
    color_space: str = AUTO_COLOR_SPACE
    document: bool = False


#: The display of a frame with no definition or scene to ask: the engine's
#: curve, exposure 1, colours X3D gives as displayed written as they are.
ENGINE = Display()


def display_uniforms(shown: Display) -> dict[str, float]:
    """The uniforms a program reading ``_tonemap_inc.glsl`` is given for ``shown``

    ``toneMapping`` and ``colorSpace`` are the codes, ``exposure`` the
    multiplier and ``documentDisplay`` 1 for a document.
    """
    return {'toneMapping': operator_code(shown.operator),
            'colorSpace': color_space_code(shown.color_space),
            'exposure': float(shown.exposure),
            'documentDisplay': int(shown.document)}


def upload_display(program: int, shown: Display) -> None:
    """Set :func:`display_uniforms` on ``program``, the program in use

    A uniform the program does not declare is passed over.
    """
    from OpenGL import GL  # noqa: PLC0415 the rest of the module needs no GL
    for name, value in display_uniforms(shown).items():
        location = GL.glGetUniformLocation(program, name)
        if location == -1:
            continue
        if isinstance(value, float):
            GL.glUniform1f(location, value)
        else:
            GL.glUniform1i(location, value)


def frame_display(mode: Any) -> Display:
    """The :class:`Display` of the frame ``mode`` is drawing, or :data:`ENGINE`

    ``mode`` is the render pass; one with no ``frameDisplay`` answers :data:`ENGINE`.
    """
    found = getattr(mode, 'frameDisplay', None)
    return found() if callable(found) else ENGINE


def display(source: Any, scene: Any = None) -> Display:
    """The :class:`Display` for a frame of ``scene`` drawn through ``source``.

    ``source`` is a render pass, a context or a definition
    (:func:`OpenGLContext.renderoptions.definition`); ``scene`` defaults to
    the source's own ``scene``.
    """
    from OpenGLContext import renderoptions
    from OpenGLContext import lighting
    if scene is None:
        scene = getattr(source, 'scene', None)
    document = lighting.scene_x3d_lit(scene, 'auto')
    chosen = renderoptions.choice(source, 'toneMapping', default_tone_mapping())
    exposure = renderoptions.number(source, 'exposure', default_exposure())
    space = renderoptions.choice(source, 'colorSpace', default_color_space())
    return Display(operator=resolve_operator(chosen, document),
                   exposure=max(float(exposure), 0.0),
                   color_space=resolve_color_space(space),
                   document=document)


def _narkowicz(x: Any) -> Any:
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)


def _hill_fit(v: Any) -> Any:
    return (v * (v + 0.0245786) - 0.000090537) / (v * (0.983729 * v + 0.4329510) + 0.238081)


def _hill_fit_inverse(y: Any) -> Any:
    # (1 - 0.983729 y) v^2 + (0.0245786 - 0.4329510 y) v - (0.000090537 + 0.238081 y) = 0
    qa = 1.0 - 0.983729 * y
    qb = 0.0245786 - 0.4329510 * y
    qc = -(0.000090537 + 0.238081 * y)
    return (-qb + np.sqrt(np.maximum(qb * qb - 4.0 * qa * qc, 0.0))) / (2.0 * qa)


def _hill(x: Any) -> Any:
    return np.clip(_hill_fit(x @ ACES_INPUT.T) @ ACES_OUTPUT.T, 0.0, 1.0)


def _neutral(color: Any) -> Any:
    color = np.array(color, dtype='d')
    low = color.min(axis=-1, keepdims=True)
    offset = np.where(low < 0.08, low - 6.25 * low * low, 0.04)
    color = color - offset
    peak = color.max(axis=-1, keepdims=True)
    d = 1.0 - NEUTRAL_START
    compressed = peak >= NEUTRAL_START
    safe = np.where(compressed, peak, 1.0)
    new_peak = 1.0 - d * d / (safe + d - NEUTRAL_START)
    scaled = color * (new_peak / safe)
    g = 1.0 - 1.0 / (NEUTRAL_DESATURATION * (safe - new_peak) + 1.0)
    mixed = scaled * (1.0 - g) + new_peak * g
    return np.where(compressed, mixed, color)


def tone_map(color: Any, operator: str, exposure: float = 1.0) -> Any:
    """``color`` (..., 3) times ``exposure``, through ``operator``'s curve"""
    x = np.asarray(color, dtype='d') * float(exposure)
    if operator == 'none':
        return x
    if operator == 'aces_narkowicz':
        return _narkowicz(x)
    if operator == 'aces_hill':
        return _hill(x)
    if operator == 'aces_hill_exposure_boost':
        return _hill(x / EXPOSURE_BOOST)
    if operator == 'khr_pbr_neutral':
        return _neutral(x)
    raise ValueError('a tone curve is one of %s, not %r' % (OPERATORS, operator))


def _neutral_inverse(shown: Any) -> Any:
    shown = np.minimum(np.asarray(shown, dtype='d'), 1.0 - 1e-6)
    new_peak = shown.max(axis=-1, keepdims=True)
    d = 1.0 - NEUTRAL_START
    compressed = new_peak >= NEUTRAL_START
    peak = np.where(compressed, d * d / (1.0 - new_peak) - d + NEUTRAL_START, new_peak)
    g = 1.0 - 1.0 / (NEUTRAL_DESATURATION * (peak - new_peak) + 1.0)
    safe_peak = np.where(compressed, new_peak, 1.0)
    color = np.where(compressed,
                     (shown - g * new_peak) / (1.0 - g) * (peak / safe_peak),
                     shown)
    low = np.maximum(color.min(axis=-1, keepdims=True), 0.0)
    original = np.where(low < 0.04, np.sqrt(low / 6.25), low + 0.04)
    return color + (original - low)


def untone(shown: Any, operator: str) -> Any:
    """The colour ``operator``'s curve takes to ``shown`` (..., 3), with exposure 1

    ``shown`` is clipped to [0, 1]; a curve that reaches 1 only in the limit
    answers a large finite value there.
    """
    y = np.clip(np.asarray(shown, dtype='d'), 0.0, 1.0)
    if operator == 'none':
        return y
    if operator == 'aces_narkowicz':
        a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
        y = np.minimum(y, 1.0 - 1e-6)
        qa, qb, qc = c * y - a, d * y - b, e * y
        return (-qb - np.sqrt(np.maximum(qb * qb - 4.0 * qa * qc, 0.0))) / (2.0 * qa)
    if operator in ('aces_hill', 'aces_hill_exposure_boost'):
        fitted = np.clip(y @ np.linalg.inv(ACES_OUTPUT).T, 0.0, 1.0)
        x = _hill_fit_inverse(fitted) @ np.linalg.inv(ACES_INPUT).T
        return x * EXPOSURE_BOOST if operator == 'aces_hill_exposure_boost' else x
    if operator == 'khr_pbr_neutral':
        return _neutral_inverse(y)
    raise ValueError('a tone curve is one of %s, not %r' % (OPERATORS, operator))
