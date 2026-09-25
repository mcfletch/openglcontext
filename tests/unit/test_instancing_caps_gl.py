"""GL capability detection for the instancing draw-path selector.

``detect_capabilities`` queries the live context (version, UBO size, extensions)
and caches the verdict; these drive it against a real hidden GLFW context. The
pure key/grouping logic is in test_instancing_logic; the instanced draw itself is
exercised end-to-end by test_passes_render_gl.
"""

import pytest
import OpenGL.GL as GL


from OpenGLContext.passes import instancing


@pytest.fixture
def gl_context(gl_window):
    return gl_window('caps', size=(32, 32))


@pytest.fixture(autouse=True)
def no_remembered_capabilities(monkeypatch):
    """Each test detects the capabilities afresh, and what it detected is
    forgotten when it ends: the answer is kept at module level."""
    monkeypatch.setattr(instancing, '_CAPS_CACHE', None)


@pytest.mark.usefixtures('gl_context')
def test_detect_capabilities_reports_live_context():
    caps = instancing.detect_capabilities(force=True)
    # A real GL 3.3+ context reports a plausible version and a non-trivial UBO
    # size, and enumerates at least one extension.
    assert caps.version >= (3, 3)
    assert caps.max_uniform_block_size >= 16384
    assert len(caps.extensions) > 0
    assert caps.max_materials() >= 1


@pytest.mark.usefixtures('gl_context')
def test_detect_capabilities_is_cached():
    first = instancing.detect_capabilities(force=True)
    # Second unforced call returns the very same cached object (no re-query).
    assert instancing.detect_capabilities() is first


@pytest.mark.usefixtures('gl_context')
def test_detect_capabilities_degrades_on_query_failure(monkeypatch):
    """A driver that raises on every integer query falls back per field to the safe
    3.3 baseline (no version, no UBO size, no extensions) rather than propagating."""

    def boom(*_a, **_k):
        raise RuntimeError("simulated driver query failure")

    monkeypatch.setattr(GL, 'glGetIntegerv', boom)
    caps = instancing.detect_capabilities(force=True)
    assert caps.version == (3, 3)
    assert caps.max_uniform_block_size == 16384
    assert caps.ssbo is False
    assert len(caps.extensions) == 0


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
