"""What a material or an object *is*, and what the engine makes of it.

A glTF carries geometry and PBR factors, and nothing that says "this surface is
water" or "this object is a trigger volume". ``OGLC_hook`` is that tag. It is
one payload with two spellings, either on a material or on a node::

    // extensions -- what a tool writes
    {"OGLC_hook": {"kind": "water", "style": "choppy", "level": 12.5}}

    // extras -- what a Blender custom property becomes
    {"OGLC_hook": {"kind": "water", "style": "choppy"}}

    // extras, shorthand: a bare string is the kind, with no parameters
    {"OGLC_hook": "water"}

The extension wins where both are present, because a file that carries one was
written by a tool that knew what it meant. A ``kind`` nothing is registered for
loads as an ordinary shape, so a file authored for another engine still loads.

An application binds a kind to a factory::

    from OpenGLContext.loaders.gltf import hooks

    @hooks.register('lantern')
    def lantern(ctx: hooks.HookContext):
        ctx.mesh.waveStyle = None
        return None

The factory is called at both hook points -- once per primitive of a tagged
material, once per tagged node -- and ``ctx.at`` says which. What it may return
differs, because the two stand in different places:

``material``
    ``None`` to keep the loader's own ``Shape``, or a node to put in its place.
``node``
    ``None`` to keep the loader's ``Transform`` and children, or
    ``(node, replacing)``: ``False`` puts the node under the glTF node's
    transform, ``True`` puts it in the glTF node's own slot in the parent and
    hands it the placement (``ctx.local_matrix``).

A factory that raises is logged with the kind and the holder, and that
holder loads as the loader built it; the rest of the document loads. A
factory reads its parameters through ``ctx.values``
(:class:`~OpenGLContext.loaders.documentvalues.DocumentValues`), which answers
a default for a value it cannot use and reports it once per document.

**A file names a kind; it never names code.** The registry is populated by the
application, so a downloaded model can only select among what the running
program already registered. The one exception is :data:`BUILTIN` -- a fixed
table in this file naming the kinds the engine itself ships, imported on demand
so an application that never meets water never imports it. There is no
entry-point scan: an installed package cannot add a kind to somebody else's
viewer by being present. ``OPENGLCONTEXT_GLTF_HOOKS=0`` turns the whole
mechanism off.
"""
from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Union, overload,
)

import numpy as np

from OpenGLContext.loaders.documentvalues import DocumentValues

if TYPE_CHECKING:
    from vrml.node import Node

    from OpenGLContext.loaders.resolver import Resolver
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    from OpenGLContext.scenegraph.shape import Shape
    from OpenGLContext.scenegraph.transform import Transform

log = logging.getLogger(__name__)

__all__ = [
    'EXTENSION', 'ENVIRONMENT', 'BUILTIN', 'HookTag', 'HookContext',
    'Registration', 'HookRunner', 'register', 'unregister', 'registered',
    'enabled', 'tag_from', 'tag_for',
]

#: The key a tag is written under, as an ``extensions`` block and as an
#: ``extras`` key alike, so an artist and a tool write the same word.
EXTENSION = 'OGLC_hook'

#: Set this to ``0`` to leave every tag in every file unread.
ENVIRONMENT = 'OPENGLCONTEXT_GLTF_HOOKS'

#: The kinds the engine ships, and the module that registers each. Consulted
#: only when a document names one and nothing has bound it yet. A fixed table
#: in this source: a document selects among these names and cannot name a
#: module of its own.
BUILTIN: Dict[str, str] = {
    'water': 'OpenGLContext.scenegraph.water.gltf',
    'mirror': 'OpenGLContext.scenegraph.mirrorhooks',
    'fire': 'OpenGLContext.scenegraph.particlehooks',
    'smoke': 'OpenGLContext.scenegraph.particlehooks',
    'sparks': 'OpenGLContext.scenegraph.particlehooks',
}

_OFF = ('0', 'no', 'false', 'off')


def enabled() -> bool:
    """Whether tags are read at all, from :data:`ENVIRONMENT`."""
    return os.environ.get(ENVIRONMENT, '1').strip().lower() not in _OFF


# --- the tag ------------------------------------------------------------------

