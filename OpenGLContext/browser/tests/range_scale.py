"""Test range and scale"""
from OpenGLContext.browser.visual import *
import time
from OpenGLContext.arrays import arange

scene.visible = 1
sphere()
##scene._context.loadUrl( "z:\\wrls\\figure.wrl" )


print('playing with range')
for x in range(-20,20):
    scene.range = x
    time.sleep( .001 )
print('playing with scale')
for x in arange(2.0,-2.0,-.01):
    scene.scale = x
    time.sleep( .001 )

scene.visible = 0
print('exit')