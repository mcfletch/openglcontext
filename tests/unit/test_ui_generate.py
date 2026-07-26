"""A settings page built from a node's fields, with no per-setting code."""

import pytest
from vrml import field, node

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.ui import generate
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.widgets import (
    KeyCapture, Label, Select, Slider, TextField, Toggle,
)


class Tunable(node.Node):
    PROTO = 'UITestTunable'
    enabled = field.newField('enabled', 'SFBool', 1, True)
    lightCount = field.newField('lightCount', 'SFInt32', 1, 4)
    exposure = field.newField('exposure', 'SFFloat', 1, 1.0)
    looseNumber = field.newField('looseNumber', 'SFFloat', 1, 0.0)
    quality = field.newField('quality', 'SFString', 1, 'high')
    freeText = field.newField('freeText', 'SFString', 1, '')
    keys = field.newField('keys', 'MFString', 1, list)
    size = field.newField('size', 'SFVec2f', 1, (1, 1))
    child = field.newField('child', 'SFNode', 1, node.NULL)
    secret = field.newField('secret', 'SFBool', 1, False)

    UI_HINTS = {
        'lightCount': {'label': 'Lights', 'minimum': 0, 'maximum': 8, 'step': 1},
        'exposure': {'minimum': 0.0, 'maximum': 2.0, 'step': 0.1},
        'quality': {'options': ('low', 'high'), 'optionLabels': ('Low', 'High')},
        'keys': {'editor': 'keys'},
        'secret': {'skip': True},
    }


class Refined(Tunable):
    PROTO = 'UITestRefined'
    UI_HINTS = {'exposure': {'label': 'Brightness'}}


@pytest.fixture
def target():
    return Tunable()


class TestEditorChoice:
    def test_a_boolean_gets_a_toggle(self, target):
        assert isinstance(generate.editor_for(target, 'enabled'), Toggle)

    def test_a_ranged_integer_gets_an_integer_slider(self, target):
        editor = generate.editor_for(target, 'lightCount',
                                     generate.hints_for(target)['lightCount'])
        assert isinstance(editor, Slider)
        assert editor.integer

    def test_a_ranged_float_slider_is_not_an_integer(self, target):
        editor = generate.editor_for(target, 'exposure',
                                     generate.hints_for(target)['exposure'])
        assert isinstance(editor, Slider)
        assert not editor.integer

    def test_a_number_with_no_range_gets_a_text_field(self, target):
        """A slider over an invented 0..1 is a wrong answer, not a missing one."""
        assert isinstance(generate.editor_for(target, 'looseNumber'), TextField)

    def test_a_string_with_options_gets_a_select(self, target):
        editor = generate.editor_for(target, 'quality',
                                     generate.hints_for(target)['quality'])
        assert isinstance(editor, Select)
        assert list(editor.optionLabels) == ['Low', 'High']

    def test_a_plain_string_gets_a_text_field(self, target):
        assert isinstance(generate.editor_for(target, 'freeText'), TextField)

    def test_key_names_get_a_key_capture(self, target):
        editor = generate.editor_for(target, 'keys',
                                     generate.hints_for(target)['keys'])
        assert isinstance(editor, KeyCapture)

    def test_a_vector_has_no_simple_editor(self, target):
        assert generate.editor_for(target, 'size') is None

    def test_a_sub_record_is_not_generated(self, target):
        """A sub-page is an authoring decision, not something to guess."""
        assert generate.editor_for(target, 'child') is None

    def test_a_field_can_opt_out(self, target):
        assert generate.editor_for(target, 'secret',
                                   generate.hints_for(target)['secret']) is None

    def test_an_unknown_field_gives_nothing(self, target):
        assert generate.editor_for(target, 'nosuch') is None

    def test_the_editor_is_bound_to_the_field(self, target):
        editor = generate.editor_for(target, 'enabled')
        assert editor.read() is True
        editor.write(False)
        assert not target.enabled


class TestLabels:
    def test_a_camel_case_name_becomes_words(self):
        assert generate.label_for('lightCount') == 'Light count'

    def test_a_hint_overrides_the_name(self):
        assert generate.label_for('lightCount', {'label': 'Lights'}) == 'Lights'

    def test_a_subclass_can_refine_an_inherited_hint(self):
        hints = generate.hints_for(Refined())
        assert hints['exposure']['label'] == 'Brightness'
        assert hints['exposure']['maximum'] == 2.0


class TestPage:
    def test_a_page_pairs_a_label_with_each_editor(self, target):
        grid = generate.page_for(target, include=['enabled', 'quality'])
        kinds = [type(child).__name__ for child in grid.children]
        assert kinds == ['Label', 'Toggle', 'Label', 'Select']

    def test_the_order_asked_for_is_the_order_shown(self, target):
        grid = generate.page_for(target, include=['quality', 'enabled'])
        assert grid.children[1].fieldName == 'quality'

    def test_a_field_with_no_editor_is_left_out(self, target):
        grid = generate.page_for(target, include=['enabled', 'size'])
        assert len(grid.children) == 2

    def test_every_editable_field_appears_by_default(self, target):
        grid = generate.page_for(target)
        names = [child.fieldName for child in grid.children
                 if hasattr(child, 'fieldName')]
        assert 'enabled' in names and 'quality' in names
        assert 'secret' not in names

    def test_a_new_field_turns_up_with_no_ui_work(self):
        """The reason generation exists: a setting cannot silently go missing."""
        class Extended(Tunable):
            PROTO = 'UITestExtended'
            newSetting = field.newField('newSetting', 'SFBool', 1, False)

        grid = generate.page_for(Extended())
        assert any(getattr(child, 'fieldName', None) == 'newSetting'
                   for child in grid.children)

    def test_fields_can_be_excluded(self, target):
        grid = generate.page_for(target, exclude=['enabled'])
        names = [getattr(child, 'fieldName', None) for child in grid.children]
        assert 'enabled' not in names


class TestContextDefinitionPage:
    def test_the_rendering_page_covers_the_hidden_features(self):
        grid = generate.page_for(ContextDefinition(),
                                 include=ContextDefinition.RENDERING_FIELDS)
        names = [getattr(child, 'fieldName', None) for child in grid.children]
        for expected in ('shadows', 'bloom', 'ibl', 'transmission',
                         'maximumLights', 'instancing', 'tessellationLOD'):
            assert expected in names, expected

    def test_every_rendering_field_got_an_editor(self):
        grid = generate.page_for(ContextDefinition(),
                                 include=ContextDefinition.RENDERING_FIELDS)
        editors = [child for child in grid.children
                   if not isinstance(child, Label)]
        assert len(editors) == len(ContextDefinition.RENDERING_FIELDS)

    def test_the_page_lays_out_without_a_gl_context(self):
        from OpenGLContext.ui.geometry import Rect
        grid = generate.page_for(ContextDefinition(),
                                 include=ContextDefinition.RENDERING_FIELDS)
        grid.arrange(Rect(0, 0, 600, 800), FontMetrics(8, 16, 2))
        assert all(child.rect.width > 0 for child in grid.children)
