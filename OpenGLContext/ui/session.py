"""Editing a node on a copy, so Cancel is real at every level.

A dialog's model is a node, and its widgets edit a **copy** of it.  Settings are
already nodes with typed fields -- ``ContextDefinition``, ``WalkMode``,
``KeyBinding`` -- so validation, defaults and serialisation are already there
and a settings screen needs none of its own::

    session = SettingsSession(context.contextDefinition)
    session.draft            # a copy; every widget binds to this
    session.dirty            # whether the draft differs from the target
    session.commit()         # copy the draft's fields back, field by field
    session.revert()         # throw the draft away

**A sub-record is edited by a nested session.**  A movement-settings page
opened from the main screen edits a copy of *the parent's draft* sub-node, and
its Apply writes into that draft -- not into the live node::

    child = session.child('movementModes', index=0)
    child.commit()           # into the parent's draft; still nothing is saved

Only the outermost :meth:`commit` reaches the real node.  That is the whole
point: cancel the movement page and the walk speed is unchanged; cancel the
*settings screen* after applying that page and it is still unchanged.  A child
that wrote straight to the live node would make the parent's Cancel a lie.

Two rules the copying keeps:

* **Commit copies fields into the existing node; it never swaps the node.**  A
  sub-record may be ``USE``d in two places, and replacing the ``SFNode`` would
  leave the second reference pointing at the old one.  Copying field by field
  also means existing watchers are notified normally.
* **Dirtiness propagates upward**, so a settings screen's Apply lights up for a
  change made two dialogs deep.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Set

from pydispatch import dispatcher
from vrml import node as vrmlnode, protofunctions

__all__ = ['SettingsSession', 'copy_node', 'apply_node', 'nodes_equal']

#: Field names the node system keeps for itself.
_INTERNAL = (' DEF', ' root', ' PROTO', 'externalURL')
#: A node class lists here any field that is *published* rather than chosen --
#: state something else writes, which a settings dialog must not carry a stale
#: copy of and write back on Apply.
TRANSIENT_ATTRIBUTE = 'TRANSIENT_FIELDS'


def _editableFields(source: Any) -> List[Any]:
    """The fields a session copies: the settings, and nothing else.

    Out: the node system's own bookkeeping, and anything the class declares in
    ``TRANSIENT_FIELDS`` -- ``ContextDefinition.movementMode``, say, which the
    navigation manager writes to say which mode is in force.  Copying one would
    make a draft hold a stale value and write it back on Apply.
    """
    transient = tuple(getattr(type(source), TRANSIENT_ATTRIBUTE, ()))
    return [definition for definition in protofunctions.getFields(source)
            if definition.name not in _INTERNAL
            and definition.name not in transient
            and not definition.name.startswith(' ')]


def _copyValue(definition: Any, value: Any) -> Any:
    kind = definition.typeName()
    if kind == 'SFNode':
        return copy_node(value) if value else value
    if kind == 'MFNode':
        return [copy_node(child) if child else child for child in value]
    if isinstance(value, list):
        return list(value)
    copier = getattr(value, 'copy', None)
    return copier() if callable(copier) else value


def copy_node(source: Any) -> Any:
    """A deep copy of a node: sub-nodes copied, not shared.

    Sharing them would make a child dialog's edits visible in the parent before
    anything was applied, which is exactly what editing a copy is for.
    """
    clone = source.__class__()
    for definition in _editableFields(source):
        setattr(clone, definition.name,
                _copyValue(definition, getattr(source, definition.name)))
    return clone


def _valuesEqual(definition: Any, left: Any, right: Any) -> bool:
    kind = definition.typeName()
    if kind == 'SFNode':
        if not left or not right:
            return (not left) and (not right)
        return nodes_equal(left, right)
    if kind == 'MFNode':
        if len(left) != len(right):
            return False
        return all(_valuesEqual(_SF_NODE, one, other)
                   for one, other in zip(left, right, strict=True))
    if hasattr(left, 'shape') or hasattr(right, 'shape'):
        return bool(len(left) == len(right) and (left == right).all())
    return bool(left == right)


def nodes_equal(left: Any, right: Any) -> bool:
    """Whether two nodes hold the same values in every field."""
    if left.__class__ is not right.__class__:
        return False
    return all(_valuesEqual(definition,
                            getattr(left, definition.name),
                            getattr(right, definition.name))
               for definition in _editableFields(left))


def apply_node(source: Any, destination: Any) -> None:
    """Copy every field of ``source`` into ``destination``, in place.

    Sub-nodes are recursed into rather than replaced, so a node ``USE``d
    elsewhere keeps its identity and everything watching it keeps working.  A
    field is written only when it actually changed, so committing a page where
    nothing moved wakes nobody.
    """
    for definition in _editableFields(source):
        name = definition.name
        new = getattr(source, name)
        old = getattr(destination, name)
        kind = definition.typeName()
        if kind == 'SFNode' and new and old and new.__class__ is old.__class__:
            apply_node(new, old)
            continue
        if kind == 'MFNode' and len(new) == len(old) and all(
                one and other and one.__class__ is other.__class__
                for one, other in zip(new, old, strict=True)):
            for one, other in zip(new, old, strict=True):
                apply_node(one, other)
            continue
        if _valuesEqual(definition, new, old):
            continue
        setattr(destination, name, _copyValue(definition, new))


class _SFNodeType:
    """Just enough of a field to compare two nodes held in a list."""

    @staticmethod
    def typeName() -> str:
        return 'SFNode'


_SF_NODE = _SFNodeType()


class SettingsSession:
    """One node being edited on a copy, with nested sessions for sub-records."""

    def __init__(self, target: Any, parent: Optional['SettingsSession'] = None
                 ) -> None:
        #: The node this will eventually write back into.  For a child session
        #: that is a node of the *parent's draft*, not a live one.
        self.target = target
        self.parent = parent
        #: Called with this session whenever the draft is edited.
        self.on_dirty: Optional[Callable[['SettingsSession'], None]] = None
        self.draft = copy_node(target)
        #: The values as they stood when the session opened, kept so the caller
        #: can still be told what moved *after* a commit has made the draft and
        #: the target agree.
        self.original = copy_node(target)
        self._watch()

    # -- change notification ----------------------------------------------
    def _watch(self) -> None:
        """Hear about every edit anywhere in the draft.

        Through the field system's own notifications rather than a second
        channel: a widget writes through the field, so this is the one place
        that sees every edit however it arrived.
        """
        self._receiver = self._draftChanged     # a strong reference, held here
        for current in self._draftNodes():
            dispatcher.connect(receiver=self._receiver, sender=current,
                               signal=dispatcher.Any)

    def _unwatch(self) -> None:
        for current in self._draftNodes():
            try:
                dispatcher.disconnect(receiver=self._receiver, sender=current,
                                      signal=dispatcher.Any)
            except dispatcher.errors.DispatcherError:
                pass

    def _draftNodes(self) -> List[Any]:
        found: List[Any] = []
        _collectNodes(self.draft, found)
        return found

    def _draftChanged(self, *args: Any, **named: Any) -> None:
        if self.on_dirty is not None:
            self.on_dirty(self)

    # -- the edit ----------------------------------------------------------
    @property
    def dirty(self) -> bool:
        """Whether the draft differs from what it would be saved over."""
        return not nodes_equal(self.draft, self.target)

    def changed_fields(self) -> Set[str]:
        """The names of the fields the user actually moved.

        Against the values the session opened with rather than against the
        target, so it is still the right answer once :meth:`commit` has written
        the draft through -- which is when a caller saving the user's settings
        wants it.

        This is what tells a *user's* settings apart from the ones a game
        shipped: a file holding only these keeps a player's choices without
        also freezing every default the game may want to change in a later
        build.
        """
        return set(
            definition.name for definition in _editableFields(self.draft)
            if not _valuesEqual(definition, getattr(self.draft, definition.name),
                                getattr(self.original, definition.name)))

    def commit(self) -> None:
        """Write the draft's values into the target, field by field.

        For a child session the target is the enclosing draft, so this is an
        Apply within the dialog above rather than a save.
        """
        apply_node(self.draft, self.target)

    def revert(self) -> None:
        """Throw the draft away and start again from the target."""
        self._unwatch()
        self.draft = copy_node(self.target)
        self._watch()

    # -- nesting -----------------------------------------------------------
    def child(self, attribute: Optional[str] = None, index: Optional[int] = None,
              node: Any = None) -> 'SettingsSession':
        """A session over one sub-record of this session's draft.

        Name a field (and an index, for a list), or pass a node already taken
        out of the draft.  Either way the child edits a copy, and its
        :meth:`commit` writes into *this* draft.
        """
        if node is None:
            if attribute is None:
                raise ValueError("a child needs a field name or a node")
            node = getattr(self.draft, attribute, None)
            if index is not None and node is not None:
                try:
                    node = node[index]
                except (IndexError, TypeError):
                    node = None
        if not node:
            raise ValueError("no sub-record at %r%s"
                             % (attribute, '' if index is None
                                else '[%d]' % (index,)))
        return SettingsSession(node, parent=self)

    def root(self) -> 'SettingsSession':
        """The outermost session -- the only one whose commit actually saves."""
        current = self
        while current.parent is not None:
            current = current.parent
        return current


def _collectNodes(current: Any, found: List[Any]) -> None:
    """Every node in a tree, the root first, with no node visited twice."""
    if any(current is seen for seen in found):
        return
    found.append(current)
    for definition in _editableFields(current):
        kind = definition.typeName()
        if kind == 'SFNode':
            value = getattr(current, definition.name)
            if value and isinstance(value, vrmlnode.Node):
                _collectNodes(value, found)
        elif kind == 'MFNode':
            for child in getattr(current, definition.name):
                if child and isinstance(child, vrmlnode.Node):
                    _collectNodes(child, found)
