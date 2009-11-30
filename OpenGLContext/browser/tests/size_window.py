"""This should cause a window to open"""
from OpenGLContext.browser.visual import *
import time, os
from OpenGLContext import browser

scene.visible = 1
sphere()
##scene._context.loadUrl( os.path.join(os.path.dirname(browser.__file__),'default_world.wrl') )

for x in range(300,600):
    scene.width = x
    time.sleep( .01 )
for y in range(300,600):
    scene.height = y
    time.sleep( .01 )

scene.visible = 0