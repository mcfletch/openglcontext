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
