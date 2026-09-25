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

    def test_a_lone_asterisk_is_an_asterisk(self):
        """The commentary is prose, so a star that starts nothing is a star."""
        assert '\\*' in self.render('a * marks the default')
        assert '\\*args' in self.render('passed as *args')

    def test_a_link_becomes_a_link(self):
        out = self.render('the [https://example.org/ example] page')
        assert '`example <https://example.org/>`__' in out

    def test_a_link_to_another_page_becomes_a_reference_to_it(self):
        """``.html`` is where a page lands, not where its source is."""
        out = self.render('the [molehill.html Molehill] scene')
        assert ':doc:`Molehill <molehill>`' in out

    def test_a_link_to_a_page_outside_the_tutorials_keeps_its_path(self):
        out = self.render('see [/structure.html the structure] page')
        assert ':doc:`the structure </structure>`' in out

    def test_a_link_to_somewhere_else_is_still_a_link(self):
        out = self.render('the [https://example.org/x.html example] page')
        assert '`example <https://example.org/x.html>`__' in out

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

    def test_a_paragraph_opening_with_emphasis_is_not_a_bullet(self):
        """A marker is a star and a space; ``*Which file*`` is emphasis."""
        out = self.render('*Which file to write.*  The menu offers three.')
        assert out.startswith('*Which file to write.*')
        assert '- ' not in out

    def test_term_definitions_become_a_definition_list(self):
        out = self.render('target -- which buffer type is intended')
        assert out.splitlines()[0] == 'target'
        assert out.splitlines()[1].startswith('   which buffer')

    def test_a_block_whose_spacing_means_something_keeps_it(self):
        """A line indented under the line above it is a block laid out by hand."""
        out = self.render('size    the count\n    in bytes\nflags   what to do\n')
        assert out.startswith('::')
        assert 'size    the count' in out

    def test_an_indented_list_under_a_heading_keeps_its_columns(self):
        """The keys a demo binds, written as a column against what they do."""
        out = self.render('Keys:\n    space   drop another body\n    r       reset\n')
        assert out.startswith('Keys:')
        assert 'space   drop another body' in out
        assert 'r       reset' in out


class TestRestInTheCommentary:
    """A script whose commentary is written in reST keeps its markup.

    The notation grew up around plain prose, where a backtick is a backtick.
    The newer scripts document themselves in reST -- a literal, a role, a
    reference -- and those spans are markup rather than text.
    """

    def render(self, text):
        return '\n\n'.join(block.text for block in markup.commentary(text))

    def test_a_literal_is_left_as_markup(self):
        assert '``build``' in self.render('what ``build`` keeps')

    def test_interpreted_text_is_left_as_markup(self):
        assert self.render('one `HUDLayer` over the world').startswith(
            'one `HUDLayer` over'
        )

    def test_a_role_is_left_as_markup(self):
        out = self.render('see :doc:`the characters page </characters>`')
        assert ':doc:`the characters page </characters>`' in out

    def test_a_role_wrapped_across_lines_is_still_one_role(self):
        """A docstring wraps its lines; the role does not care where."""
        out = self.render('see :doc:`Light Nodes,\nROUTEs <lightobject>` for it')
        assert ':doc:`Light Nodes, ROUTEs <lightobject>`' in out

    def test_a_literal_block_follows_the_colons_that_announce_it(self):
        """``::`` at the end of a paragraph means the next block is literal."""
        out = self.render('Run one of these::\n\n    prog --lathe\n    prog --list')
        assert 'Run one of these::' in out
        assert '   prog --lathe\n   prog --list' in out

    def test_a_name_inside_a_literal_is_not_linked_again(self):
        """``glBegin`` written as a literal is already what the writer meant."""
        assert self.render('call ``glBegin``') == 'call ``glBegin``'

    def test_emphasis_is_left_as_markup(self):
        assert self.render('what a shader *must* do') == 'what a shader *must* do'

    def test_strong_is_left_as_markup(self):
        assert '**one**' in self.render('they share **one** mesh')

    def test_multiplication_is_not_emphasis(self):
        """``2*3*4`` is arithmetic: the stars have words tight against them."""
        assert self.render('a 2*3*4 grid') == 'a 2\\*3\\*4 grid'

    def test_prose_around_the_markup_is_still_escaped(self):
        out = self.render('a lone * beside ``code``')
        assert '\\*' in out
        assert '``code``' in out


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


class TestLinkingTheGLNames:
    """A call named in the commentary is a link into PyOpenGL's own set.

    That set declares every entry point under its package name, so the target
    is ``OpenGL.GL.glBegin`` and ``~`` is what shows the reader the name they
    wrote; ``intersphinx`` turns it into an address at build time, and where
    that set is out of reach the name renders as itself.
    """

    def render(self, text):
        return '\n\n'.join(block.text for block in markup.commentary(text))

    def test_an_entry_point_becomes_a_reference(self):
        assert self.render('call glBegin to start') == (
            'call :py:func:`~OpenGL.GL.glBegin` to start'
        )

    def test_a_word_that_only_looks_like_one_is_left_alone(self):
        """``glTF`` is a file format, and PyOpenGL exports nothing of the name."""
        assert 'glTF' in self.render('a glTF model')
        assert 'py:func' not in self.render('a glTF model')

    def test_a_dotted_name_becomes_a_reference(self):
        assert self.render('from OpenGL.GL.shaders import x') == (
            'from :py:obj:`OpenGL.GL.shaders` import x'
        )

    def test_a_dotted_name_is_read_once(self):
        """Not as a module and then again as the call at the end of it."""
        out = self.render('see OpenGL.GL.glBegin')
        assert out == 'see :py:obj:`OpenGL.GL.glBegin`'

    def test_a_reference_running_into_a_bracket_is_separated(self):
        """reST reads a reference as one only where it ends before a closer."""
        out = self.render('glGetUniformLocation( shader, name )')
        assert out.startswith(':py:func:`~OpenGL.GL.glGetUniformLocation`\\ (')

    def test_the_glu_and_glut_names_come_from_their_own_packages(self):
        known = markup.entry_points()
        assert known.get('gluPerspective') == 'OpenGL.GLU'
        assert known.get('glBegin') == 'OpenGL.GL'


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
        assert '.. tutorial-code:: python' in page
        assert '   from OpenGLContext import testingcontext' in page

    def test_code_at_the_top_level_is_not_indented(self, page):
        assert ':indent:' not in page

    def test_it_says_which_script_it_came_from(self, page):
        assert '``tests/shader_1.py``' in page


