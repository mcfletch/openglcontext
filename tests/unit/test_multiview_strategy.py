"""Which way a context draws several views, decided from what its driver offers.

The rule is a function of the extension list and the version, so it is tested
here without a context; ``detect`` is the part that asks a driver, and is
exercised against the real one at the end.
"""
import logging

import pytest

from OpenGLContext.multiview import strategy as multiview
from OpenGLContext.multiview.strategy import MultiviewCapabilities
from OpenGLContext import contextresources, renderoptions
from OpenGLContext.contextdefinition import ContextDefinition


def caps(extensions=(), version=(3, 3), viewports=16):
    return MultiviewCapabilities.from_features(set(extensions), version, viewports)


class TestAvailability:
    def test_gl33_with_no_extensions_draws_views_in_turn(self):
        assert caps().available() == ('sequential',)

    def test_gl41_routes_primitives_with_a_geometry_shader(self):
        # Apple silicon's GL 4.1: viewport arrays are core, the vertex-shader
        # viewport index is not offered.
        assert caps(version=(4, 1)).available() == ('geometry', 'sequential')

    def test_the_extensions_do_the_same_below_41(self):
        assert caps({'GL_ARB_viewport_array', 'GL_ARB_gpu_shader5'},
                    (3, 3)).available() == ('geometry', 'sequential')

    def test_a_geometry_shader_must_be_invocable_once_per_view(self):
        assert caps({'GL_ARB_viewport_array'}, (3, 3)).available() == ('sequential',)

    def test_a_vertex_shader_viewport_index_is_preferred_when_offered(self):
        found = caps({'GL_ARB_shader_viewport_layer_array'}, (4, 6))
        assert found.available() == ('vertex', 'geometry', 'sequential')
        assert found.vertex_extension == 'GL_ARB_shader_viewport_layer_array'

    def test_the_amd_extension_serves_where_the_arb_one_is_missing(self):
        found = caps({'GL_AMD_vertex_shader_viewport_index'}, (4, 5))
        assert found.vertex_extension == 'GL_AMD_vertex_shader_viewport_index'
        assert found.available()[0] == 'vertex'

    def test_the_arb_name_wins_when_both_are_offered(self):
        found = caps({'GL_AMD_vertex_shader_viewport_index',
                      'GL_ARB_shader_viewport_layer_array'}, (4, 6))
        assert found.vertex_extension == 'GL_ARB_shader_viewport_layer_array'

    def test_a_vertex_viewport_index_is_used_from_gl_41(self):
        found = caps({'GL_ARB_shader_viewport_layer_array', 'GL_ARB_viewport_array',
                      'GL_ARB_gpu_shader5'}, (4, 0))
        assert found.available() == ('geometry', 'sequential')

    def test_a_vertex_viewport_index_needs_viewport_arrays_to_route_to(self):
        found = caps({'GL_ARB_shader_viewport_layer_array'}, (3, 3))
        assert found.available() == ('sequential',)

    def test_names_without_the_gl_prefix_are_accepted(self):
        assert caps({'ARB_viewport_array'}).viewport_array

    def test_too_few_viewports_leaves_views_in_turn(self):
        assert caps(version=(4, 6), viewports=1).available() == ('sequential',)

    def test_the_views_one_submission_can_reach_are_bounded_by_both(self):
        assert caps(version=(4, 6), viewports=8).max_views == 8
        assert caps(version=(4, 6), viewports=32).max_views == multiview.MAX_VIEWS
        assert caps().max_views == multiview.MAX_VIEWS


class TestProgramViews:
    def test_programs_are_compiled_for_a_power_of_two_of_views(self):
        counts = [multiview.program_views(views) for views in range(1, 10)]
        assert counts == [2, 2, 4, 4, 8, 8, 8, 8, 16]


