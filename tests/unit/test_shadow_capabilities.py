"""Asking the driver what it can do, once rather than per shader compile.

Reading a GL context's capabilities means pulling its whole extension string
and building a set from it. A shader compile asks for the shadow budget, and a
scene that streams new materials as it goes compiles as it goes -- which put a
tenth of a frame into re-reading an answer that cannot change.
"""




class TestItIsAskedOnce:
    """Reading the driver's capabilities means pulling its whole extension
    string; a caller that asks per shader compile asks a great many times."""

    def test_a_real_answer_is_remembered(self, monkeypatch) -> None:
        from OpenGLContext.passes import shadowcaps
        monkeypatch.setattr(shadowcaps, '_DETECTED', {})
        monkeypatch.setattr(shadowcaps, '_current_gl_context', lambda: 7)
        asked = []

        def once(context=None):
            asked.append(context)
            return shadowcaps.ShadowCapabilities(detected=True)

        monkeypatch.setattr(shadowcaps.ShadowCapabilities, '_detect', once)
        context = object()
        first = shadowcaps.ShadowCapabilities.detect(context)
        second = shadowcaps.ShadowCapabilities.detect(context)
        assert first is second
        assert len(asked) == 1

    def test_a_fallback_answer_is_not(self, monkeypatch) -> None:
        """Asked before there is a context, the baseline comes back -- and the
        real answer is still available once there is one."""
        from OpenGLContext.passes import shadowcaps
        monkeypatch.setattr(shadowcaps, '_DETECTED', {})
        monkeypatch.setattr(shadowcaps, '_current_gl_context', lambda: 7)
        asked = []

        def probing(context=None):
            asked.append(context)
            return shadowcaps.ShadowCapabilities(detected=bool(asked[1:]))

        monkeypatch.setattr(shadowcaps.ShadowCapabilities, '_detect', probing)
        shadowcaps.ShadowCapabilities.detect(None)
        shadowcaps.ShadowCapabilities.detect(None)
        assert len(asked) == 2

    def test_two_contexts_get_their_own_answer(self, monkeypatch) -> None:
        """What is remembered belongs to the GL context, and a caller with
        nothing to hand -- a shader compile knows only that one is current --
        must get the answer for the one it is in."""
        from OpenGLContext.passes import shadowcaps
        monkeypatch.setattr(shadowcaps, '_DETECTED', {})
        current = [101]
        monkeypatch.setattr(shadowcaps, '_current_gl_context',
                            lambda: current[0])
        monkeypatch.setattr(
            shadowcaps.ShadowCapabilities, '_detect',
            lambda context=None: shadowcaps.ShadowCapabilities(
                detected=True, max_texture_units=current[0] % 100))
        assert shadowcaps.ShadowCapabilities.detect(None).max_texture_units == 1
        current[0] = 132
        assert shadowcaps.ShadowCapabilities.detect(None).max_texture_units == 32

    def test_with_no_context_current_nothing_is_remembered(self, monkeypatch) -> None:
        """There is no context for the answer to be about, so the next caller
        asks again rather than inheriting this one's."""
        from OpenGLContext.passes import shadowcaps
        monkeypatch.setattr(shadowcaps, '_DETECTED', {})
        monkeypatch.setattr(shadowcaps, '_current_gl_context', lambda: None)
        asked = []
        monkeypatch.setattr(
            shadowcaps.ShadowCapabilities, '_detect',
            lambda context=None: (asked.append(1),
                                  shadowcaps.ShadowCapabilities(detected=True))[1])
        shadowcaps.ShadowCapabilities.detect(None)
        shadowcaps.ShadowCapabilities.detect(None)
        assert len(asked) == 2


class TestForgettingTheAnswer:
    """A memo that outlives a test decides the next one's result. Both of
    these are what ``tests/unit/conftest.py`` calls between tests."""

    def test_the_capabilities_can_be_forgotten(self, monkeypatch) -> None:
        from OpenGLContext.passes import shadowcaps
        monkeypatch.setattr(shadowcaps, '_DETECTED', {})
        monkeypatch.setattr(shadowcaps, '_current_gl_context', lambda: 7)
        monkeypatch.setattr(
            shadowcaps.ShadowCapabilities, '_detect',
            lambda context=None: shadowcaps.ShadowCapabilities(detected=True))
        shadowcaps.ShadowCapabilities.detect(None)
        assert shadowcaps._DETECTED
        shadowcaps.reset_detected()
        assert not shadowcaps._DETECTED

    def test_the_shadow_config_can_be_forgotten(self, monkeypatch) -> None:
        from OpenGLContext.passes import shadersource
        monkeypatch.setattr(shadersource, '_SHADOW_CONFIG', (3, True))
        shadersource.reset_shadow_config()
        assert shadersource._SHADOW_CONFIG is None


class TestTheShadowConfigIsAskedOnce:
    def test_it_is_resolved_once(self, monkeypatch) -> None:
        from OpenGLContext.passes import shadersource, shadowcaps
        monkeypatch.setattr(shadersource, '_SHADOW_CONFIG', None)
        asked = []

        def once(context=None):
            asked.append(1)
            return shadowcaps.ShadowCapabilities(detected=True,
                                                 max_texture_units=32)

        monkeypatch.setattr(shadowcaps.ShadowCapabilities, 'detect', once)
        first = shadersource.resolve_shadow_config()
        assert shadersource.resolve_shadow_config() == first
        assert len(asked) == 1
