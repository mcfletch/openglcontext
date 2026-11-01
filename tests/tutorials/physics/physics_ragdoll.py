#! /usr/bin/env python
'''=Physics: a ragdoll knocked down=

[physics_ragdoll.py-screen-0001.png Screenshot]

The yard of ``oglc-ragdoll``: Cesium Man from the Khronos sample models
(CC-BY 4.0, Cesium) walks on a marble floor with a ragdoll for a skeleton.
Powered, motors turn each bone towards the walk's pose and a spring holds
the pelvis up, so a blow makes him stagger and recover.  Limp, the motors let
go and he falls.

The script opens on a scene already played: a blow he recovers from, then a
heavier one with the ragdoll going limp over a third of a second, so the
first frame shows him lying on the floor.  The keys the demo prints strike
him again and stand him back up.
'''
from OpenGLContext.bin.ragdoll_demo import MODEL, RagdollYard, definition
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.loaders.gltf import sample_model_url

#: The opening, in seconds, played in steps of what length before the first frame.
WALK = 0.8
RECOVER = 1.0
FALL = 2.0
STEP = 1.0 / 60.0


class TestContext(BaseContext):
    '''The world steps in the frame (``definition()``), so the opening is the
    same on every run.'''
    renderer = 'pbr'
    initialPosition = (1.6, 1.2, 2.6)
    initialOrientation = (-0.25, 1, 0.1, 0.55)
    contextDefinition = ContextDefinition(physics=definition())

    def OnInit(self):
        '''``RagdollYard`` builds the floor and the figure.  Its
        ``RagdollFigure(physics, model, mode='powered', root_force=...)`` is
        the call to read: ``RagdollRig.from_model`` chooses the bones from
        the model's humanoid bone map and sizes each capsule from the skin
        weighted to it, and the figure sends the walk's pose to the ragdoll
        each frame and writes the bones back into the skin.'''
        model = CharacterModel.load(sample_model_url(MODEL))
        self.yard = RagdollYard(self.physics, model)
        self.sg = self.yard.scene()
        '''``animate`` calls the yard's ``update(dt)`` once a frame: the
        figure's ``update`` and ``draw``.'''
        self.animate(self.yard.update)
        for key, handler in (('h', self.yard.strike), ('k', self.yard.knock_down),
                             ('g', self.OnGetUp), ('p', self.yard.toggle_power)):
            self.addEventHandler('keypress', name=key,
                                 function=handler)
        self.opening()
        print(__doc__)

    def opening(self):
        '''A blow on the chest is ``ragdoll.hit(bone, impulse)``.  Knocking
        him down is a heavier one and ``figure.set_mode('limp', 0.3)``, with
        ``figure.following`` false so the walk no longer leads the bones.'''
        self.play(WALK)
        self.yard.strike()
        self.play(RECOVER)
        self.yard.knock_down()
        self.play(FALL)

    def play(self, seconds):
        for _ in range(round(seconds / STEP)):
            self.yard.update(STEP)
            self.physics.frame(STEP)
    
    def OnGetUp(self, event):
        self.yard.get_up()
        self.triggerRedraw(True)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
