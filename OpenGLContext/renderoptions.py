"""Reading a rendering feature's setting from the context that is rendering.

Every switchable feature -- shadows, bloom, image-based lighting, transmission,
instancing, level of detail -- is a **field on the**
:class:`~OpenGLContext.contextdefinition.ContextDefinition`, whose default comes
from the environment variable that used to be the only way to set it.  That
means one source of truth: a shell variable still pins a feature for a script or
a CI run, while a settings screen can show it, change it and have the change
take effect on the next frame.

A render pass asks through here rather than reading the environment itself,
because a pass knows its context and the context knows its definition::

    if renderoptions.flag(self, 'shadows', True):
        ...

Anything with no definition behind it -- a bare pass in a unit test -- gets the
default, so nothing has to construct a context to render.

Three-valued settings use ``'auto'``, which means "the engine decides": IBL and
transmission both degrade themselves on a software rasteriser, and a screen that
forced a choice would take that away.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Sequence, Tuple

from vrml import protofunctions

__all__ = ['definition', 'flag', 'choice', 'number', 'CHOICES', 'LABELS']

#: The values each three-valued option accepts, in the order a settings screen
#: cycles them.  ``auto`` is first because it is the default.
CHOICES: Dict[str, Tuple[str, ...]] = {
    'ibl': ('auto', 'full', 'analytic', 'off'),
    'transmission': ('auto', 'full', 'blend', 'off'),
    'profile': ('compatibility', 'core'),
}

#: What a settings screen shows for each of those values.
LABELS: Dict[str, Tuple[str, ...]] = {
    'ibl': ('Automatic', 'Full probe', 'Analytic', 'Off'),
    'transmission': ('Automatic', 'Refractive', 'Blended', 'Off'),
    'profile': ('Compatibility', 'Core'),
}


def definition(source: Any) -> Optional[Any]:
    """The ContextDefinition behind a pass, a render mode or a context.

    None when there is nothing to ask, which is the normal case in a unit test
    that instantiates a pass without a window.
    """
    found = getattr(source, 'contextDefinition', None)
    if found is not None:
        return found
    context = getattr(source, 'context', None)
    if context is not None:
        return getattr(context, 'contextDefinition', None)
    return None


def _value(source: Any, name: str) -> Any:
    """A field's value, but only if something actually set it.

    A field nobody has touched reports None so the caller's default stands --
    and every caller's default reads its environment variable *at call time*.
    That is what keeps a demo that flips ``OPENGLCONTEXT_BLOOM`` between models
    working, while a settings screen that writes the field takes precedence
    from then on.
    """
    found = definition(source)
    if found is None:
        return None
    try:
        declared = protofunctions.getField(found, name)
    except AttributeError:
        return None
    if not declared.fhas(found):
        return None
    return getattr(found, name, None)


def flag(source: Any, name: str, default: bool) -> bool:
    """A boolean option, or ``default`` where there is no definition."""
    value = _value(source, name)
    return default if value is None else bool(value)


def choice(source: Any, name: str, default: str) -> str:
    """A named option, or ``default`` where there is no definition."""
    value = _value(source, name)
    return default if not value else str(value)


def number(source: Any, name: str, default: float) -> float:
    """A numeric option, or ``default`` where there is no definition."""
    value = _value(source, name)
    return default if value is None else value


# -- defaults from the environment ---------------------------------------
#: Spellings of "no" accepted by every boolean environment variable.
FALSE_WORDS = ('0', 'off', 'false', 'no', 'none', '')
TRUE_WORDS = ('1', 'on', 'true', 'yes')


def env_flag(name: str, default: bool) -> bool:
    """A boolean environment variable, unset falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in FALSE_WORDS:
        return False
    if raw in TRUE_WORDS:
        return True
    return default


def env_choice(name: str, allowed: Sequence[str], synonyms: Dict[str, str],
               default: str = 'auto') -> str:
    """A named environment variable, mapped through its accepted spellings."""
    raw = os.environ.get(name, '').strip().lower()
    raw = synonyms.get(raw, raw)
    return raw if raw in allowed else default


def env_number(name: str, default: float, integer: bool = False) -> float:
    """A numeric environment variable, unparseable falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw) if integer else float(raw)
    except ValueError:
        return default