@dataclass(frozen=True)
class HookTag:
    """A kind, and whatever parameters that kind defines."""

    kind: str
    params: Dict[str, Any] = field(default_factory=dict)


def _one_tag(block: Any) -> Optional[HookTag]:
    """One ``OGLC_hook`` value as a tag, or None where it says nothing."""
    if isinstance(block, str):
        kind = block.strip()
        return HookTag(kind) if kind else None
    if isinstance(block, dict):
        kind = str(block.get('kind') or '').strip()
        if not kind:
            log.debug('%s names no kind; the material or node is loaded as it '
                      'stands', EXTENSION)
            return None
        return HookTag(kind, {key: value for key, value in block.items()
                              if key != 'kind'})
    return None


def tag_from(extras: Any, extensions: Any) -> Optional[HookTag]:
    """The tag two holders spell, the extension winning over ``extras``."""
    for holder in (extensions, extras):
        if isinstance(holder, dict) and EXTENSION in holder:
            tag = _one_tag(holder[EXTENSION])
            if tag is not None:
                return tag
    return None


def tag_for(holder: Any) -> Optional[HookTag]:
    """The tag a parsed glTF material or node carries, or None."""
    if holder is None:
        return None
    return tag_from(getattr(holder, 'extras', None),
                    getattr(holder, 'extensions', None))


# --- the registry -------------------------------------------------------------

#: What a hook returns. At the material point: None, or a node to stand in
#: the shape's place. At the node point: None, or ``(node, replacing)``.
HookResult = Union[None, 'Node', Tuple['Node', bool]]

#: A hook, called once per primitive of a tagged material or once per tagged
#: node. See :class:`HookContext` for what it is handed and may return.
Factory = Callable[['HookContext'], HookResult]

#: What a kind does with wall time: ``advance(data, when) -> bool``, where
#: ``data`` is that kind's :attr:`GLTFScene.hook_data` entry and the answer says
#: whether anything changed.
Advance = Callable[[Any, float], bool]


@dataclass(frozen=True)
class Registration:
    """What a kind is bound to."""

    kind: str
    factory: Factory
    #: Whether two nodes referencing one mesh may share the hook's result. A
    #: hook whose result carries per-node state -- a box round where *this*
    #: copy stands, a trigger's fired flag -- says ``False`` and is run once
    #: per node, exactly as a morphed or skinned mesh already is.
    shareable: bool = True
    advance: Optional[Advance] = None


_REGISTRY: Dict[str, Registration] = {}


@overload
def register(kind: str, factory: None = None, *, shareable: bool = True,
             advance: Optional[Advance] = None) -> Callable[[Factory], Factory]: ...


@overload
def register(kind: str, factory: Factory, *, shareable: bool = True,
             advance: Optional[Advance] = None) -> Factory: ...


def register(kind: str, factory: Optional[Factory] = None, *,
             shareable: bool = True,
             advance: Optional[Advance] = None
             ) -> Union[Factory, Callable[[Factory], Factory]]:
    """Bind ``kind`` to a factory, as a decorator or as a call.

    The engine claims the bare lowercase names it documents and ships. An
    application names its own kinds with a prefix -- ``glisteel:rail``,
    ``twigbb:teleporter`` -- so they cannot collide with a kind the engine
    ships later; nothing enforces the prefix.
    """
    def bind(bound: Factory) -> Factory:
        _REGISTRY[kind] = Registration(kind, bound, shareable, advance)
        return bound
    return bind if factory is None else bind(factory)


def unregister(kind: str) -> None:
    """Take a kind out of the registry; unbound kinds are left alone."""
    _REGISTRY.pop(kind, None)


@overload
def registered(kind: None = None) -> Dict[str, Registration]: ...


@overload
def registered(kind: str) -> Optional[Registration]: ...


def registered(kind: Optional[str] = None
               ) -> Union[Dict[str, Registration], Optional[Registration]]:
    """What ``kind`` is bound to, or the whole registry where none is named.

    A viewer reports which of a file's tags it can honour with this. A kind the
    engine ships is imported on being asked for, so it reads as bound whether
    or not anything has loaded one yet.
    """
    if kind is None:
        for name in BUILTIN:
            _ensure_builtin(name)
        return dict(_REGISTRY)
    _ensure_builtin(kind)
    return _REGISTRY.get(kind)


