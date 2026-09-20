"""The documentation build: the commentary format, and the tutorial pages.

A tutorial is a runnable script with its commentary in ``'''`` strings between
the statements, and the page for it is written from that file, so the page and
the program it describes cannot drift apart.  These hold the two halves of
that: what the commentary notation means, and what the page made of it says.
"""

import os

import pytest

from docbuild import markup, tutorials


class TestHeadings:
    def test_a_line_wrapped_in_equals_is_the_title(self):
        (block,) = markup.commentary('=First steps=')
        assert block.kind == 'title'
        assert block.text == 'First steps'

    def test_a_line_wrapped_in_underscores_is_a_section(self):
        (block,) = markup.commentary('_Uniforms_')
        assert block.kind == 'subtitle'
        assert block.text == 'Uniforms'

    def test_a_sentence_that_happens_to_end_in_a_marker_is_prose(self):
        (block,) = markup.commentary('The scale is a = b = c')
        assert block.kind == 'rst'


class TestProse:
    def render(self, text):
        return '\n\n'.join(block.text for block in markup.commentary(text))

    def test_a_paragraph_is_wrapped(self):
        out = self.render('one ' * 60)
        assert max(len(line) for line in out.splitlines()) <= 78

    def test_an_asterisk_in_prose_is_an_asterisk(self):
        """The commentary is prose: nothing in it is reST markup."""
        assert '\\*must\\*' in self.render('what a shader *must* do')

    def test_a_link_becomes_a_link(self):
        out = self.render('the [https://example.org/ example] page')
        assert '`example <https://example.org/>`__' in out

    def test_a_bare_url_is_a_link(self):
        assert 'https://example.org/x' in self.render('see https://example.org/x')

    def test_bracketed_prose_is_not_a_link(self):
        """The target has to look like a location, or a footnote becomes one."""
        out = self.render('run it [--help for the tunable knobs]')
        assert 'help for the tunable knobs' in out
        assert '`__' not in out

    def test_bullets_become_a_list(self):
        out = self.render('* what a vertex shader does\n* what a fragment one does')
        assert out.startswith('- what a vertex shader does')
        assert '- what a fragment one does' in out

    def test_a_continuation_line_joins_its_bullet(self):
        out = self.render('* a bullet\n  carried on\n* another')
        assert '- a bullet carried on' in out

    def test_term_definitions_become_a_definition_list(self):
        out = self.render('target -- which buffer type is intended')
        assert out.splitlines()[0] == 'target'
        assert out.splitlines()[1].startswith('   which buffer')

    def test_a_block_whose_spacing_means_something_keeps_it(self):
        """A line indented under the line above it is a block laid out by hand."""
        out = self.render('The fields:\n  size    the count\n      in bytes\n')
        assert out.startswith('::')
        assert 'size    the count' in out


class TestPictures:
    def render(self, text):
        return '\n\n'.join(block.text for block in markup.commentary(text))

    def test_a_block_that_is_one_picture_is_an_image(self):
        out = self.render('[shader_1.py-screen-0001.png Screenshot]')
        assert out.startswith('.. image:: shader_1.py-screen-0001.png')
        assert ':alt: Screenshot' in out

    def test_a_picture_with_something_to_say_gets_a_caption(self):
        out = self.render('[transforms_1.py-screen-0002.png X Scale]')
        assert out.startswith('.. figure::')
        assert out.rstrip().endswith('X Scale')

    def test_several_pictures_in_one_block_are_a_row(self):
        out = self.render('[a.png X Scale][b.png Y Scale]')
        assert out.startswith('.. container:: shot-row')
        assert out.count('.. figure::') == 2

    def test_the_class_the_old_stylesheet_used_is_dropped(self):
        out = self.render('[class=clear-right a.png X Scale]')
        assert 'clear-right' not in out
        assert '.. figure:: a.png' in out

    def test_a_picture_in_a_sentence_is_left_as_written(self):
        """Only a block that is nothing but pictures is a picture."""
        out = self.render('look at [a.png this] and see')
        assert '.. image::' not in out


SCRIPT = '''#! /usr/bin/env python
\'\'\'=A title=

Some commentary.
\'\'\'
from OpenGLContext import testingcontext
\'\'\'_A section_

More commentary.\'\'\'
class TestContext(BaseContext):
    """An ordinary docstring, which is part of the code."""
'''


