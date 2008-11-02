"""This should cause a window to open"""
from OpenGLContext.browser.visual import *
import time

scene.visible = 1
scene._context.loadUrl( "z:\\wrls\\figure.wrl" )

scene.title = "Moving right"
for x in range(300):
	scene.x = x
	time.sleep( .001 )
scene.title = "Moving down"
for y in range(300):
	scene.y = y
	time.sleep( .001 )

scene.visible = 0
