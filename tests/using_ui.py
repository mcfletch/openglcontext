#! /usr/bin/env python
'''=Putting a panel on the screen=

[using_ui.py-screen-0001.png Screenshot]

A settings screen over a running world, built out of widgets: a switch, a
slider and a button.  The panel takes the pointer and the keyboard while it is
up, and the world carries on rendering behind it.

Screen furniture that must not take the input -- a reticule, a health bar, a
message queue -- is a HUD layer instead: :doc:`HUD widgets <hud_demo>`.  The
ready-made screens (the rendering settings, a yes/no question, a console) are
in :doc:`the overlay UI page </overlayui>`.

Keys:
    u        show the panel again
    escape   put it away
'''
import math

from OpenGLContext import testingcontext
'''``OverlayMixin`` gives a context the overlay stack, the input routing and
the drawing.  It is mixed in *ahead of* the context class so its event
handling runs before navigation gets the same click.'''
from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import (
    Button, Label, PRIMARY, Slider, Spacer, Toggle,
)
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)

BaseContext = testingcontext.getInteractive()

#: Seconds for one full turn at the slider's maximum.
PERIOD = 4.0


class TestContext(OverlayMixin, BaseContext):
    initialPosition = (0, 1.5, 6)

    def OnInit(self):
        '''An ordinary scene: something to look at while the panel is over
        it.'''
        self.spinner = Transform(children=[
            Shape(geometry=Box(size=(1.6, 1.6, 1.6)),
                  appearance=Appearance(material=Material(
                      diffuseColor=(0.75, 0.45, 0.25)))),
        ])
        self.light = DirectionalLight(direction=(-0.4, -0.7, -0.6))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.12, 0.14, 0.17)]),
            self.light,
            self.spinner,
        ])
        self.speed = 0.5
        self.spinning = True
        self.timer = Timer(duration=PERIOD, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.timer.register(self)
        self.timer.start()
        '''A letter key can be bound on ``keypress``, which is character
        input.  A function key produces no character, so ``<F10>`` and its
        like are bound on ``keyboard`` instead.  Either way the handler has to
        be a bound method of something that lives: handlers are held weakly,
        and a lambda passed inline is collected as soon as the call returns.'''
        self.addEventHandler('keypress', name='u', function=self.OnShow)
        self.OnShow()
        print(__doc__)

    def OnShow(self, event=None):
        '''``pushOverlay`` puts a panel on screen and gives it the input;
        ``popOverlay`` takes it off again, and so does Escape.'''
        if not self.overlays.visible:
            self.pushOverlay(self.panel())

    def panel(self):
        '''A panel is a title and a tree of widgets.  ``Column`` and ``Row``
        lay their children out; the panel sizes itself to what is in it and
        places itself in the window.

        A widget carries the value it edits, and says what to do when it
        changes.  ``on_change`` is called as the value moves, ``on_activate``
        when a button is pressed.'''
        spin = Toggle(text='Spin', value=self.spinning,
                      on_change=self.OnSpin)
        '''A slider draws its track and its number.  The name of the thing it
        sets is a ``Label`` beside it, which is how the generated settings
        pages lay a control out as well.'''
        speed = Row(spacing=8, children=[Label(text='Speed'),
                                         Slider(value=self.speed,
                                                minimum=0.0, maximum=1.0,
                                                step=0.05,
                                                on_change=self.OnSpeed)])
        '''A widget given a ``target`` node and a ``fieldName`` edits that
        field directly, with no callback and no second copy of the value:
        this switch *is* the light's ``on`` field, and anything else watching
        that field hears about the change as usual.'''
        light = Toggle(text='Light', target=self.light, fieldName='on')
        close = Button(text='Close', role=PRIMARY, on_activate=self.OnClose)
        return Panel(title='Options', children=[
            Column(spacing=6, children=[
                Label(text='A panel over a live world.', wrap=True),
                spin,
                speed,
                light,
                Row(spacing=8, top=8, children=[Spacer(), close]),
            ]),
        ])

    def OnSpin(self, widget):
        self.spinning = widget.read()

    def OnSpeed(self, widget):
        self.speed = widget.read()

    def OnClose(self, widget):
        self.popOverlay()

    def OnFraction(self, event):
        '''The world goes on turning while the panel is up: a panel takes the
        input, not the frame.'''
        if self.spinning:
            self.turn = getattr(self, 'turn', 0.0) + self.speed * 0.05
            self.spinner.rotation = (0, 1, 0, self.turn * 2.0 * math.pi)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
