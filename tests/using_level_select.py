#! /usr/bin/env python
'''=Choosing a level=

[using_level_select.py-screen-0001.png Screenshot]

A level carousel lets the user select a level by name and image, so that
they have some indication of the nature and quality of the level they will
download.  `OpenGLContext.ui.gallery.Carousel` is the widget: a band of
pictures with their names underneath, rolled by the arrows, the keyboard,
or a click on any picture already on screen.

Keys and mouse:

    left, right   roll the band
    return        load what is in the middle
    l             open the chooser again
    escape        put it away
'''
import os
import tempfile

from OpenGLContext import testingcontext
'''The chooser is a panel like any other -- :doc:`Putting a panel on the
screen <using_ui>` -- and the carousel is a widget in it.'''
from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.ui.gallery import Carousel
from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Button, Label, PRIMARY, Spacer
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)

BaseContext = testingcontext.getInteractive()

#: The levels this game offers: the name it is loaded by, the name a player
#: reads, and the colour standing in for the world it loads.
LEVELS = [
    ('dock', 'The Dock', (0.30, 0.45, 0.65)),
    ('foundry', 'The Foundry', (0.70, 0.40, 0.25)),
    ('orchard', 'The Orchard', (0.35, 0.60, 0.35)),
    ('vault', 'The Vault', (0.45, 0.40, 0.60)),
    ('observatory', 'The Observatory', (0.55, 0.50, 0.70)),
]


class TestContext(OverlayMixin, BaseContext):
    initialPosition = (0, 1.2, 6)

    def OnInit(self):
        '''A shot per level.  A game ships these as screenshots of each map;
        this one draws them at start-up so there is nothing binary to keep
        beside the demo.'''
        self.shots = level_shots()
        self.level = LEVELS[0][0]
        self.block = Transform(children=[
            Shape(geometry=Box(size=(2, 2, 2)),
                  appearance=Appearance(material=Material(
                      diffuseColor=LEVELS[0][2]))),
        ])
        self.sky = Background(skyColor=[(0.11, 0.12, 0.15)])
        self.sg = sceneGraph(children=[
            self.sky,
            DirectionalLight(direction=(-0.4, -0.7, -0.6)),
            self.block,
        ])
        self.addEventHandler('keypress', name='l', function=self.OnChoose)
        self.OnChoose()
        print(__doc__)

    def OnChoose(self, event=None):
        '''The carousel's fields are three lists of the same length: what each
        option *is*, what it is called, and where its picture is.  ``value`` is
        the option in the middle, which is what ``read()`` answers and what
        ``on_change`` is called for.'''
        if self.overlays.visible:
            return
        self.carousel = Carousel(
            options=[name for name, _label, _colour in LEVELS],
            optionLabels=[label for _name, label, _colour in LEVELS],
            optionImages=self.shots,
            value=self.level,
            visibleCount=3,
            on_change=self.OnRolled,
        )
        play = Button(text='Play', role=PRIMARY, on_activate=self.OnPlay)
        self.pushOverlay(Panel(title='Choose a level', modal=True, children=[
            Column(spacing=8, children=[
                Label(text='Left and right roll the band.'),
                self.carousel,
                Row(spacing=8, top=8, children=[Spacer(), play]),
            ]),
        ]))

    def OnRolled(self, widget):
        """Rolling the band is not choosing: it only says what is in front."""
        print('looking at %s' % (widget.read(),))

    def OnPlay(self, widget):
        '''What a game does here is load the map the carousel is showing.  This
        one paints the block and the sky in the level's colours, which is the
        same shape of code with the loading taken out.'''
        self.level = self.carousel.read()
        colour = dict((name, colour) for name, _label, colour in LEVELS)[self.level]
        self.block.children[0].appearance.material.diffuseColor = colour
        self.sky.skyColor = [tuple(part * 0.25 for part in colour)]
        self.popOverlay()
        self.triggerRedraw(1)
        print('loading %s' % (self.level,))


def level_shots():
    """One picture per level, drawn into a temporary directory.

    Returns the paths, in the order :data:`LEVELS` gives them -- which is what
    ``optionImages`` wants, since it is read against ``options`` by position.
    """
    from PIL import Image, ImageDraw
    directory = tempfile.mkdtemp(prefix='oglc-levels-')
    paths = []
    for name, _label, colour in LEVELS:
        image = Image.new('RGB', (192, 108),
                          tuple(int(part * 255) for part in colour))
        draw = ImageDraw.Draw(image)
        draw.rectangle([8, 8, 183, 99], outline=(255, 255, 255), width=2)
        draw.line([(8, 72), (183, 72)], fill=(255, 255, 255), width=1)
        path = os.path.join(directory, '%s.png' % (name,))
        image.save(path)
        paths.append(path)
    return paths


if __name__ == "__main__":
    TestContext.ContextMainLoop()
