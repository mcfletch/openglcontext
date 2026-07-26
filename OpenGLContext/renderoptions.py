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

import logging
import os
from typing import Any, Dict, Optional, Sequence, Tuple

from vrml import protofunctions

log = logging.getLogger(__name__)

__all__ = ['definition', 'flag', 'choice', 'number', 'env_flag', 'env_choice',
           'env_number', 'env_flag_once', 'env_number_once', 'reset_env_cache',
           'CHOICES', 'LABELS']

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
    """A numeric option, or ``default`` where there is no definition.

    Always a float, whatever the field stores: an ``SFInt32`` hands back an
    int and a numpy-backed field a numpy scalar, and a caller left to convert
    is a caller that sometimes forgets.
    """
    value = _value(source, name)
    return float(default if value is None else value)


# -- defaults from the environment ---------------------------------------
# **These are start-up switches, and each is read once.**  A pass that changed
# its mind mid-session because something else edited ``os.environ`` would be
# unpredictable; the ContextDefinition field is the thing meant to change at
# runtime, and it outranks whatever the variable settled.  Use the ``_once``
# forms below wherever the answer is kept; the plain forms are the parsing
# underneath them, for a caller that genuinely wants to look now.
#
# **An unset variable and an empty one mean the same thing**, because that is
# what an unexported shell variable expands to.
#
#: Spellings of "no" accepted by every boolean environment variable.
FALSE_WORDS = ('0', 'off', 'false', 'no', 'none')
TRUE_WORDS = ('1', 'on', 'true', 'yes')

#: The answers already settled, keyed by variable name.  See :func:`env_flag_once`.
_ENV_CACHE: Dict[str, Any] = {}


def reset_env_cache() -> None:
    """Forget the settled answers, so the next read consults the environment.

    A process-lifetime memo needs one of these or it is a one-way door: the
    first read decides for the whole session, and a test that sets the variable
    is silently ignored -- or leaves *its* answer behind for every test after
    it.
    """
    _ENV_CACHE.clear()


def env_flag_once(name: str, default: bool) -> bool:
    """A boolean environment variable, read once and then remembered."""
    if name not in _ENV_CACHE:
        _ENV_CACHE[name] = env_flag(name, default)
    return bool(_ENV_CACHE[name])


def env_number_once(name: str, default: float, integer: bool = False) -> float:
    """A numeric environment variable, read once and then remembered."""
    if name not in _ENV_CACHE:
        _ENV_CACHE[name] = env_number(name, default, integer=integer)
    return float(_ENV_CACHE[name])


def env_flag(name: str, default: bool) -> bool:
    """A boolean environment variable, unset falling back to ``default``.

    A value that is neither a yes nor a no is **reported**, not swallowed:
    these variables are how a feature is pinned for a CI run, and a typo that
    silently reverses the pin makes the result of that run a lie.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if not raw:
        return default
    if raw in FALSE_WORDS:
        return False
    if raw in TRUE_WORDS:
        return True
    log.warning("ignoring %s=%r: expected one of %s", name, raw,
                ', '.join(TRUE_WORDS + FALSE_WORDS))
    return default


def env_choice(name: str, allowed: Sequence[str], synonyms: Dict[str, str],
               default: str = 'auto') -> str:
    """A named environment variable, mapped through its accepted spellings."""
    raw = os.environ.get(name, '').strip().lower()
    if not raw:
        return default
    raw = synonyms.get(raw, raw)
    if raw not in allowed:
        log.warning("ignoring %s=%r: expected one of %s", name, raw,
                    ', '.join(allowed))
        return default
    return raw


def env_number(name: str, default: float, integer: bool = False) -> float:
    """A numeric environment variable, unparseable falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw) if integer else float(raw)
    except ValueError:
        log.warning("ignoring %s=%r: expected a number", name, raw)
        return default
