"""Rendering features declared on the ContextDefinition rather than hidden.

Each of these was an environment variable read deep inside a pass, which meant
it could only be set before the process started and could not be shown to a
player at all.  They are now fields, with the environment variable as the
field's *default*, so a settings screen can offer them and a script can still
pin one from the shell.
"""


from OpenGLContext import renderoptions
from OpenGLContext.contextdefinition import ContextDefinition


class FakeContext:
    def __init__(self, definition):
        self.contextDefinition = definition


class FakePass:
    def __init__(self, definition):
        self.context = FakeContext(definition)


class TestLookup:
    def test_a_pass_finds_the_definition_through_its_context(self):
        definition = ContextDefinition()
        assert renderoptions.definition(FakePass(definition)) is definition

    def test_a_context_offers_its_own_definition(self):
        definition = ContextDefinition()
        assert renderoptions.definition(FakeContext(definition)) is definition

    def test_something_with_no_definition_gives_none(self):
        assert renderoptions.definition(object()) is None

    def test_a_missing_definition_falls_back_to_the_default(self):
        assert renderoptions.flag(object(), 'shadows', False) is False
        assert renderoptions.flag(object(), 'shadows', True) is True

    def test_a_flag_reads_the_field(self):
        definition = ContextDefinition(shadows=False)
        assert renderoptions.flag(FakePass(definition), 'shadows', True) is False

    def test_a_choice_reads_the_field(self):
        definition = ContextDefinition(ibl='analytic')
        assert renderoptions.choice(FakePass(definition), 'ibl', 'auto') == 'analytic'

    def test_auto_leaves_the_decision_to_the_engine(self):
        assert renderoptions.choice(FakePass(ContextDefinition()), 'ibl',
                                    'auto') == 'auto'

    def test_a_number_reads_the_field(self):
        definition = ContextDefinition(maximumLights=2)
        assert renderoptions.number(FakePass(definition), 'maximumLights', 8) == 2

    def test_an_unknown_name_falls_back(self):
        definition = ContextDefinition()
        assert renderoptions.flag(FakePass(definition), 'nosuch', True) is True


