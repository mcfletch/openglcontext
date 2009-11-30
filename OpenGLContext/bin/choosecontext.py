#! /usr/bin/env python
'''Choose Context class for use as default testing context
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from vrml.vrml97 import nodetypes
from OpenGLContext.events import mouseevents
from gettext import gettext as _

class ChoiceContext( BaseContext ):
    currentChoice = 0
    def loadChoices( self ):
        """See which contexts are available"""
        choices = [
            e.name for e in self.getContextTypes()
        ]
        return list(enumerate(choices))
    def nameForContextType( self, index ):
        if index > -1:
            return self.choices[index][1]
        return -1,None
    def setSavedText( self, index ):
        self.savedChoice = self.currentChoice
        self.savedText.string = [ _('Current: %s')%(
            self.nameForContextType( self.savedChoice )
        )]
        return self.savedChoice
    def OnInit( self ):
        """Setup callbacks and build geometry for rendering"""
        self.choices = self.loadChoices()
        print 'Available Contexts', self.choices
        current = self.getDefaultContextType()
        for i,name in self.choices:
            if name == current:
                self.currentChoice =  self.savedChoice = i
        fontStyle = FontStyle3D(
            size = 1,
            family = "SERIF",
            justify = "CENTER",
            renderBack = False,
            renderSides = False,
        )
        navFontStyle = FontStyle3D(
            size = 2,
            family = "SANS",
            justify = "CENTER",
            renderBack = False,
            renderSides = False,
        )
        backButton = Text(
            string = _('<'),
            fontStyle = navFontStyle,
        )
        forwardButton = Text(
            string = _('>'),
            fontStyle = navFontStyle,
        )
        saveButton = Text(
            string = _('Save'),
            fontStyle = fontStyle,
        )
        self.previousButton = MouseOver(
            choice = [
                Shape(
                    geometry = backButton,
                    appearance = Appearance(
                        material = Material( diffuseColor = (0,.5,0) ),
                    ),
                ),
                Shape(
                    geometry = backButton,
                    appearance = Appearance(
                        material = Material( diffuseColor = (0,1,0) ),
                    ),
                ),
            ],
            whichChoice = 0,
        )
        clicker = Shape(
            DEF = 'CLICKER',
            geometry = Box( size=(1,1,.001)),
            appearance = Appearance(
                material = Material( transparency=0 ),
            ),
        )
        self.nextButton = MouseOver(
            choice = [
                Group(
                    children = [
                        Shape(
                            geometry = forwardButton,
                            appearance = Appearance(
                                material = Material( diffuseColor = (0,.5,0) ),
                            ),
                        ),
                        clicker,
                    ],
                ),
                Group(
                    children = [
                        Shape(
                            geometry = forwardButton,
                            appearance = Appearance(
                                material = Material( diffuseColor = (1,1,0) ),
                            ),
                        ),
                        #clicker,
                    ],
                ),
            ],
            whichChoice = 0,
        )
        self.saveButton = MouseOver(
            choice = [
                Shape(
                    geometry = saveButton,
                    appearance = Appearance(
                        material = Material( diffuseColor = (0,.5,0) ),
                    ),
                ),
                Shape(
                    geometry = saveButton,
                    appearance = Appearance(
                        material = Material( diffuseColor = (0,1,0) ),
                    ),
                ),
            ],
            whichChoice = 0,
        )
        self.currentChoiceText = 		Text(
            string=[self.choices[self.currentChoice][1]],
            fontStyle = fontStyle,
        )
        self.savedText = 		Text(
            string='',
            fontStyle = fontStyle,
        )
        self.setSavedText( self.currentChoice )

        self.sg = sceneGraph(
            children = [
                SimpleBackground( color = (0,0,.25) ),
                Transform(
                    translation = (0,2,0),
                    children = [
                        Shape(
                            geometry = self.currentChoiceText,
                        ),
                    ],
                ),
                Transform(
                    translation = (-4,-1.5,0),
                    children = [
                        self.previousButton,
                    ],
                ),
                Transform(
                    translation = (4,-1.5,0),
                    children = [
                        self.nextButton,
                    ],
                ),
                Transform(
                    translation= (0,-1,0),
                    children = [self.saveButton],
                ),
                Transform(
                    translation= (0,-3,0),
                    children = [
                        Shape(
                            geometry = self.savedText,
                        ),
                    ],
                ),
            ],
        )
#        self.addEventHandler(
#            'mousebutton', 
#            node=self.previousButton, 
#            button = 0,
#            state = 0,
#            function = self.OnPrevious,
#        )
#        self.addEventHandler(
#            'mousebutton', 
#            node=self.nextButton, 
#            button = 0,
#            state = 0,
#            function = self.OnNext,
#        )
#        self.addEventHandler(
#            'mousebutton', 
#            node=self.saveButton, 
#            button = 0,
#            state = 0,
#            function = self.OnSave,
#        )
            
    def OnNext( self, event ):
        """Clicked the next button"""
        self.currentChoice += 1
        self.currentChoice = self.currentChoice % len( self.choices )
        self.currentChoiceText.string = self.choices[self.currentChoice][1]
        self.triggerRedraw(1)
    def OnPrevious( self, event ):
        """Clicked the previous button"""
        self.currentChoice -= 1
        self.currentChoice = self.currentChoice % len( self.choices )
        self.currentChoiceText.string = self.choices[self.currentChoice][1]
        self.triggerRedraw(1)
        
    def OnSave( self, event ):
        """Save current choice to the preferences file"""
        self.setDefaultContextType( self.choices[self.currentChoice][1] )
        self.setSavedText( self.currentChoice )
        self.triggerRedraw(1)

def main():
    """Mainloop redirecting to context's mainloop for operations"""
    return ChoiceContext.ContextMainLoop()

if __name__ == "__main__":
    main()