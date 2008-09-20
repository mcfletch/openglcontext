"""This should cause a window to open"""
from OpenGLContext.browser.visual import *
import time

print """showing the first window"""
scene.visible = 1
##scene._context.loadUrl( "z:\\wrls\\figure.wrl" )
sphere( color=(0,0,1))
scene._context.triggerRedraw(1 )

print """creating the second window"""
second = display ( x=350,y=0)
sphere( display = second )
second.visible = 1
print """Second widow created"""


print """Doing animation in the second window"""
for x in range(-100,100):
	second.autocenter = 0
	second.center = (x/20.0,0,0)
	second.range = x/5.0
	scene.autocenter = 0
	scene.center = (0,x/20.0,0)
	scene.range = x/5.0
	time.sleep( .01 )

scene.visible = 0
second.visible = 0
print 'exit'