class TestDefaults:
    def test_shadows_are_on_by_default(self):
        assert ContextDefinition().shadows

    def test_the_environment_still_sets_the_default(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_SHADOWS', '0')
        import importlib
        from OpenGLContext import contextdefinition
        importlib.reload(contextdefinition)
        try:
            assert not contextdefinition.ContextDefinition().shadows
        finally:
            monkeypatch.delenv('OPENGLCONTEXT_SHADOWS')
            importlib.reload(contextdefinition)

    def test_every_declared_render_option_has_a_field(self):
        definition = ContextDefinition()
        for name in ('shadows', 'shadowsSoft', 'shadowCascades', 'maximumLights',
                     'bloom', 'ibl', 'iblIntensity', 'transmission',
                     'instancing', 'tessellationLOD', 'vsync'):
            assert hasattr(definition, name), name

    def test_the_choices_are_declared_for_the_settings_screen(self):
        assert 'analytic' in renderoptions.CHOICES['ibl']
        assert 'blend' in renderoptions.CHOICES['transmission']
        assert renderoptions.CHOICES['ibl'][0] == 'auto'


class TestPassesHonourTheFields:
    def test_a_pass_reads_shadows_from_the_definition(self):
        from OpenGLContext.passes.flatcore import FlatPass
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(ContextDefinition(shadows=False))
        assert not render.use_shadows

    def test_an_explicit_assignment_still_wins(self):
        """A test or a demo that turns shadows off on one pass keeps working."""
        from OpenGLContext.passes.flatcore import FlatPass
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(ContextDefinition(shadows=True))
        render.use_shadows = False
        assert not render.use_shadows

    def test_the_environment_settles_the_default_once_per_pass(self, monkeypatch):
        """A start-up switch, not a per-frame one.

        Something else editing ``os.environ`` mid-session -- another test
        module, a demo staging its next model -- must not silently flip a live
        pass; the field is the thing that is meant to change at runtime.
        """
        from OpenGLContext.passes.flatcore import FlatPass
        monkeypatch.setenv('OPENGLCONTEXT_SHADOWS', '0')
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(ContextDefinition())
        assert not render.use_shadows
        monkeypatch.setenv('OPENGLCONTEXT_SHADOWS', '1')
        assert not render.use_shadows

    def test_the_field_still_outranks_a_settled_environment(self, monkeypatch):
        from OpenGLContext.passes.flatcore import FlatPass
        monkeypatch.setenv('OPENGLCONTEXT_SHADOWS', '0')
        definition = ContextDefinition()
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(definition)
        assert not render.use_shadows
        definition.shadows = True
        assert render.use_shadows

    def test_soft_shadows_come_from_the_definition(self):
        from OpenGLContext.passes.flatcore import FlatPass
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(ContextDefinition(shadowsSoft=True))
        assert render.shadow_soft

    def test_instancing_comes_from_the_definition(self):
        from OpenGLContext.passes.flatcore import FlatPass
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(ContextDefinition(instancing=False))
        assert not render.instancing_enabled

    def test_the_light_limit_comes_from_the_definition(self):
        from OpenGLContext.passes.flatcore import FlatPass
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(ContextDefinition(maximumLights=2))
        assert render.maxLights(8) == 2

    def test_the_light_limit_never_exceeds_what_the_shader_has(self):
        from OpenGLContext.passes.flatcore import FlatPass
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(ContextDefinition(maximumLights=64))
        assert render.maxLights(8) == 8

    def test_zero_lights_means_no_lights_at_all(self):
        from OpenGLContext.passes.flatcore import FlatPass
        render = FlatPass.__new__(FlatPass)
        render.context = FakeContext(ContextDefinition(maximumLights=0))
        assert render.maxLights(8) == 0

    def test_the_pbr_pass_reads_instancing_from_the_definition(self):
        from OpenGLContext.passes.pbrpass import PBRPass
        render = PBRPass.__new__(PBRPass)
        render.context = FakeContext(ContextDefinition(instancing=False))
        assert not render.instancing_enabled

    def test_the_pbr_pass_reads_the_light_limit_from_the_definition(self):
        from OpenGLContext.passes.pbrpass import PBRPass
        render = PBRPass.__new__(PBRPass)
        render.context = FakeContext(ContextDefinition(maximumLights=3))
        assert render.maxLights(8) == 3

    def test_transmission_can_be_turned_off_from_the_definition(self):
        from OpenGLContext.passes.flateffects import _FlatEffectsMixin as FlatEffectsMixin
        render = FlatEffectsMixin.__new__(FlatEffectsMixin)
        render.context = FakeContext(ContextDefinition(transmission='off'))
        render._transmission_mode = None
        render._gl_renderer = 'NVIDIA'
        assert render.transmissionMode() == 'off'

    def test_ibl_can_be_pinned_from_the_definition(self):
        from OpenGLContext.passes import ibl
        assert ibl.resolve_ibl_mode('NVIDIA', probe=lambda: True,
                                    requested='analytic') == 'analytic'

    def test_ibl_auto_still_probes(self):
        from OpenGLContext.passes import ibl
        assert ibl.resolve_ibl_mode('llvmpipe', probe=lambda: True,
                                    requested='auto') == 'analytic'

    def test_bloom_can_be_turned_on_from_the_definition(self):
        from OpenGLContext.passes import bloom
        assert bloom.bloom_enabled(FakePass(ContextDefinition(bloom=True)))

    def test_bloom_stays_off_by_default(self):
        assert not __import__(
            'OpenGLContext.passes.bloom', fromlist=['bloom']
        ).bloom_enabled(FakePass(ContextDefinition()))

    def test_tessellation_lod_can_be_turned_off_from_the_definition(self):
        from OpenGLContext.scenegraph import tessellationlod

        class Mode:
            context = FakeContext(ContextDefinition(tessellationLOD=False))
            matrix = None
        assert not tessellationlod.lod_enabled(Mode())

    def test_the_shadow_cascade_count_can_be_pinned_from_the_definition(self):
        from OpenGLContext.passes.shadowpool import _CascadeControllerMixin

        class Program:
            MAX_CASCADES = 4

        render = _CascadeControllerMixin.__new__(_CascadeControllerMixin)
        render.context = FakeContext(ContextDefinition(shadowCascades=2))
        render.shader_program = Program()
        assert render._effectiveCascades() == 2


class TestEnvironmentIsReadOnceAndOnlyOnce:
    """One rule for when an environment variable is read, in one place.

    These are start-up switches: a pass that changed its mind mid-session
    because something else edited ``os.environ`` would be unpredictable, and
    the ContextDefinition field is the thing meant to change at runtime.  So
    the variable settles the *default* once and the field outranks it from
    then on.
    """

    def test_a_flag_is_read_once_per_process(self, monkeypatch):
        renderoptions.reset_env_cache()
        monkeypatch.setenv('OPENGLCONTEXT_TEST_FLAG', '1')
        assert renderoptions.env_flag_once('OPENGLCONTEXT_TEST_FLAG', False)
        monkeypatch.setenv('OPENGLCONTEXT_TEST_FLAG', '0')
        assert renderoptions.env_flag_once('OPENGLCONTEXT_TEST_FLAG', False), \
            "the memo re-read the environment"

    def test_resetting_makes_the_next_read_consult_it_again(self, monkeypatch):
        renderoptions.reset_env_cache()
        monkeypatch.setenv('OPENGLCONTEXT_TEST_FLAG', '1')
        assert renderoptions.env_flag_once('OPENGLCONTEXT_TEST_FLAG', False)
        renderoptions.reset_env_cache()
        monkeypatch.setenv('OPENGLCONTEXT_TEST_FLAG', '0')
        assert not renderoptions.env_flag_once('OPENGLCONTEXT_TEST_FLAG', True)

    def test_a_number_is_memoised_the_same_way(self, monkeypatch):
        renderoptions.reset_env_cache()
        monkeypatch.setenv('OPENGLCONTEXT_TEST_NUMBER', '4')
        assert renderoptions.env_number_once('OPENGLCONTEXT_TEST_NUMBER', 1) == 4
        monkeypatch.setenv('OPENGLCONTEXT_TEST_NUMBER', '9')
        assert renderoptions.env_number_once('OPENGLCONTEXT_TEST_NUMBER', 1) == 4

    def test_instancing_does_not_re_read_the_environment_each_frame(
            self, monkeypatch):
        """The property said one thing and the helper beside it did another."""
        from OpenGLContext.passes import flatcore
        renderoptions.reset_env_cache()
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCING', '1')
        flat = flatcore.FlatPass.__new__(flatcore.FlatPass)
        assert flat.instancing_enabled
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCING', '0')
        assert flat.instancing_enabled, "re-read the environment mid-session"

    def test_the_instance_minimum_is_not_frozen_at_import(self, monkeypatch):
        """Read at import, ``monkeypatch.setenv`` could never reach it."""
        from OpenGLContext.passes import flatcore
        renderoptions.reset_env_cache()
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_MIN', '7')
        flat = flatcore.FlatPass.__new__(flatcore.FlatPass)
        assert flat.instanceMinimum() == 7


class TestABadEnvironmentValueIsReported:
    """A typo that silently reverses a switch makes a CI result a lie."""

    def test_an_unrecognised_boolean_warns(self, monkeypatch, caplog):
        monkeypatch.setenv('OPENGLCONTEXT_TEST_FLAG', 'ture')
        with caplog.at_level('WARNING'):
            assert renderoptions.env_flag('OPENGLCONTEXT_TEST_FLAG', True)
        assert 'ture' in caplog.text

    def test_an_unrecognised_choice_warns(self, monkeypatch, caplog):
        monkeypatch.setenv('OPENGLCONTEXT_TEST_CHOICE', 'sideways')
        with caplog.at_level('WARNING'):
            assert renderoptions.env_choice(
                'OPENGLCONTEXT_TEST_CHOICE', ('auto', 'off'), {}) == 'auto'
        assert 'sideways' in caplog.text

    def test_an_unparseable_number_warns(self, monkeypatch, caplog):
        monkeypatch.setenv('OPENGLCONTEXT_TEST_NUMBER', 'lots')
        with caplog.at_level('WARNING'):
            assert renderoptions.env_number('OPENGLCONTEXT_TEST_NUMBER', 2.0) == 2.0
        assert 'lots' in caplog.text

    def test_an_empty_value_means_unset_for_both(self, monkeypatch):
        """Same spelling, same meaning: an unexported shell variable."""
        monkeypatch.setenv('OPENGLCONTEXT_TEST_FLAG', '')
        monkeypatch.setenv('OPENGLCONTEXT_TEST_CHOICE', '')
        assert renderoptions.env_flag('OPENGLCONTEXT_TEST_FLAG', True) is True
        assert renderoptions.env_choice(
            'OPENGLCONTEXT_TEST_CHOICE', ('auto', 'off'), {}) == 'auto'

    def test_a_good_value_is_silent(self, monkeypatch, caplog):
        monkeypatch.setenv('OPENGLCONTEXT_TEST_FLAG', 'off')
        with caplog.at_level('WARNING'):
            assert not renderoptions.env_flag('OPENGLCONTEXT_TEST_FLAG', True)
        assert not caplog.text


class TestEveryHintReachesTheScreen:
    """A hint for a field no section shows is presentation nobody can reach.

    The generated page exists so a new setting cannot silently go missing; the
    same guarantee is worth having in the other direction, or the hints drift
    into describing controls that were dropped.
    """

    def _sections(self):
        definition = ContextDefinition
        return set(definition.RENDERING_FIELDS + definition.INTERFACE_FIELDS
                   + definition.DIAGNOSTIC_FIELDS)

    def test_every_hint_names_a_field_a_section_shows(self):
        unreachable = set(ContextDefinition.UI_HINTS) - self._sections()
        assert not unreachable, sorted(unreachable)

    def test_every_hint_names_a_field_that_exists(self):
        from vrml import protofunctions
        definition = ContextDefinition()
        for name in ContextDefinition.UI_HINTS:
            assert protofunctions.getField(definition, name) is not None, name

    def test_the_profile_is_not_offered(self):
        """Settled when the window is made; a screen cannot change it."""
        assert 'profile' not in self._sections()
        assert 'profile' not in ContextDefinition.UI_HINTS
