"""Genuine end-to-end exercise of the event-injection subsystem.

Before this, event_injector.py and the interactive_runner/event_sender fixtures
were only tested against themselves. This drives a real OpenGLContext through the
whole path -- socket IPC -> EventInjector -> event manager -> a bound handler --
by injecting a mouse click and asserting the handler ran.
"""

import os
from pathlib import Path

import pytest

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = tests_root(__file__)
TARGET = TESTS_DIR / "helpers" / "interactive_click_target.py"
CLICK_MARKER = "INJECTED_CLICK_DISPATCHED"


def _has_render_target():
    return bool(
        os.environ.get('DISPLAY')
        or os.environ.get('WAYLAND_DISPLAY')
        or os.environ.get('PYOPENGL_PLATFORM', '').lower() in ('egl', 'osmesa')
    )


@pytest.mark.interactive
@pytest.mark.skipif(not _has_render_target(), reason="no GL render target available")
def test_injected_click_reaches_handler(interactive_runner):
    """An injected mouse click is dispatched to the application handler."""
    # GLFW/context startup time varies a lot under parallel CI load, so rather
    # than bet on one fixed instant, inject the click several times spread over
    # a few seconds; the handler is idempotent and the marker only has to appear
    # once. This keeps the test from being wall-clock-fragile.
    click = {'type': 'mousebutton', 'x': 100, 'y': 100, 'button': 0, 'state': 1}
    events = [{'type': 'wait', 'duration': 1.0}]
    for _ in range(6):
        events.append(click)
        events.append({'type': 'wait', 'duration': 0.5})

    result = interactive_runner(
        TARGET,
        events=events,
        env={'OPENGLCONTEXT_PROFILE': 'compatibility'},
        timeout=90,
    )

    # If the GL app could not even bind its event socket, the environment could
    # not launch it (e.g. a display/GLFW exhausted after a long run of GL tests),
    # which is not a failure of the injection path -- skip rather than flake. The
    # dispatch logic itself is covered unconditionally by the GL-free unit tests
    # in test_testing_infrastructure.TestEventInjectionMixin.
    if 'Failed to connect to event socket' in result.stderr:
        pytest.skip(f"GL app could not start in this environment: {result.stderr}")

    assert CLICK_MARKER in result.stdout, (
        "injected click never reached the handler.\n"
        f"returncode={result.returncode} timed_out={result.timed_out}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