#: A method whose commentary sits between it and the class it belongs to.
NESTED = '''\'\'\'=A title=\'\'\'
class TestContext(BaseContext):
    """The class."""
    \'\'\'Commentary on the method.\'\'\'
    def OnInit(self):
        \'\'\'Commentary inside the method.\'\'\'
        self.x = 1
        if self.x:
            self.y = 2
'''


class TestIndentation:
    """Code cut from inside a class or a function stays where it sits in it."""

    @pytest.fixture
    def page(self, tmp_path):
        path = tmp_path / 'nested.py'
        path.write_text(NESTED, encoding='utf8')
        return tutorials.render(tutorials.parse(str(path)))

    def test_a_method_says_how_far_in_it_sits(self, page):
        assert (
            '.. tutorial-code:: python\n'
            '   :indent: 4\n\n'
            '   def OnInit(self):'
        ) in page

    def test_a_method_body_says_how_far_in_it_sits(self, page):
        assert (
            '.. tutorial-code:: python\n'
            '   :indent: 8\n\n'
            '   self.x = 1\n'
            '   if self.x:\n'
            '       self.y = 2'
        ) in page

    def test_the_built_page_shows_the_code_at_its_indent(
        self, page, tmp_path, monkeypatch
    ):
        """docutils strips a directive's common indent; the directive puts it back."""
        from docutils import nodes
        from sphinx.application import Sphinx

        from OpenGLContext.testing.paths import tests_root

        monkeypatch.syspath_prepend(str(tests_root(__file__).parent / 'docs' / '_ext'))
        source = tmp_path / 'source'
        source.mkdir()
        (source / 'conf.py').write_text(
            "extensions = ['oglc_tutorials']\n", encoding='utf8'
        )
        (source / 'index.rst').write_text(page, encoding='utf8')
        app = Sphinx(
            str(source),
            str(source),
            str(tmp_path / 'out'),
            str(tmp_path / 'doctrees'),
            'dummy',
            status=None,
            warning=None,
            freshenv=True,
        )
        app.build()
        code = [
            block.astext()
            for block in app.env.get_doctree('index').findall(nodes.literal_block)
        ]
        assert code == [
            'class TestContext(BaseContext):\n    """The class."""',
            '    def OnInit(self):',
            '        self.x = 1\n        if self.x:\n            self.y = 2',
        ]
        assert all(
            block['language'] == 'python'
            for block in app.env.get_doctree('index').findall(nodes.literal_block)
        )


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

    def test_a_path_can_open_with_a_page_written_by_hand(self):
        """A walkthrough belongs with the scripts it walks through."""
        paths = [tutorials.TutorialPath('Physics', 'x', ['shader_1'],
                                        pages=['physics_getting_started'])]
        page = tutorials.render_index(paths, ['shader_1'])
        assert '   physics_getting_started\n   shader_1' in page

    def test_a_page_in_a_path_is_not_listed_twice(self):
        page = tutorials.render_index(tutorials.PATHS, [])
        assert page.count('physics_getting_started') == 1


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

    def test_every_picture_a_tutorial_shows_is_there(self):
        """A named picture that is not in ``docs/tutorials`` is a broken image."""
        missing = []
        for path in tutorials.PATHS:
            for name in path.scripts:
                source = os.path.join(tutorials.TESTS, '%s.py' % (name,))
                for piece in tutorials.parse(source).pieces:
                    if piece.kind != 'commentary':
                        continue
                    for url in markup.pictures(piece.text):
                        if not os.path.isfile(os.path.join(tutorials.OUTPUT, url)):
                            missing.append('%s: %s' % (name, url))
        assert missing == []

    def test_every_page_a_path_names_by_hand_is_there(self):
        missing = [
            name
            for path in tutorials.PATHS
            for name in path.pages
            if not os.path.isfile(
                os.path.join(tutorials.OUTPUT, '%s.rst' % (name,))
            )
        ]
        assert missing == []


class TestEveryLinkedTutorialIsWritten:
    """A page that links ``tutorials/<name>`` links a page the build writes:
    one of :data:`tutorials.PATHS`, or a hand-written one."""

    def written(self):
        names = {'index'} | {name for name, _ in tutorials.HAND_WRITTEN}
        for path in tutorials.PATHS:
            names.update(path.pages)
            names.update(path.scripts)
        return names

    def test_no_documentation_page_links_a_tutorial_nothing_writes(self):
        import glob
        import re
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        linked = set()
        for page in glob.glob(os.path.join(here, 'docs', '*.rst')):
            with open(page, encoding='utf-8') as handle:
                linked.update(re.findall(r'<tutorials/([A-Za-z0-9_]+)>',
                                         handle.read()))
        assert linked - self.written() == set()

    def test_a_tutorial_s_screenshot_is_committed_beside_it(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        picture = os.path.join(here, 'docs', 'tutorials',
                               'physics_events.py-screen-0001.png')
        assert os.path.isfile(picture)
