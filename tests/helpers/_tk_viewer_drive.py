#! /usr/bin/env python3
"""Drive one thing the Tk viewer demo does, and report what happened.

Run as a subprocess by ``tests/unit/test_demo_viewers.py``: each named step
builds the demo's real window with a real GL context, does the one thing, prints
what came of it and stops.  A subprocess per step because a Tk application is a
process with one interpreter in it, and the steps that quit really do quit.

Usage:  _tk_viewer_drive.py <step> [<step> ...]
"""
import os
import sys
import time

os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'

from vrml import protofunctions                                 # noqa: E402

from OpenGLContext.demos.tk_viewer import (                     # noqa: E402
    ViewerApplication, pathOf, rowId,
)
from OpenGLContext.scenegraph import basenodes                  # noqa: E402
from OpenGLContext.testing.paths import tests_root              # noqa: E402

MODEL = str(tests_root(__file__) / 'wrls' / 'instanced_lattice.gltf')

#: How long to give an asynchronous load before calling it a failure, in
#: seconds.  Generous: a software rasteriser on a busy machine is what this has
#: to finish under.  Counted in seconds rather than in frames, because an
#: iteration with nothing to draw returns at once and a thousand of them are no
#: time at all for a worker thread to load anything in.
LOAD_SECONDS = 60.0


def say(name, value):
    print('%s %s' % (name, value), flush=True)


def built(source=None):
    """The demo application, with its first frame drawn"""
    application = ViewerApplication(source=source)
    application.onFrame()
    return application


def loaded(application):
    """Pump frames until the scene the worker thread is loading is on screen"""
    deadline = time.time() + LOAD_SECONDS
    while time.time() < deadline:
        application.onFrame()
        if application.shownScene is not None and application.outline.rows:
            return True
        time.sleep(0.01)
    return False


def windowGone(application):
    """Whether the host window has gone

    Destroying the root destroys the Tcl interpreter with it, so asking a
    destroyed application about itself raises rather than answering.
    """
    try:
        return not application.root.winfo_exists()
    except Exception:
        return True


def treeLabels(application):
    """What the Treeview is showing, top to bottom"""
    def below(item):
        found = []
        for child in application.tree.get_children(item):
            found.append(application.tree.item(child, 'text'))
            found.extend(below(child))
        return found
    return below('')


# -- the steps --------------------------------------------------------------
def tree():
    """The scene reaches the tree control"""
    application = built(MODEL)
    say('LOADED', loaded(application))
    labels = treeLabels(application)
    say('ROWS', len(labels))
    say('HASROOT', 'sceneGraph' in labels)
    say('MATCHES', len(application.outline.rows) == len([
        label for label in labels if label != '…']))


def expanding():
    """Opening a row in the tree opens it in the model, and shows more"""
    application = built(MODEL)
    loaded(application)
    before = len(application.outline.rows)
    application.tree.focus(rowId((0,)))
    application.onOpenRow()
    say('EXPANDED', (0,) in application.outline.expanded)
    say('GREW', len(application.outline.rows) > before)
    application.onCloseRow()
    say('COLLAPSED', (0,) not in application.outline.expanded)
    say('BACK', len(application.outline.rows) == before)


def selecting():
    """Selecting a row names the node, and the panel says what it is"""
    application = built(MODEL)
    loaded(application)
    application.tree.selection_set(rowId((0,)))
    application.onSelect()
    say('SELECTED', application.outline.selected is not None)
    say('WATCHING', application.watching is application.outline.selected)
    say('DETAIL', application.detail.get('1.0', 'end').strip().splitlines()[0])


def watching():
    """A change to the selected node reaches the panel through pydispatcher"""
    application = built()
    application.outline.root = basenodes.sceneGraph(
        children=[basenodes.Transform(DEF='hub')])
    application.fillTree()
    application.tree.selection_set(rowId((0,)))
    application.onSelect()
    node = application.outline.selected
    node.translation = (3, 4, 5)
    application.root.update()               # run the after_idle the change asked for
    say('TOLD', '[3. 4. 5.]' in application.detail.get('1.0', 'end'))
    protofunctions.defName(node, 'renamed')
    application.onFrame()
    say('RENAMED', 'renamed' in treeLabels(application))


def opening():
    """The File menu's own handler opens a scene through the engine"""
    application = built()
    say('EMPTY', application.context.source is None)
    application.open(MODEL)
    say('OPENED', application.context.source == MODEL)
    say('LOADED', loaded(application))
    say('STATUS', os.path.basename(application.status.cget('text')))


def quitting():
    """Quitting from the host's menu takes the window and the GL with it"""
    application = built(MODEL)
    loaded(application)
    application.onQuit()
    say('RELEASED', application.context.frame is None)
    say('WATCHING', application.watching is None)
    say('OUTLINE', application.outline.rows == [])
    say('WINDOW', windowGone(application))


def viewfinished():
    """A view that quits itself takes the host's window down with it"""
    application = built(MODEL)
    application.context.OnQuit()
    application.onFrame()
    say('WINDOW', windowGone(application))


STEPS = {
    'tree': tree,
    'expanding': expanding,
    'selecting': selecting,
    'watching': watching,
    'opening': opening,
    'quitting': quitting,
    'viewfinished': viewfinished,
}


if __name__ == '__main__':
    assert pathOf(rowId((1, 2))) == (1, 2), 'the row ids do not round-trip'
    for name in sys.argv[1:]:
        STEPS[name]()
    say('DONE', '')
