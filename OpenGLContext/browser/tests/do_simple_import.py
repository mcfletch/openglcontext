"""This should cause a window to open"""
from OpenGLContext.browser import visual

assert hasattr(visual, "scene"), """No display context named "scene" created on import of visual"""

visual.scene.visible = 1
assert visual.scene.visible, """Visible field not available, or didn't take true value"""
visual.scene.visible = 0
print 'Finished, no errors, should exit now.'