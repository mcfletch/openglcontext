#! /usr/bin/env python
'''=A console over the frame=

[using_console.py-screen-0001.png Screenshot]

A console is a scrollback, an input line, and a table of commands the line
is read against.  It is what a game gives a developer -- and, often enough,
a player -- for spawning something, flipping a setting, or reading the
warnings the engine logged while the level was loading.

Keys:

    `                open and close the console
    up, down         walk back through what was typed
    escape           put it away

Type `help` in it for the commands this demo registers.
'''
from OpenGLContext import testingcontext
'''The console is a ``Panel`` like any other, so a context gains it the same
way: :doc:`Putting a panel on the screen <using_ui>` is the stack every
context has.'''
from OpenGLContext.ui import console
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)

import logging

BaseContext = testingcontext.getInteractive()


class TestContext(BaseContext):
    initialPosition = (0, 1.2, 6)

    def OnInit(self):
        '''Something to act on: a box the console's commands will colour and
        move.'''
        self.box = Transform(children=[
            Shape(geometry=Box(size=(1.6, 1.6, 1.6)),
                  appearance=Appearance(material=Material(
                      diffuseColor=(0.7, 0.45, 0.3)))),
        ])
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.11, 0.12, 0.15)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.6)),
            self.box,
        ])
        '''A ``CommandRegistry`` is the table a typed line is looked up in.
        Each entry is a name, a function and a line of help; the function is
        called with the panel and the words that followed the name, and what
        it returns is printed.  ``help`` and ``clear`` are there already.'''
        self.commands = console.CommandRegistry()
        self.commands.add('colour', self.cmd_colour,
                          'colour R G B -- set the box colour, 0..1 each')
        self.commands.add('spin', self.cmd_spin,
                          'spin DEGREES -- turn the box about Y')
        self.commands.add('warn', self.cmd_warn,
                          'warn TEXT -- log a warning, to show it arriving')
        self.panel = None
        self.addEventHandler('keypress', name='`', function=self.OnConsole)
        '''It opens with the console up, which is where the reader wants it.'''
        self.OnConsole()
        print(__doc__)

    def OnConsole(self, event=None):
        '''One panel, kept and pushed again rather than rebuilt: the
        scrollback is the thing a reader came back for.'''
        if self.overlays.visible:
            self.popOverlay()
            return
        if self.panel is None:
            self.panel = console.console_panel(registry=self.commands)
            '''``ConsoleLogHandler`` puts Python logging on the screen.  In a
            packaged game the engine's warnings -- a texture that would not
            load, a shader that fell back -- go somewhere nobody looks; with
            the handler attached they arrive in the scrollback.'''
            logging.getLogger('OpenGLContext').addHandler(
                console.ConsoleLogHandler(self.panel))
            self.panel.write('Type help for the commands this demo adds.')
            self.run('help')
            self.run('colour 0.2 0.55 0.9')
        self.pushOverlay(self.panel)

    def run(self, line):
        '''Running a line without anyone typing it: the registry is dispatched
        against directly, and the echo and the answer are written the way the
        input line writes them.  A key binding, a startup file or a test does
        the same thing.'''
        self.panel.write(console.PROMPT + line)
        answer = self.commands.dispatch(self.panel, line)
        if answer:
            self.panel.write(answer)

    '''A command is an ordinary method.  It is handed the panel, so it can
    write more than it returns, and the words as they were typed -- text,
    which is why each one checks what it was given.'''

    def cmd_colour(self, panel, *words):
        if len(words) != 3:
            return 'colour wants three numbers, 0..1 each'
        try:
            colour = tuple(float(word) for word in words)
        except ValueError:
            return 'colour wants numbers'
        self.box.children[0].appearance.material.diffuseColor = colour
        self.triggerRedraw(1)
        return 'box is now %.2f %.2f %.2f' % colour

    def cmd_spin(self, panel, *words):
        try:
            degrees = float(words[0]) if words else 45.0
        except ValueError:
            return 'spin wants a number of degrees'
        from math import radians
        self.box.rotation = (0, 1, 0, radians(degrees))
        self.triggerRedraw(1)
        return 'turned to %g degrees' % (degrees,)

    def cmd_warn(self, panel, *words):
        '''Nothing is written to the console here: the warning goes to
        logging, and the handler attached above is what carries it in.'''
        logging.getLogger('OpenGLContext').warning(
            ' '.join(words) or 'a warning with nothing to say')
        return None


if __name__ == "__main__":
    TestContext.ContextMainLoop()
