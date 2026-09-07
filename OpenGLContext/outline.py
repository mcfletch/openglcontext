"""The scenegraph as a flat list of rows, for a tree control to show

A :class:`SceneOutline` walks a scenegraph, keeps a set of expanded rows and a
selection, and re-walks when the scene changes underneath it.  It holds no GL
and knows no toolkit, so one model feeds a ``ttk.Treeview``, a ``QTreeView`` and
a ``wx.TreeCtrl`` alike -- and an application that wants to know what is in the
scene it just loaded can ask it without opening a window at all::

    from OpenGLContext.outline import SceneOutline

    outline = SceneOutline(context.sg, onChange=self.treeNeedsRefilling)
    for row in outline.rows:
        print('  ' * row.depth, row.label)
    outline.toggle(outline.rows[1].path)

**Children are the node-valued fields**, in name order: a ``Transform``'s
``children``, and equally a ``Shape``'s ``geometry`` and ``appearance``, which
the rendering traversal does not descend into and an inspector wants.  Two
kinds of value are passed over: a field holding a *weak* reference, which is a
pointer back into the scene rather than a part of it (every node's ``root``),
and a value that is not a node (a scenegraph's ``routes``).

A row is addressed by its **path** -- the child indices from the root, so
``(0, 2)`` is the third child of the first -- which stays meaningful across a
rebuild and is what expansion and selection are recorded as.  One node reached
by two routes gets a row under each, since that is what sharing looks like.

**Changes arrive on whichever thread made them.**  The viewer loads on a worker
thread, so the scene is built off the render thread and ``onChange`` is called
there; a toolkit's widgets belong to its own thread.  So ``onChange`` is a
*notice*, not a place to fill a tree from: set a flag, and refill from the
host's own timer or idle callback, which is what the demos in
:mod:`OpenGLContext.demos` do.  One notice covers every change until the rows
are next read, so a busy scene does not flood the host.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from pydispatch import dispatcher
from vrml import field as _field
from vrml import node as _node
from vrml import protofunctions

__all__ = ['OutlinePath', 'OutlineRow', 'SceneOutline', 'isNode', 'nodeChildren',
           'nodeFields', 'nodeSummary']

log = logging.getLogger(__name__)

#: A row's address: the child indices leading to it from the root, which is ``()``.
OutlinePath = Tuple[int, ...]


def nodeFields(node: Any) -> List[Any]:
    """The fields of *node* that hold the nodes under it, in name order

    A weak field is left out: it refers to a node that lives somewhere else,
    and following it walks back up the scene rather than down it.
    """
    fields = [
        field for field in protofunctions.getFields(node)
        if getattr(field, 'nodes', 0) and not isinstance(field, _field.WeakField)
    ]
    return sorted(fields, key=lambda field: field.name)


def nodeChildren(node: Any) -> List[Tuple[str, Any]]:
    """The nodes under *node*, each with the name of the field it hangs from

    Single- and multiple-valued fields read the same way here: ``geometry``
    contributes one child and ``children`` contributes as many as it holds.
    """
    children: List[Tuple[str, Any]] = []
    for field in nodeFields(node):
        try:
            value = field.fget(node)
        except Exception:
            log.debug('could not read %s of %r', field.name, node, exc_info=True)
            continue
        if isNode(value):
            children.append((field.name, value))
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            children.extend((field.name, item) for item in value if isNode(item))
    return children


def isNode(value: Any) -> bool:
    """Whether *value* is a node the outline shows

    An empty single-valued field holds VRML97's ``NULL``, which is a node in
    the type system and nothing to look at in a tree.
    """
    return isinstance(value, _node.Node) and not isinstance(value, _node.NullNode)


def nodeSummary(node: Any, width: int = 60) -> List[Tuple[str, str]]:
    """What one node holds, as ``(field name, value)`` text in name order

    The panel beside a tree: the values a node carries in its own right, with
    the nodes under it left out, since those are rows of their own.  A value
    too long for the panel is cut to *width*, and one that will not be read is
    reported as ``'?'`` rather than taking the panel down with it.
    """
    if node is None:
        return []
    summary: List[Tuple[str, str]] = []
    for field in sorted(protofunctions.getFields(node), key=lambda field: field.name):
        if getattr(field, 'nodes', 0) or field.name.startswith(' '):
            continue
        try:
            text = str(field.fget(node))
        except Exception:
            log.debug('could not read %s of %r', field.name, node, exc_info=True)
            text = '?'
        text = ' '.join(text.split())
        summary.append((field.name, text[:width - 1] + '…'
                        if len(text) > width else text))
    return summary


class OutlineRow(NamedTuple):
    """One line of the outline: a node, where it is, and what to call it"""

    #: Child indices from the root; ``()`` is the root itself.
    path: OutlinePath
    #: The node this row stands for.
    node: Any
    #: How far in to indent it, which is ``len(path)``.
    depth: int
    #: The field of the parent this node hangs from, or None for the root.
    field: Optional[str]
    #: The name the file gave this node, or ``''`` where it gave none.
    defName: str
    #: The node's type, as a scene file spells it.
    nodeType: str
    #: Whether there is anything under it to open.
    expandable: bool

    @property
    def label(self) -> str:
        """What to show: the name the scene gave the node, else its type."""
        return self.defName or self.nodeType


class SceneOutline:
    """A scenegraph as rows, with expansion, selection, and notice of changes

    root -- the scenegraph to walk, which may be replaced at any time
    onChange -- called with no arguments when the scene has changed and the
        rows need reading again.  Called on the thread that made the change;
        see the module documentation.
    """

    def __init__(
        self,
        root: Any = None,
        onChange: Optional[Callable[[], None]] = None,
        expanded: Optional[Iterable[OutlinePath]] = None,
    ) -> None:
        self.onChange = onChange
        #: The paths whose children are shown.  The root opens with the scene.
        self.expanded: Set[OutlinePath] = (
            {()} if expanded is None else {tuple(path) for path in expanded}
        )
        self._root: Any = None
        self._rows: List[OutlineRow] = []
        self._dirty = False
        self._selection: Optional[OutlinePath] = None
        #: The nodes being listened to, and the fields listened to on each.
        self._watched: Dict[int, Tuple[Any, Tuple[Any, ...]]] = {}
        self.root = root

    # -- the scene --------------------------------------------------------
    @property
    def root(self) -> Any:
        """The scenegraph being shown."""
        return self._root

    @root.setter
    def root(self, root: Any) -> None:
        self._root = root
        self._selection = None
        # Walked at once rather than at the first read: listening to the scene
        # begins with being given one, so a host that is told of a change
        # before it has drawn its first tree is still told.
        self.refresh()

    def close(self) -> None:
        """Let go of the scene and stop listening to it

        A viewer that opens one model after another calls this on the way out
        of the last one: the rows are what would otherwise keep every scene it
        has ever shown alive.
        """
        self.root = None

    # -- the rows ---------------------------------------------------------
    @property
    def rows(self) -> List[OutlineRow]:
        """The visible rows, walked again first if the scene has changed."""
        if self._dirty:
            self.refresh()
        return self._rows

    def refresh(self) -> List[OutlineRow]:
        """Walk the scene now, whether or not anything said it had changed."""
        rows = self._walk()
        self._rows = rows
        self._dirty = False
        self._updateWatches(rows)
        return rows

    @property
    def dirty(self) -> bool:
        """Whether the rows want walking again

        Set by a change to the scene and by opening or closing a row alike:
        either way the host's tree no longer matches the model.
        """
        return self._dirty

    def _walk(self) -> List[OutlineRow]:
        """Depth-first through the expanded part of the scene"""
        if self._root is None:
            return []
        rows: List[OutlineRow] = []
        # An explicit stack rather than recursion: how deep a loaded scene goes
        # is the file's business, so it is bounded by memory here rather than by
        # the interpreter's recursion limit.
        # ``above`` is the identity of every node on the way to this one, which
        # is what stops a scene that refers back to itself being walked twice.
        stack: List[Tuple[OutlinePath, Any, Optional[str], Tuple[int, ...]]] = [
            ((), self._root, None, ())
        ]
        while stack:
            path, node, field, above = stack.pop()
            children = [] if id(node) in above else nodeChildren(node)
            rows.append(OutlineRow(
                path=path,
                node=node,
                depth=len(path),
                field=field,
                defName=protofunctions.defName(node) or '',
                nodeType=protofunctions.protoName(node) or type(node).__name__,
                expandable=bool(children),
            ))
            if children and path in self.expanded:
                below = above + (id(node),)
                for index in reversed(range(len(children))):
                    childField, child = children[index]
                    stack.append((path + (index,), child, childField, below))
        return rows

    # -- expansion --------------------------------------------------------
    def expand(self, path: OutlinePath) -> None:
        """Show what is under *path*."""
        self.expanded.add(tuple(path))
        self._dirty = True

    def collapse(self, path: OutlinePath) -> None:
        """Hide what is under *path*."""
        self.expanded.discard(tuple(path))
        self._dirty = True

    def toggle(self, path: OutlinePath) -> bool:
        """Open *path* if it is closed and close it if it is open

        Returns whether it is now open, which is what a tree control's own
        handler wants to hear.
        """
        path = tuple(path)
        if path in self.expanded:
            self.collapse(path)
            return False
        self.expand(path)
        return True

    # -- selection --------------------------------------------------------
    def select(self, path: Optional[OutlinePath]) -> None:
        """Select the row at *path*, or nothing when given None."""
        self._selection = None if path is None else tuple(path)

    @property
    def selection(self) -> Optional[OutlinePath]:
        """The selected path, or None once it is no longer a row."""
        row = self._selectedRow()
        return None if row is None else row.path

    @property
    def selected(self) -> Any:
        """The selected node, or None where nothing is selected."""
        row = self._selectedRow()
        return None if row is None else row.node

    @property
    def selectedRow(self) -> Optional[OutlineRow]:
        """The selected row, for a panel that wants its type and name too."""
        return self._selectedRow()

    def _selectedRow(self) -> Optional[OutlineRow]:
        """The selected row, letting go of a selection the scene has dropped"""
        if self._selection is not None:
            for row in self.rows:
                if row.path == self._selection:
                    return row
            self._selection = None
        return None

    # -- watching the scene -----------------------------------------------
    def _watchedFields(self, node: Any) -> Tuple[Any, ...]:
        """The fields of *node* whose changing changes this outline

        Which is the structure under it, and the name it is shown by.
        """
        return tuple(nodeFields(node)) + (_node.Node.DEF,)

    def _updateWatches(self, rows: Iterable[OutlineRow]) -> None:
        """Listen to the nodes now shown, and to no others

        A node keeps its subscription across a walk that still shows it, so an
        outline of a large scene does not disconnect and reconnect thousands of
        fields for each change.
        """
        wanted: Dict[int, Any] = {}
        for row in rows:
            wanted.setdefault(id(row.node), row.node)
        for key, (node, fields) in list(self._watched.items()):
            if key not in wanted:
                self._connect(node, fields, dispatcher.disconnect)
                del self._watched[key]
        for key, node in wanted.items():
            if key not in self._watched:
                fields = self._watchedFields(node)
                self._connect(node, fields, dispatcher.connect)
                self._watched[key] = (node, fields)

    def _connect(self, node: Any, fields: Tuple[Any, ...], action: Callable[..., Any]) -> None:
        """Subscribe to, or unsubscribe from, each of *fields* on *node*

        Both the value being replaced and the field being deleted are changes
        to the same thing as far as a tree showing it is concerned.
        """
        for field in fields:
            for kind in ('set', 'del'):
                action(self._changed, (kind, field), node)

    def _changed(self, signal: Any = None, sender: Any = None, **named: Any) -> None:
        """A watched field changed: the rows want walking again

        Told once until the rows are read, since a host refills its tree from
        the whole list and a scene being assembled changes a great many fields
        on the way to being one thing to look at.
        """
        if self._dirty:
            return
        self._dirty = True
        if self.onChange is not None:
            try:
                self.onChange()
            except Exception:
                log.exception('outline change handler failed')
