from OpenGLContext.browser.visual import *
import time

scene.visible = 1
sphere( color = (1,0,0), pos=(0,0,0) )
cone( color = (0,0,1), pos=(2,0,0), length=2 )
cylinder( color = (0,1,0), pos=(-2,0,0), length=4)
box( color = (.5,.5,.5), pos=(0,-.5,0), size=(6,1,4))
curve(
	pos=[
		(0,0,4),
		(1,0,4),
		(1,1,4),
		(-1,1,4),
		(-1,-1,4),
		(1,-1,4),
	],
	radius=3,
)
curve(
	pos=[
		(3,0,4),
		(4,0,4),
		(4,1,4),
		(2,1,4),
		(2,-1,4),
		(4,-1,4),
	],
	color = [
		(0,0,0),
		(1,0,0),
		(0,1,0),
		(0,0,1),
		(1,1,0),
		(0,1,1),
	],
	radius=0,
)

scene._context.triggerRedraw(1)
