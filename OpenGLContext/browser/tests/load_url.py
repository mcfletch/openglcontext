"""This should cause a window to open"""
from OpenGLContext.browser.visual import *
import os
path = os.path.join(os.path.dirname(__file__), '..', 'default_world.wrl')

scene.visible = 1
scene._context.loadUrl( path )
##
##b = box()