class TestChoice:
    def test_auto_takes_the_best_strategy_this_build_draws(self):
        found = caps({'GL_ARB_shader_viewport_layer_array'}, (4, 6))
        assert found.choose('auto', implemented=('vertex', 'sequential')) == 'vertex'
        assert found.choose('auto', implemented=('sequential',)) == 'sequential'

    def test_a_requested_strategy_is_honoured_where_it_can_run(self):
        found = caps(version=(4, 1))
        assert found.choose('sequential', implemented=('geometry', 'sequential')) == 'sequential'

    def test_a_strategy_the_driver_lacks_falls_back_and_says_so(self, caplog):
        with caplog.at_level(logging.WARNING, logger=multiview.__name__):
            chosen = caps().choose('vertex', implemented=('vertex', 'sequential'))
        assert chosen == 'sequential'
        assert 'vertex' in caplog.text

    def test_an_unknown_strategy_is_reported_not_guessed(self, caplog):
        with caplog.at_level(logging.WARNING, logger=multiview.__name__):
            assert caps().choose('sideways') == 'sequential'
        assert 'sideways' in caplog.text

    def test_a_strategy_that_failed_is_passed_over_for_the_next(self):
        found = caps({'GL_ARB_shader_viewport_layer_array'}, (4, 6))
        assert found.choose('auto', failed={'vertex'}) == 'geometry'
        assert found.choose('auto', failed={'vertex', 'geometry'}) == 'sequential'

    def test_a_requested_strategy_that_failed_falls_back_and_says_so(self, caplog):
        found = caps({'GL_ARB_shader_viewport_layer_array'}, (4, 6))
        with caplog.at_level(logging.WARNING, logger=multiview.__name__):
            assert found.choose('vertex', failed={'vertex'}) == 'geometry'
        assert 'vertex' in caplog.text

    def test_sequential_cannot_be_failed_out_of(self):
        assert caps().choose('auto', failed={'sequential'}) == 'sequential'

    def test_the_default_choice_is_a_strategy(self):
        assert caps().choose() in multiview.STRATEGIES

    def test_sequential_is_always_a_strategy(self):
        assert 'sequential' in multiview.STRATEGIES

    def test_built_from_features_it_has_the_viewports_it_is_told(self):
        assert caps(viewports=1).max_viewports == 1
        assert MultiviewCapabilities.from_features(set(), (4, 1)).max_viewports == 1


class TestRequested:
    def test_the_definition_field_says_which_strategy_is_wanted(self):
        class Source:
            contextDefinition = ContextDefinition(multiview='sequential')

        assert multiview.requested_strategy(Source()) == 'sequential'

    def test_with_no_definition_the_choice_is_automatic(self):
        assert multiview.requested_strategy(object()) == 'auto'

    def test_the_environment_pins_the_default(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_MULTIVIEW', 'sequential')
        renderoptions.reset_env_cache()
        assert ContextDefinition().multiview == 'sequential'

    def test_the_environment_is_what_a_pass_asks_for(self, monkeypatch):
        """A definition whose field nobody set answers with the variable's pin."""

        class Source:
            contextDefinition = ContextDefinition()

        monkeypatch.setenv('OPENGLCONTEXT_MULTIVIEW', 'gs')
        assert multiview.requested_strategy(Source()) == 'geometry'

    def test_the_environment_is_read_once(self, monkeypatch):
        """A start-up switch: the definition's field is what changes at run time."""

        class Source:
            contextDefinition = ContextDefinition()

        monkeypatch.setenv('OPENGLCONTEXT_MULTIVIEW', 'sequential')
        assert multiview.requested_strategy(Source()) == 'sequential'
        monkeypatch.setenv('OPENGLCONTEXT_MULTIVIEW', 'geometry')
        assert multiview.requested_strategy(Source()) == 'sequential'

    def test_the_environment_variable_is_a_rendering_one(self):
        assert 'OPENGLCONTEXT_MULTIVIEW' in renderoptions.ENVIRONMENT


class TestDetect:
    @pytest.fixture(autouse=True)
    def forget(self):
        multiview.reset_detected()
        yield
        multiview.reset_detected()

    def test_with_no_context_the_answer_is_the_33_floor(self):
        found = MultiviewCapabilities.detect()
        assert found.available() == ('sequential',)
        assert not found.detected

    @pytest.mark.usefixtures('gl_context')
    def test_a_real_driver_is_asked_once(self):
        first = MultiviewCapabilities.detect()
        assert first.detected
        assert first.gl_version >= (3, 3)
        assert MultiviewCapabilities.detect() is first
        assert 'sequential' in first.available()

    @pytest.mark.usefixtures('gl_context')
    def test_a_context_that_dies_is_forgotten(self):
        """A driver hands a dead context's address to the next one."""
        MultiviewCapabilities.detect()
        key = contextresources.context_key()
        assert key in multiview._DETECTED  # noqa: SLF001 the per-context detection memo, which must let a dead context go
        contextresources.context_lost()
        assert key not in multiview._DETECTED  # noqa: SLF001 the per-context detection memo, which must let a dead context go

    @pytest.mark.usefixtures('gl_context')
    def test_a_driver_that_answers_nothing_is_asked_once(self, monkeypatch):
        asked = []

        def nothing(cls):
            asked.append(1)
            return cls()

        monkeypatch.setattr(MultiviewCapabilities, '_detect', classmethod(nothing))
        first = MultiviewCapabilities.detect()
        assert not first.detected
        assert MultiviewCapabilities.detect() is first
        assert len(asked) == 1
