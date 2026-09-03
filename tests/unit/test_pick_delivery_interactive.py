"""A click is delivered to an application that renders only on demand.

An asynchronous pick is read back during a render later than the one that
queued it. An editor or a viewer has nothing to animate while that is in
flight, so unless the pass asks for the frame its own readback needs, the click
waits for whatever unrelated event happens to ask for one -- and the menu it
opened appears when the pointer next moves, seconds later.
"""

import pytest

from OpenGLContext.testing.display import display_available
from OpenGLContext.testing.paths import tests_root

TESTS_DIR = tests_root(__file__)
TARGET = TESTS_DIR / "helpers" / "ondemand_click_target.py"
CLICK_MARKER = "PICKED_CLICK_DISPATCHED"


@pytest.mark.interactive
@pytest.mark.skipif(not display_available(), reason="no GL render target available")
def test_picked_click_reaches_an_on_demand_application(interactive_runner):
    """One click, through the selection pass, with nothing else asking to draw."""
    events = [
        {'type': 'wait', 'duration': 2.0},
        {'type': 'mousebutton', 'x': 200, 'y': 200, 'button': 0, 'state': 1,
         'pick': True},
        # Long enough that a click waiting for an unrelated redraw would be seen
        # to be waiting, and short enough to keep the test quick.
        {'type': 'wait', 'duration': 4.0},
    ]

    result = interactive_runner(
        TARGET,
        events=events,
        env={'OPENGLCONTEXT_PROFILE': 'core', 'OPENGLCONTEXT_BACKEND': 'glfw'},
        timeout=90,
    )

    if 'Failed to connect to event socket' in result.stderr:
        pytest.skip(f"GL app could not start in this environment: {result.stderr}")

    assert CLICK_MARKER in result.stdout, (
        "a picked click never reached the handler of an application that "
        "renders only on demand.\n"
        f"returncode={result.returncode} timed_out={result.timed_out}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
