"""This should cause a window to open"""
from OpenGLContext.browser.visual import *
import time

scene.visible = 1
sphere()
##scene._context.loadUrl( "z:\\wrls\\figure.wrl" )

for x in range(-100,100):
    scene.autocenter = 0
    scene.center = (x/20.0,0,0)
    time.sleep( .001 )

scene.visible = 0
print('exit')