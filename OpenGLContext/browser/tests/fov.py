from OpenGLContext.browser.visual import *
import time
from OpenGLContext.arrays import arange

scene.visible = 1
sphere()
##scene._context.loadUrl( "z:\\wrls\\figure.wrl" )


for x in arange(0.01,3.14159, 0.01):
    scene.fov = x
    time.sleep( .001 )

scene.visible = 0
print('exit')