"""Which optional features the PBR program is compiled with: ``shaderFeatures``.

A program with every feature costs registers on every pixel whether or not the
scene uses them, so a program is compiled with the features its application
declares.
"""
import pytest

from OpenGLContext import renderoptions
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.passes import pbrpass
from OpenGLContext.passes.pbrpass import PBRPass, PBRShaderProgram, shader_features


class TestTheNamesAreParsed:
    @pytest.mark.parametrize('text', [None, '', '  ', 'all', 'ALL'])
    def test_all_or_nothing_said_is_every_feature(self, text):
        assert shader_features(text) is None

    def test_none_is_no_optional_feature(self):
        assert shader_features('none') == frozenset()

    def test_a_list_is_those_features(self):
        assert shader_features(' Clearcoat, planar-reflection ') == frozenset(
            {'clearcoat', 'planar-reflection'})

    def test_every_feature_can_be_named(self):
        every = ','.join(pbrpass.SHADER_FEATURES)
        assert shader_features(every) == frozenset(pbrpass.SHADER_FEATURES)

    def test_a_name_nothing_answers_to_is_reported_and_left_out(self, caplog):
        with caplog.at_level('WARNING'):
            found = shader_features('sheen, glitter')
        assert found == frozenset({'sheen'})
        assert 'glitter' in caplog.text


class TestTheDefinitionSaysWhichFeatures:
    def test_every_feature_is_the_default(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_SHADER_FEATURES', raising=False)
        assert shader_features(ContextDefinition().shaderFeatures) is None

    def test_the_environment_sets_the_default(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_SHADER_FEATURES', 'none')
        assert shader_features(ContextDefinition().shaderFeatures) == frozenset()

    def test_a_capture_does_not_inherit_the_variable(self):
        assert 'OPENGLCONTEXT_SHADER_FEATURES' in renderoptions.ENVIRONMENT


class TestThePassGivesTheProgramTheDefinitionsFeatures:
    @staticmethod
    def pass_for(definition):
        window = type('Window', (), {'contextDefinition': definition})()
        found = PBRPass.__new__(PBRPass)
        found.context = window
        found._shader_program_instance = None
        return found

    def test_a_declared_list_reaches_the_program(self):
        program = self.pass_for(ContextDefinition(shaderFeatures='sheen')).getShaderProgram()
        assert program.features == frozenset({'sheen'})

    def test_a_definition_that_declares_nothing_leaves_every_feature(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_SHADER_FEATURES', raising=False)
        program = self.pass_for(ContextDefinition()).getShaderProgram()
        assert program.features is None

    def test_a_pass_with_no_definition_leaves_every_feature(self):
        found = PBRPass.__new__(PBRPass)
        found._shader_program_instance = None
        assert found.getShaderProgram().features is None


@pytest.mark.usefixtures('gl_context')
class TestTheProgramIsCompiledForTheFeatures:
    @staticmethod
    def compiled(features):
        program = PBRShaderProgram()
        program.features = features
        assert program.compile()
        return program

    def test_none_compiles_out_every_feature_the_pass_gates(self):
        program = self.compiled(frozenset())
        assert not program.planar_reflection_supported
        assert not program.zone_probes_supported
        assert not program.volume_scatter_supported
        assert not program.layer_samplers_supported
        assert program.ext_channels == {}

    def test_every_feature_the_driver_runs_is_the_default(self):
        everything = self.compiled(None)
        nothing = self.compiled(frozenset())
        for gate in ('planar_reflection_supported', 'zone_probes_supported',
                     'volume_scatter_supported', 'layer_samplers_supported'):
            assert getattr(everything, gate) >= getattr(nothing, gate)
        assert len(everything.ext_channels) >= len(nothing.ext_channels)

    def test_naming_everything_is_the_default(self):
        named = self.compiled(frozenset(pbrpass.SHADER_FEATURES))
        default = self.compiled(None)
        for gate in ('planar_reflection_supported', 'zone_probes_supported',
                     'volume_scatter_supported', 'layer_samplers_supported'):
            assert getattr(named, gate) == getattr(default, gate)
        assert named.ext_channels == default.ext_channels

    def test_a_feature_named_is_a_feature_kept(self):
        default = self.compiled(None)
        kept = self.compiled(frozenset({'planar-reflection'}))
        assert kept.planar_reflection_supported == default.planar_reflection_supported
        assert not kept.zone_probes_supported
        assert not kept.volume_scatter_supported

    def test_the_lobes_are_defines_of_the_program_compiled(self):
        program = self.compiled(frozenset({'sheen'}))
        defines = dict(d.replace('#define ', '').split() for d in program._defines[0]
                       if d.startswith('#define USE_'))
        assert defines == {'USE_CLEARCOAT': '0', 'USE_SHEEN': '1', 'USE_TRANSMISSION': '0'}

    def test_the_default_adds_no_lobe_defines(self):
        program = self.compiled(None)
        assert not [d for d in program._defines[0] if d.startswith('#define USE_')]
