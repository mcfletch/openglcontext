"""Building a settings page from a node's fields.

The field's type picks the editor, so a new ``SFFloat`` on ``WalkMode`` appears
in the settings screen with no UI work and cannot silently go missing.  A screen
that wants better grouping or wording supplies an authored
:class:`~OpenGLContext.ui.panel.Panel` instead; this is the fallback, and the
cost of having one is a single path.

A node class says how its fields should be presented by declaring ``UI_HINTS``
beside them::

    class WalkMode(MovementMode):
        walkSpeed = field.newField('walkSpeed', 'SFFloat', 1, 3.0)
        UI_HINTS = {
            'walkSpeed': {'label': 'Walking speed', 'minimum': 0.5,
                          'maximum': 20.0, 'step': 0.5},
        }

Without a hint a number gets a text field rather than a slider, because a
slider with no range is a slider over 0..1 and that is a wrong answer rather
than a missing one.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from vrml import protofunctions

from OpenGLContext.ui.layout import Grid
from OpenGLContext.ui.widgets import (
    KeyCapture, Label, NumberField, Select, Slider, TextField, Toggle, Widget,
)

__all__ = ['hints_for', 'editor_for', 'page_for', 'label_for',
           'COLUMN_FLEX', 'COLUMN_SPACING', 'ROW_SPACING', 'ROW_PADDING']

#: Attribute a node class declares its presentation in.
HINTS_ATTRIBUTE = 'UI_HINTS'
#: Field types with no sensible one-line editor.  A sub-record gets a button to
#: its own page, which is an authoring decision rather than a generated one.
UNEDITABLE = ('SFNode', 'MFNode', 'SFImage', 'SFArray', 'SFArray32')
#: Editors that are a fixed size and belong against the right margin.  The rest
#: -- a slider, a text field -- have a length worth reading and stretch.
COMPACT = (Toggle, Select, KeyCapture)
#: How the label and control columns share the width.  Even, so the controls
#: line up down the page instead of stepping in and out with the labels, and so
#: neither column is a sliver on a wide display.
COLUMN_FLEX = (1.0, 1.0)
#: Pixels at the reference font size between the two columns, between one row
#: and the next, and around each row's contents.
COLUMN_SPACING = 24.0
ROW_SPACING = 0.0
ROW_PADDING = 7.0

#: Names that are words in their own right and are shouted, not spelled.  A
#: graphics settings page is full of them, and "Ibl" reads as a mistake.
ACRONYMS = frozenset((
    'ibl', 'ui', 'lod', 'fps', 'hdr', 'gl', 'gpu', 'msaa', 'ao', 'pbr',
    'srgb', 'uv', 'vr', 'fov', 'dpi',
))

_CAMEL = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def label_for(name: str, hint: Optional[Dict[str, Any]] = None) -> str:
    """What to call a field on screen: its hint, or its name made readable.

    Sentence case, because a settings page is a list of things rather than a
    row of headings -- except for the acronyms a graphics setting is full of,
    which are words in their own right and unreadable lower-cased.  "Ibl
    intensity" is a typo; "IBL intensity" is the setting.
    """
    if hint and hint.get('label'):
        return str(hint['label'])
    words = [_word(word, first=index == 0)
             for index, word in enumerate(_CAMEL.sub(' ', name).split())]
    return ' '.join(words)


def _word(word: str, first: bool) -> str:
    """One word of a generated label, cased for where it sits."""
    if word.lower() in ACRONYMS:
        return word.upper()
    return word.capitalize() if first else word.lower()


def hints_for(node: Any) -> Dict[str, Dict[str, Any]]:
    """The presentation hints for a node, base classes included.

    Walked from the base classes down so a subclass can refine how an inherited
    field is shown -- a swim speed and a walk speed want different ranges.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for klass in reversed(type(node).__mro__):
        declared = klass.__dict__.get(HINTS_ATTRIBUTE)
        if not declared:
            continue
        for name, hint in declared.items():
            merged.setdefault(name, {}).update(hint)
    return merged


