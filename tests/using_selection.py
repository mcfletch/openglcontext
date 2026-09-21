#! /usr/bin/env python
'''=Selecting and dragging=

[using_selection.py-screen-0001.png Screenshot]

Clicking a thing in the world, being told about it, and moving it.  Three
pieces: a callback bound *to a node*, so the press arrives already knowing
what it hit; the pick, which is what answers that question; and
`OpenGLContext.edit.gizmo.TranslationGizmo`, the tri-axis handle a drag is
held to one axis of.

Keys and mouse:

    click a box      select it; the handle appears on it
    drag an arm      move the box along that axis
    click the floor  put the handle away
    escape           abandon a drag part-way, or deselect
    r                reset the boxes
'''
from OpenGLContext import testingcontext
'''The handle is an engine part rather than a demo's own: ``edit`` is the
authoring toolkit -- tool modes, plan views, handles -- that the editors are
built out of.'''
from OpenGLContext.edit.gizmo import TranslationGizmo
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)

BaseContext = testingcontext.getInteractive()

#: Where the boxes start, and what colour each one is.
BOXES = [
    ((-2.2, 0.5, 0.0), (0.75, 0.35, 0.3)),
    ((0.0, 0.5, 0.0), (0.35, 0.6, 0.4)),
    ((2.2, 0.5, 0.0), (0.35, 0.45, 0.75)),
]
#: How long an arm of the handle is, in the same units as the scene.
GIZMO_SIZE = 1.4
#: What a selected box is tinted with, so the selection reads at a glance.
SELECTED = (1.0, 0.85, 0.35)


class TestContext(BaseContext):
    initialPosition = (0, 3.2, 9)
    initialOrientation = (-1, 0, 0, 0.3)

    def OnInit(self):
        self.build()
        '''One handle serves every box: only one thing is being moved at a
        time, so it is attached where the selection is rather than one being
        made per box.'''
        self.gizmo = TranslationGizmo(size=GIZMO_SIZE)
        self.selection = None
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.12, 0.14, 0.17)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.6)),
            self.floor,
        ] + self.boxes + [self.gizmo.node])

        '''A handler bound with ``node=`` fires only for presses on that node
        or on something under it.  The pick has already worked out what the
        pointer is over, so the callback does not have to: it is told which
        box, the way a button is told it was pressed.'''
        for box in self.boxes:
            self.addEventHandler('mousebutton', button=0, state=1, node=box,
                                 function=self.OnBox)
        '''A handler bound with no node takes what nothing else claimed -- a
        press on the floor, or on the background.  The handle's own arms are
        checked here first, because grabbing an arm is the start of a drag
        rather than a selection.'''
        self.addEventHandler('mousebutton', button=0, state=1,
                             function=self.OnPress)
        self.addEventHandler('mousebutton', button=0, state=0,
                             function=self.OnRelease)
        '''A drag is a mouse move with the button held.'''
        self.addEventHandler('mousemove', buttons=(0,), function=self.OnDrag)
        self.addEventHandler('keypress', name='<escape>', function=self.OnCancel)
        self.addEventHandler('keypress', name='r', function=self.OnReset)
        '''It opens with the middle box selected, so the handle is on screen
        before anything is clicked.'''
        self.select(self.boxes[1])
        print(__doc__)

    def build(self):
        """The boxes to pick, and a floor to click on to deselect."""
        self.boxes = []
        for position, colour in BOXES:
            self.boxes.append(Transform(translation=position, children=[
                Shape(geometry=Box(size=(1, 1, 1)),
                      appearance=Appearance(material=Material(
                          diffuseColor=colour))),
            ]))
        self.floor = Transform(translation=(0, -0.05, 0), children=[
            Shape(geometry=Box(size=(12, 0.1, 8)),
                  appearance=Appearance(material=Material(
                      diffuseColor=(0.2, 0.22, 0.25)))),
        ])

    # -- selection -------------------------------------------------------
    def OnBox(self, event):
        '''What the callback is handed: the event, and through it the pick.
        ``event.getObjectPaths()`` is every node path under the pointer,
        nearest first, and ``event.unproject()`` is where in the world the
        pointer landed.  The node itself comes from the binding.'''
        for box in self.boxes:
            if any(box in path for path in event.getObjectPaths()):
                self.select(box)
                return

    def OnPress(self, event):
        '''A press that reached here hit no box.  The handle is asked whether
        one of its arms was grabbed -- its arms stand in front of whatever they
        are moving, so a press on an arm is never a press on the thing behind
        it -- and anything else puts the handle away.'''
        if self.gizmo.axis_for(event.getObjectPaths()) is not None:
            self.gizmo.press(event)
            return
        self.select(None)

    def select(self, box):
        """Work on one box, or on none."""
        if self.selection is not None:
            self.material(self.selection).emissiveColor = (0, 0, 0)
        self.selection = box
        if box is None:
            self.gizmo.detach()
        else:
            self.material(box).emissiveColor = SELECTED
            '''``attach`` puts the handle at a point in the coordinates of the
            group it is in.  The boxes and the handle are both in the root
            group, so a box's ``translation`` is that point.'''
            self.gizmo.attach(box.translation)
            print('selected the box at %.1f, %.1f, %.1f' % tuple(box.translation))
        self.triggerRedraw(1)

    # -- dragging --------------------------------------------------------
    def OnDrag(self, event):
        '''``drag`` answers where the grabbed arm has taken the point, or None
        for a move that is not part of a drag -- no arm held, or the pointer
        edge-on to the one that is, which says nothing about where along it to
        go.  Writing the answer onto the node is the whole of moving it.'''
        moved = self.gizmo.drag(event)
        if moved is None or self.selection is None:
            return
        self.selection.translation = tuple(moved)
        self.triggerRedraw(1)

    def OnRelease(self, event):
        """Let go of the arm, leaving the box where the drag left it."""
        self.gizmo.release()

    def OnCancel(self, event):
        '''Escape abandons a drag part-way: ``cancel`` answers where the point
        was before it began, which is put back.  With no drag going on it
        deselects instead.'''
        if self.gizmo.dragging is not None and self.selection is not None:
            self.selection.translation = tuple(self.gizmo.cancel())
            self.triggerRedraw(1)
        else:
            self.select(None)

    def OnReset(self, event=None):
        self.select(None)
        for box, (position, _colour) in zip(self.boxes, BOXES):
            box.translation = position
        self.triggerRedraw(1)

    @staticmethod
    def material(box):
        """The material of the shape under a box's transform."""
        return box.children[0].appearance.material


if __name__ == "__main__":
    TestContext.ContextMainLoop()
