#! /usr/bin/env python
'''=A character's footsteps follow the surface=

[character_footsteps.py-screen-0001.png Screenshot]

A foot that lands plays the footstep of the material under it. The land of
:doc:`character_run` is grass, and a slab of stone lies across the way: the
fox's steps change as it crosses the slab and change back as it leaves it.
'''
from character_run import FOX, LAND, LandContext
from OpenGLContext.audio import sounds
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.scenegraph import surfaces

'''Two sounds made on the spot: a soft rustle for grass and a short hard click
for stone. A game names the files of its footsteps.'''
RUSTLE = sounds.noise(0.12, amplitude=0.25, seed=3)
CLICK = sounds.impact(0.08, decay=60.0, seed=5)
#: Where the slab lies: centre in x and z, and its size in metres.
SLAB_AT = (0.5, -9.0)
SLAB_SIZE = (4.0, 0.2, 5.0)


class TestContext(LandContext):
    def OnInit(self):
        super().OnInit()
        '''``footstep=`` on a material is the clip a foot lands with. The
        materials are defined before the bodies that take them.'''
        self.physics.materials.define('grass', friction=0.8, footstep=RUSTLE)
        self.physics.materials.define('stone', friction=0.6, footstep=CLICK)
        '''The ground is grass, and a block of stone, drawn and collided, is
        the slab. A foot is on whichever the ray from the fox's feet meets
        first: the slab, where the fox is over it.'''
        self.physics.add_ground(LAND, material='grass')
        height = float(LAND.sample(*SLAB_AT)) + 0.05
        stone = surfaces.pbr_material(surfaces.marble(256), roughness=0.3)
        slab = surfaces.shape(
            surfaces.block(SLAB_SIZE), stone,
            translation=(SLAB_AT[0], height, SLAB_AT[1]))
        self.sg.children.append(slab)
        self.slab = self.physics.add_static(slab, proxy='box', material='stone')
        self.hero = self.physics.add_character(
            model=sample_model_url('Fox'), animations=FOX,
            position=(0, 0.2, 0), parent=self.sg)
        self.follow(self.hero)
        '''A script that wants to know of each foot, to leave a print or
        raise dust, listens for ``'footstep'``: the ``Footstep`` it is given
        says which foot, how far through the stride, where, and the name of the
        material under it.'''
        self.hero.addEventHandler('footstep', function=self.OnFootstep)
        self.steps = []

    def OnFootstep(self, step):
        self.steps.append(step.material)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