def _ensure_builtin(kind: str) -> None:
    """Import the module that registers one of the engine's own kinds."""
    if kind in _REGISTRY or kind not in BUILTIN:
        return
    try:
        importlib.import_module(BUILTIN[kind])
    except ImportError:                       # pragma: no cover - a broken install
        log.warning('the %r hook ships with the engine and %s will not import; '
                    'a model tagged %r loads as an ordinary shape',
                    kind, BUILTIN[kind], kind)


# --- what a hook is handed ----------------------------------------------------

@dataclass
class HookContext:
    """Everything a hook is given, and the two things it may write.

    ``at`` is ``'material'`` or ``'node'``: one factory serves both points, and
    which one it stands at decides what the return value means.

    At the material point ``mesh``, ``material`` and ``shape`` are the finished
    objects rather than the accessors they came from, ``primitive`` is the glTF
    primitive, and ``bounds`` is the primitive's **local** box -- the pair the
    loader frames the camera from, writable by a hook that changes the extent.
    For a kind registered ``shareable=False``, ``world_matrix`` is where this
    copy of the primitive stands and :meth:`world_bounds` places the box
    there; a shareable kind's result serves every node on the mesh, so it is
    given no ``world_matrix`` and :meth:`world_bounds` answers None.

    At the node point ``node`` is the glTF node record, ``transform`` the
    ``Transform`` the loader built for it, ``children`` the subtree gathered
    under it, and ``local_matrix`` the placement that transform applies -- which
    is the placement a hook taking the node's own slot takes on.
    """

    at: str
    kind: str
    params: Dict[str, Any]
    #: The parsed glTF document (a ``pygltflib.GLTF2``).
    document: Any
    resolver: 'Resolver'
    #: The dict that becomes :attr:`GLTFScene.hook_data`, keyed by kind.
    scene_data: Dict[str, Any]
    #: Row-vector 4x4, or None; see above.
    world_matrix: Optional[np.ndarray] = None
    #: What a hook reads its parameters through: each value a hook cannot use
    #: is reported once for the whole document.
    values: DocumentValues = field(default_factory=DocumentValues)

    # the material point
    #: The glTF primitive record (a ``pygltflib.Primitive``).
    primitive: Any = None
    mesh: Optional['PBRMesh'] = None
    material: Optional['PBRMaterial'] = None
    shape: Optional['Shape'] = None
    bounds: Optional[Tuple[np.ndarray, np.ndarray]] = None

    # the node point
    #: The glTF node record (a ``pygltflib.Node``).
    node: Any = None
    transform: Optional['Transform'] = None
    children: List['Node'] = field(default_factory=list)
    local_matrix: Optional[np.ndarray] = None

    def collect(self, item: Any) -> Any:
        """Put one record in this kind's ``hook_data`` entry, and return it.

        The list is made on the first record, so a scene with no tag of this
        kind has no entry rather than an empty one.
        """
        self.scene_data.setdefault(self.kind, []).append(item)
        return item

    def world_bounds(self) -> Optional[Tuple[Any, Any]]:
        """:attr:`bounds` placed in the world, as a world-aligned box.

        None where there is nothing to place -- a node hook's context carries
        no primitive of its own.
        """
        if self.bounds is None or self.world_matrix is None:
            return None
        from OpenGLContext.loaders.gltf.transforms import _world_box
        return _world_box(np.asarray(self.world_matrix, dtype='d'), self.bounds)


# --- running them -------------------------------------------------------------

#: What :meth:`HookRunner._run` answers for a factory that raised.
_FAILED = object()

