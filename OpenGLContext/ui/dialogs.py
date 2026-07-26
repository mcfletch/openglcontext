"""Ready-made dialogs: a question, a message, and a wall of text.

These are the shapes an application asks for often enough that building them
out of widgets every time would be busywork.  Each returns a
:class:`~OpenGLContext.ui.panel.Panel` for the caller to push onto a context's
overlay stack::

    context.pushOverlay(dialogs.confirm(
        'Download the core textures?',
        detail='About 40MB, cached for next time.',
        on_answer=self.texturesAnswered))

The buttons are **real measured rectangles**, hovered and clicked with the
pointer; the keys are accelerators for anyone who prefers them, not the only
way in.  A question that can only be dismissed by guessing a key is a bad
question.
"""

from __future__ import annotations

from gettext import gettext as _
from typing import Callable, Optional, Sequence

from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Button, Label, Spacer, DANGER, PRIMARY

__all__ = ['confirm', 'message', 'notice']

#: Content width, in characters, that a text dialog aims for.  Roughly a
#: newspaper column: long enough not to hyphenate, short enough to read.
DIALOG_COLUMNS = 56
#: Keys that answer a question, unless the caller names others.
YES_KEYS = ('y',)
NO_KEYS = ('n',)


def confirm(question: str, detail: str = '',
            on_answer: Optional[Callable[[bool], None]] = None,
            yes: Optional[str] = None, no: Optional[str] = None,
            title: str = '',
            danger: bool = False,
            yes_keys: Sequence[str] = YES_KEYS,
            no_keys: Sequence[str] = NO_KEYS) -> Panel:
    """A modal yes/no question.

    ``on_answer`` is called once, with True or False; Escape and the panel's
    Cancel both answer False, because a question dismissed without an answer is
    a No in every case this is used for.  ``danger`` marks the affirmative as
    the destructive one -- resetting bindings, discarding changes.
    """
    yes_button = Button(text=yes or _('Yes'), name='yes',
                        role=DANGER if danger else PRIMARY,
                        accelerator=yes_keys[0] if yes_keys else '')
    no_button = Button(text=no or _('No'), name='no',
                       accelerator=no_keys[0] if no_keys else '')
    body = [Label(text=question, wrap=True, name='question')]
    if detail:
        body.append(Label(text=detail, wrap=True, name='detail', top=4))
    body.append(Row(children=[Spacer(), no_button, yes_button], spacing=8,
                    top=8, name='buttons'))
    panel = Panel(title=title, scrim=True, modal=True,
                  preferredColumns=DIALOG_COLUMNS,
                  children=[Column(children=body, spacing=4)])
    answered: list = []

    def answer(value: bool) -> None:
        if answered:
            return
        answered.append(value)
        panel.close(value)
        if on_answer is not None:
            on_answer(value)

    yes_button.on_activate = lambda widget: answer(True)
    no_button.on_activate = lambda widget: answer(False)
    # Escape is a No, so a prompt closed any other way still reports one answer.
    panel.on_close = lambda closing: answer(False)
    for extra in yes_keys[1:]:
        panel.accelerators[extra] = lambda dialog: answer(True)
    for extra in no_keys[1:]:
        panel.accelerators[extra] = lambda dialog: answer(False)
    return panel


def message(text: str, title: str = '', button: Optional[str] = None,
            on_close: Optional[Callable[[Panel], None]] = None) -> Panel:
    """Something the user has to acknowledge, with one button."""
    ok = Button(text=button or _('OK'), role=PRIMARY, name='ok')
    panel = Panel(title=title, scrim=True, modal=True,
                  preferredColumns=DIALOG_COLUMNS,
                  children=[Column(children=[
                      Label(text=text, wrap=True, name='message'),
                      Row(children=[Spacer(), ok], top=8),
                  ], spacing=4)])
    ok.on_activate = lambda widget: panel.close(True)
    if on_close is not None:
        panel.on_close = on_close
    return panel


def notice(title: str, text: str, columns: int = 78,
           on_close: Optional[Callable[[Panel], None]] = None) -> Panel:
    """A wall of text nobody can style away -- a copyright or licence notice.

    Filling the window and scrolling rather than sizing to the text: these run
    to thousands of words, and a panel that grew to fit one would be taller
    than any screen.
    """
    from OpenGLContext.ui.scroll import ScrollViewport

    close = Button(text=_('Close'), role=PRIMARY, name='close')
    body = ScrollViewport(name='body', flex=1, children=[
        Label(text=text, wrap=True, name='text')])
    panel = Panel(title=title, modal=True, scrim=True, fill=True,
                  preferredColumns=columns,
                  children=[Column(children=[
                      body,
                      Row(children=[Spacer(), close], top=8),
                  ], spacing=4)])
    close.on_activate = lambda widget: panel.close(True)
    if on_close is not None:
        panel.on_close = on_close
    return panel