class TestReadingAScript:
    @pytest.fixture
    def tutorial(self, tmp_path):
        path = tmp_path / 'shader_1.py'
        path.write_text(SCRIPT, encoding='utf8')
        return tutorials.parse(str(path))

    def test_the_commentary_and_the_code_alternate(self, tutorial):
        assert [piece.kind for piece in tutorial.pieces] == [
            'code',
            'commentary',
            'code',
            'commentary',
            'code',
        ]

    def test_the_title_is_the_first_heading(self, tutorial):
        assert tutorial.title == 'A title'

    def test_a_docstring_stays_in_the_code(self, tutorial):
        """``\"\"\"`` is what the tutorial is building; ``'''`` is what it says."""
        code = [piece.text for piece in tutorial.pieces if piece.kind == 'code']
        assert any('An ordinary docstring' in piece for piece in code)

    def test_collapsed_code_is_marked(self, tmp_path):
        path = tmp_path / 'x.py'
        path.write_text("'''=T=\n\nsay\n'''\n#collapse\nimport os\n", encoding='utf8')
        tutorial = tutorials.parse(str(path))
        assert tutorial.pieces[-1].kind == 'collapsed'
        assert tutorial.pieces[-1].text.strip() == 'import os'


class TestTheTutorialPage:
    @pytest.fixture
    def page(self, tmp_path):
        path = tmp_path / 'shader_1.py'
        path.write_text(SCRIPT, encoding='utf8')
        return tutorials.render(tutorials.parse(str(path)))

    def test_it_opens_with_the_title(self, page):
        lines = [line for line in page.split('\n') if line.strip()]
        assert lines[1] == 'A title'
        assert lines[2] == '=' * len('A title')

    def test_it_carries_a_label_to_link_to(self, page):
        assert page.startswith('.. _tutorial-shader_1:')

    def test_the_shebang_is_not_part_of_the_lesson(self, page):
        assert 'env python' not in page

    def test_a_section_is_a_section(self, page):
        assert 'A section\n---------' in page

    def test_the_code_is_a_python_block(self, page):
        assert '.. code-block:: python' in page
        assert '   from OpenGLContext import testingcontext' in page

    def test_it_says_which_script_it_came_from(self, page):
        assert '``tests/shader_1.py``' in page


class TestTheIndex:
    def test_each_path_is_a_section_with_a_toctree(self):
        paths = [tutorials.TutorialPath('Shaders', 'The shader path.', ['shader_1'])]
        page = tutorials.render_index(paths, ['shader_1'])
        assert 'Shaders\n-------' in page
        assert 'The shader path.' in page
        assert '.. toctree::' in page
        assert '   shader_1' in page

    def test_a_script_that_is_not_there_is_not_listed(self):
        paths = [tutorials.TutorialPath('Shaders', 'x', ['shader_1', 'gone'])]
        page = tutorials.render_index(paths, ['shader_1'])
        assert 'gone' not in page

    def test_the_hand_written_pages_are_listed_too(self):
        page = tutorials.render_index([], [])
        for name, _ in tutorials.HAND_WRITTEN:
            assert name in page


class TestWritingThemAll:
    def test_every_named_script_gets_a_page(self, tmp_path):
        source = tmp_path / 'tests'
        source.mkdir()
        (source / 'shader_1.py').write_text(SCRIPT, encoding='utf8')
        output = tmp_path / 'out'
        written = tutorials.write(
            output=str(output),
            tests=str(source),
            paths=[tutorials.TutorialPath('Shaders', 'x', ['shader_1'])],
        )
        assert written == ['shader_1']
        assert (output / 'shader_1.rst').is_file()
        assert (output / 'index.rst').is_file()

    def test_a_missing_script_is_reported_rather_than_fatal(self, tmp_path, caplog):
        output = tmp_path / 'out'
        written = tutorials.write(
            output=str(output),
            tests=str(tmp_path),
            paths=[tutorials.TutorialPath('Shaders', 'x', ['gone'])],
        )
        assert written == []
        assert 'no such tutorial script' in caplog.text


class TestThePathsThemselves:
    """The paths name the scripts that are in the repository."""

    def test_every_named_script_is_there(self):
        missing = [
            name
            for path in tutorials.PATHS
            for name in path.scripts
            if not os.path.isfile(os.path.join(tutorials.TESTS, '%s.py' % (name,)))
        ]
        assert missing == []

    def test_every_named_script_has_commentary_to_read(self):
        """``'''`` marks it; a script using ``\"\"\"`` documents as an empty page."""
        without = [
            name
            for path in tutorials.PATHS
            for name in path.scripts
            if not [
                piece
                for piece in tutorials.parse(
                    os.path.join(tutorials.TESTS, '%s.py' % (name,))
                ).pieces
                if piece.kind == 'commentary'
            ]
        ]
        assert without == []

    def test_no_script_is_in_two_paths(self):
        named = [name for path in tutorials.PATHS for name in path.scripts]
        assert len(named) == len(set(named))