class HookRunner:
    """The hooks one document's tags name, for the length of one load.

    Holds the ``hook_data`` the hooks write and says an unknown kind once,
    rather than once per primitive of every node that uses it.
    :attr:`registrations` is what each kind the load ran was bound to, which
    is what advances that kind's ``hook_data`` afterwards.
    """

    def __init__(self, document: Any, resolver: Any,
                 on: Optional[bool] = None,
                 values: Optional[DocumentValues] = None) -> None:
        self.document = document
        self.resolver = resolver
        self.scene_data: Dict[str, Any] = {}
        self.on = enabled() if on is None else bool(on)
        #: What every hook of this load reads its parameters through.
        self.values = values if values is not None else DocumentValues()
        #: What each kind met in this load was bound to, as it was then.
        self.registrations: Dict[str, Registration] = {}
        self._unknown: Set[str] = set()

    def _bound(self, holder: Any) -> Optional[Tuple[HookTag, Registration]]:
        """The tag a holder carries and what it is bound to, or None.

        None covers the three ways there is nothing to run: the mechanism is
        off, the holder carries no tag, and the tag names a kind nothing is
        registered for -- which is said once, rather than once per primitive of
        every node that uses it.
        """
        if not self.on:
            return None
        tag = tag_for(holder)
        if tag is None:
            return None
        entry = registered(tag.kind)
        if entry is None:
            if tag.kind not in self._unknown:
                self._unknown.add(tag.kind)
                log.debug('nothing is registered for the %s kind %r; what '
                          'carries it is loaded as it stands',
                          EXTENSION, tag.kind)
            return None
        self.registrations.setdefault(tag.kind, entry)
        return tag, entry

    def shareable(self, material_def: Any) -> bool:
        """Whether a material's hook, if it has one bound, may share its result."""
        found = self._bound(material_def)
        return True if found is None else found[1].shareable

    def _run(self, entry: Registration, ctx: HookContext, holder: Any) -> Any:
        """What ``entry``'s factory returns, or :data:`_FAILED` where it raised.

        The exception is logged with the kind and the holder, and the holder
        loads as the loader built it: a hook that fails on one material or
        node costs that holder its hook, and the rest of the document loads.
        """
        try:
            return entry.factory(ctx)
        except Exception:
            log.exception('the %s hook %r failed on %s %r; it is loaded as an '
                          'ordinary %s', EXTENSION, entry.kind, ctx.at,
                          getattr(holder, 'name', None) or '(unnamed)', ctx.at)
            return _FAILED

    def _context(self, at: str, tag: HookTag, **named: Any) -> HookContext:
        return HookContext(at=at, kind=tag.kind, params=dict(tag.params),
                           document=self.document, resolver=self.resolver,
                           scene_data=self.scene_data, values=self.values,
                           **named)

    def material(self, primitive: Any, material_def: Any, mesh: Any,
                 material: Any, shape: Any, bounds: Any,
                 world: Optional[np.ndarray] = None) -> Tuple[Any, Any, bool]:
        """Run a tagged material's hook. Returns ``(node, bounds, shareable)``.

        ``world`` reaches only a hook whose kind is not shareable.
        """
        found = self._bound(material_def)
        if found is None:
            return shape, bounds, True
        tag, entry = found
        ctx = self._context('material', tag, primitive=primitive, mesh=mesh,
                            material=material, shape=shape, bounds=bounds,
                            world_matrix=None if entry.shareable else world)
        made = self._run(entry, ctx, material_def)
        if made is _FAILED:
            return shape, bounds, entry.shareable
        return (shape if made is None else made), ctx.bounds, entry.shareable

    def node(self, node_def: Any, transform: 'Transform', children: List['Node'],
             local: np.ndarray, world: np.ndarray) -> Optional[Tuple['Node', bool]]:
        """Run a tagged node's hook.

        Returns ``None`` where the loader keeps what it built, or the
        ``(node, replacing)`` pair the hook asked for.
        """
        found = self._bound(node_def)
        if found is None:
            return None
        tag, entry = found
        ctx = self._context('node', tag, node=node_def, transform=transform,
                            children=children, local_matrix=local,
                            world_matrix=world)
        made = self._run(entry, ctx, node_def)
        if made is None or made is _FAILED:
            return None
        if not (isinstance(made, tuple) and len(made) == 2):
            raise ValueError(
                "the %r hook returned %r for a node; a node hook returns None, "
                "or the node and whether it is replacing the one the loader "
                "built -- (node, True) to take its slot, (node, False) to stand "
                "under its transform" % (tag.kind, made))
        return made[0], bool(made[1])
