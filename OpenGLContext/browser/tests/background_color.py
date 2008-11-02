"""This should cause a window to open"""
from OpenGLContext.browser.visual import *
import time, os
from OpenGLContext import browser

# this has to pause until the screen is actually visible...
scene.visible = 1
##scene._context.loadUrl( os.path.join(os.path.dirname(browser.__file__),'default_world.wrl') )

for x in arange(0.0,1.0,0.01):
	scene.background = (x,0,0)
	time.sleep( .01 )
for x in arange(0.0,1.0,0.01):
	scene.background = (1.0-x,x,0)
	time.sleep( .01 )
for x in arange(0.0,1.0,0.01):
	scene.background = (0,1.0-x,x)
	time.sleep( .01 )

scene.visible = 0