def editor_for(node: Any, name: str, hint: Optional[Dict[str, Any]] = None
               ) -> Optional[Widget]:
    """The widget that edits one field, or None if it has no simple editor.

    Without a ``hint`` the node's own ``UI_HINTS`` are consulted, so asking for
    one field's editor gives the same answer as asking for the whole page.  A
    hint that reached only the page builder would make a field editable in one
    and not the other, which is the drift this module exists to prevent.
    """
    try:
        definition = protofunctions.getField(node, name)
    except AttributeError:
        # A screen naming a field this build does not have shows nothing for
        # it rather than failing to open at all.
        return None
    if hint is None:
        hint = hints_for(node).get(name)
    hint = dict(hint or {})
    kind = definition.typeName()
    if kind in UNEDITABLE or hint.get('skip'):
        return None
    common = {'target': node, 'fieldName': name, 'name': name}
    if kind == 'SFBool':
        return Toggle(**common)
    if kind in ('SFInt32', 'SFUInt32', 'SFFloat', 'SFTime'):
        return _numberEditor(kind, hint, common)
    if kind == 'SFString':
        if hint.get('options'):
            return Select(options=list(hint['options']),
                          optionLabels=list(hint.get('optionLabels', ())),
                          **common)
        return TextField(maximumLength=int(hint.get('maximumLength', 0)),
                         **common)
    if kind == 'MFString' and hint.get('editor') == 'keys':
        return KeyCapture(**common)
    return None


def _numberEditor(kind: str, hint: Dict[str, Any],
                  common: Dict[str, Any]) -> Widget:
    integer = kind in ('SFInt32', 'SFUInt32')
    if 'minimum' in hint and 'maximum' in hint:
        return Slider(minimum=float(hint['minimum']),
                      maximum=float(hint['maximum']),
                      step=float(hint.get('step', 1.0 if integer else 0.0)),
                      integer=integer, suffix=str(hint.get('suffix', '')),
                      **common)
    # No range means no slider: one over an invented 0..1 is a wrong answer
    # rather than a missing one.  A number is still typed as text, but through
    # a field that knows it is a number -- a plain text field bound to an
    # SFFloat would hand string arithmetic a float on the first keystroke.
    return NumberField(integer=integer, **common)


def page_for(node: Any, hints: Optional[Dict[str, Dict[str, Any]]] = None,
             include: Optional[Sequence[str]] = None,
             exclude: Iterable[str] = (), columns: int = 2) -> Grid:
    """A label/control grid for a node's fields.

    ``include`` names and orders the fields to show; without it every field
    that has an editor appears, in declaration order, which is what makes a
    newly added setting turn up on its own.

    The two columns share the width evenly and each row is given room around
    it, so a page reads as a list of settings at any window size rather than as
    labels crushed against controls on the left and a great deal of nothing on
    the right.
    """
    hints = dict(hints or hints_for(node))
    skipped = set(exclude)
    names = list(include) if include is not None else _fieldNames(node)
    cells: List[Widget] = []
    for name in names:
        if name in skipped:
            continue
        editor = editor_for(node, name, hints.get(name))
        if editor is None:
            continue
        hint = hints.get(name) or {}
        cells.append(Label(text=label_for(name, hint), name='%s.label' % (name,)))
        if isinstance(editor, COMPACT):
            editor.alignSelf = 'end'
        cells.append(editor)
    return Grid(children=cells, columns=columns, columnFlex=list(COLUMN_FLEX),
                columnSpacing=COLUMN_SPACING, spacing=ROW_SPACING,
                rowPadding=ROW_PADDING)


def _fieldNames(node: Any) -> List[str]:
    return [definition.name for definition in protofunctions.getFields(node)
            if not definition.name.startswith(' ')]
