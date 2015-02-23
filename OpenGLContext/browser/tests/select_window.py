"""This should cause a window to open"""
from OpenGLContext.browser import visual
import time

print("""showing the first window""")
visual.scene.visible = 1
print("""creating the second window""")
second = visual.display ( x=350,y=0, DEF="Second Window")
second.visible = 1
visual.select( second )
assert visual.scene is second, """select didn't set scene global in visual module"""
assert len(visual.scenes) == 2, """Didn't get both scenes added to list of scenes %s"""%( visual.scenes,)
for scene in visual.scenes[:]:
    print('trying to close', scene)
    scene.visible = 0
print('success')