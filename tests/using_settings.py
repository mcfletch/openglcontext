#! /usr/bin/env python
'''=A settings page=

[using_settings.py-screen-0001.png Screenshot]

Settings a player changes and a game remembers.  Two pages here: the
engine's own rendering settings, which every context already has, and one
generated from a node of your own -- a label and a control per field,
written from what the fields declare rather than laid out by hand.

Keys:

    s       the game's own options, generated from a node
    r       the engine's rendering settings
    escape  put a page away
'''
from OpenGLContext import testingcontext
'''The pages are panels, pushed on the overlay stack every context has:
:doc:`Putting a panel on the screen <using_ui>`.'''
from OpenGLContext.ui import generate, settings
from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.session import SettingsSession
from OpenGLContext.ui.widgets import Button, Label, PRIMARY, Spacer
'''A settings node is an ordinary VRML97 node: typed fields with defaults,
which is where the validation, the defaults and the saving come from.'''
from vrml import field, node

from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)

BaseContext = testingcontext.getInteractive()


class GameOptions(node.Node):
    """What this game lets a player decide, as fields.

    ``UI_HINTS`` says how each one is presented: a range makes a number a
    slider, a list of options makes a string a cycle, and a label replaces
    the field name in front of the control.  A number with no range gets a
    field to type in, because a slider over an invented 0..1 is a wrong
    answer rather than a missing one.
    """

    PROTO = 'GameOptions'
    musicVolume = field.newField('musicVolume', 'SFFloat', 1, 0.7)
    mouseSpeed = field.newField('mouseSpeed', 'SFFloat', 1, 1.0)
    difficulty = field.newField('difficulty', 'SFString', 1, 'normal')
    invertY = field.newField('invertY', 'SFBool', 1, False)
    playerName = field.newField('playerName', 'SFString', 1, 'Player One')

    UI_HINTS = {
        'musicVolume': {'label': 'Music', 'minimum': 0.0, 'maximum': 1.0,
                        'step': 0.05},
        'mouseSpeed': {'label': 'Mouse speed', 'minimum': 0.1, 'maximum': 4.0,
                       'step': 0.1, 'suffix': 'x'},
        'difficulty': {'label': 'Difficulty',
                       'options': ['easy', 'normal', 'hard'],
                       'optionLabels': ['Easy', 'Normal', 'Hard']},
        'invertY': {'label': 'Invert Y'},
        'playerName': {'label': 'Name', 'maximumLength': 24},
    }


class TestContext(BaseContext):
    initialPosition = (0, 1.2, 6)

    def OnInit(self):
        self.options = GameOptions()
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.11, 0.13, 0.16)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.6)),
            Transform(children=[
                Shape(geometry=Box(size=(1.6, 1.6, 1.6)),
                      appearance=Appearance(material=Material(
                          diffuseColor=(0.35, 0.5, 0.7)))),
            ]),
        ])
        self.addEventHandler('keypress', name='s', function=self.OnOptions)
        self.addEventHandler('keypress', name='r', function=self.OnRendering)
        self.OnOptions()
        print(__doc__)

    def OnRendering(self, event=None):
        '''The engine's own screen, over whatever is running: shadows, image
        based lighting, bloom, instancing, the interface scale.  It edits the
        context's ``contextDefinition``, and ``on_apply`` is where a game
        decides what to do with the player's choices -- write them to a file,
        send them to a server, or nothing.'''
        settings.open_settings(self, on_apply=self.OnRenderingApplied)

    def OnRenderingApplied(self, session):
        '''``changed_fields`` names what moved, so a game saves the settings
        the player chose rather than freezing every default it shipped with.'''
        print('rendering settings changed: %s'
              % (', '.join(sorted(session.changed_fields())) or 'nothing',))

    def OnOptions(self, event=None):
        '''The game's own page.

        A ``SettingsSession`` holds a **copy** of the node.  Every control
        binds to that copy, so Cancel is simply throwing it away and Apply is
        copying it back -- neither the page nor the widgets need to know how
        to undo anything.'''
        if self.overlays.visible:
            return
        session = SettingsSession(self.options)
        '''``page_for`` builds the label-and-control grid from the draft's
        fields.  A field added to the node later appears on the page with no
        edit here, which is the point of generating it.'''
        page = generate.page_for(session.draft)
        apply = Button(text='Apply', role=PRIMARY,
                       on_activate=lambda widget: self.OnApply(session))
        cancel = Button(text='Cancel',
                        on_activate=lambda widget: self.popOverlay())
        self.pushOverlay(Panel(title='Options', modal=True, children=[
            Column(spacing=8, children=[
                Label(text='Written from the fields of GameOptions.',
                      wrap=True),
                page,
                Row(spacing=8, top=8, children=[Spacer(), cancel, apply]),
            ]),
        ]))

    def OnApply(self, session):
        '''``commit`` copies the draft's fields back into the live node.  Until
        it is called the game has not seen a single edit.'''
        changed = sorted(session.changed_fields())
        session.commit()
        self.popOverlay()
        print('applied: %s' % (', '.join(changed) or 'nothing',))
        print('music %.2f, difficulty %s, invert-Y %s, name %r' % (
            self.options.musicVolume, self.options.difficulty,
            bool(self.options.invertY), self.options.playerName,
        ))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
