"""The documentation build: the commentary format, and the tutorial pages.

A tutorial is a runnable script with its commentary in ``'''`` strings between
the statements, and the page for it is written from that file, so the page and
the program it describes cannot drift apart.  These hold the two halves of
that: what the commentary notation means, and what the page made of it says.
"""

import glob
import json
import os
import re

import pytest

from docbuild import markup, tutorials

from OpenGLContext.loaders.gltf import zoning, hooks
from OpenGLContext.scenegraph import particlehooks
from OpenGLContext.scenegraph.mirrorhooks import PARAMETERS
from OpenGLContext.scenegraph.reflector import LIMITS
from OpenGLContext.scenegraph.water import gltf, medium
from OpenGLContext.testing.paths import tests_root


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

    def test_commentary_inside_a_docstring_is_refused(self, tmp_path):
        """``'''`` inside a ``\"\"\"`` string is part of that string, not commentary.

        Split there, the page shows the docstring unclosed and its closing
        quotes as code of their own.
        """
        path = tmp_path / 'nested.py'
        path.write_text(
            "'''=T='''\n"
            'class Sounds:\n'
            '    """What the game sounds like.\n'
            '\n'
            "    '''=The sounds='''\n"
            '    """\n',
            encoding='utf8',
        )
        with pytest.raises(ValueError, match=r'nested\.py:5'):
            tutorials.parse(str(path))

    def test_a_string_after_commentary_is_code(self, tmp_path):
        """A ``\"\"\"`` string under a commentary block, as the shader tutorials
        write their GLSL, is code."""
        path = tmp_path / 'glsl.py'
        path.write_text(
            "'''=T='''\n"
            'shader = compile(\n'
            "    '''the vertex stage:'''\n"
            '    """\n'
            '    void main() {}\n'
            '    """\n'
            ')\n',
            encoding='utf8',
        )
        tutorial = tutorials.parse(str(path))
        code = [piece.text for piece in tutorial.pieces if piece.kind == 'code']
        assert any('void main() {}' in piece for piece in code)

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

    def test_a_script_in_a_directory_says_where_it_is(self, tmp_path):
        path = tmp_path / 'shader_1.py'
        path.write_text(SCRIPT, encoding='utf8')
        page = tutorials.render(
            tutorials.parse(str(path), script='tutorials/shaders/shader_1')
        )
        assert page.startswith('.. _tutorial-shader_1:')
        assert '``tests/tutorials/shaders/shader_1.py``' in page


#: Commentary linking pages in its own path, in another path and outside the
#: tutorials, as ``markup`` writes each of them.
LINKS = """'''=Links=

The [shader_2.html next lesson], the [nehe1.html first NeHe lesson], the
[../shadows.html shadows page], the [/structure.html structure page] and
:doc:`Loading a glTF model <loading_gltf_model>`.
'''
"""


class TestLinksBetweenPages:
    """A page is written in its path's directory; links in the commentary are
    written as though from ``docs/tutorials``, and each is resolved from there."""

    PAGES = {
        'shader_2': 'tutorials/shaders/shader_2',
        'nehe1': 'tutorials/nehe/nehe1',
        'loading_gltf_model': 'tutorials/core_context/loading_gltf_model',
    }

    @pytest.fixture
    def page(self, tmp_path):
        path = tmp_path / 'shader_1.py'
        path.write_text(LINKS, encoding='utf8')
        return tutorials.render(tutorials.parse(str(path)), pages=self.PAGES)

    def test_a_tutorial_in_the_same_path_is_found_where_it_is(self, page):
        assert ':doc:`next lesson </tutorials/shaders/shader_2>`' in page

    def test_a_tutorial_in_another_path_is_found_where_it_is(self, page):
        assert ':doc:`first NeHe lesson </tutorials/nehe/nehe1>`' in page

    def test_a_role_written_by_hand_is_resolved_the_same_way(self, page):
        assert (
            ':doc:`Loading a glTF model </tutorials/core_context/loading_gltf_model>`'
        ) in page

    def test_a_page_above_the_tutorials_is_read_from_docs_tutorials(self, page):
        assert ':doc:`shadows page </shadows>`' in page

    def test_a_link_from_the_top_is_left_as_it_is(self, page):
        assert ':doc:`structure page </structure>`' in page


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
        from docutils import nodes  # noqa: PLC0415 the docs extra's, for this build alone
        from sphinx.application import Sphinx  # noqa: PLC0415 the docs extra's, for this build alone

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
    """The index lists the paths; each path has a page of its own listing its
    tutorials, so the sidebar carries a level for each path."""

    @pytest.fixture
    def shaders(self):
        return tutorials.TutorialPath(
            'Shaders', 'The shader path.', 'shaders', ['shader_1', 'gone']
        )

    def test_each_path_is_a_page_the_index_carries(self, shaders):
        page = tutorials.render_index([shaders], ['shaders/shader_1'])
        assert '.. toctree::\n   :hidden:\n\n   shaders/index' in page

    def test_each_path_is_described_where_it_is_linked(self, shaders):
        page = tutorials.render_index([shaders], ['shaders/shader_1'])
        assert ':doc:`Shaders <shaders/index>`\n   The shader path.' in page

    def test_a_path_with_nothing_written_is_not_listed(self, shaders):
        assert 'shaders' not in tutorials.render_index([shaders], [])

    def test_a_path_page_lists_its_tutorials(self, shaders):
        page = tutorials.render_path(shaders, ['shaders/shader_1'])
        assert page.startswith('.. _tutorials-shaders:\n\nShaders\n=======')
        assert 'The shader path.' in page
        assert '.. toctree::\n   :maxdepth: 1\n\n   shader_1' in page

    def test_a_script_that_is_not_there_is_not_listed(self, shaders):
        assert 'gone' not in tutorials.render_path(shaders, ['shaders/shader_1'])

    def test_a_path_can_open_with_a_page_written_by_hand(self):
        """A walkthrough belongs with the scripts it walks through."""
        physics = tutorials.TutorialPath(
            'Physics', 'x', 'physics', ['using_physics'],
            pages=['physics_getting_started'],
        )
        page = tutorials.render_path(physics, ['physics/using_physics'])
        assert '   physics_getting_started\n   using_physics' in page


class TestAPathIntroductionWrittenByHand:
    """``tests/tutorials/<path>/index.rst`` is the path's page in place of the
    generated one, for the background a reader wants before the first script."""

    INTRODUCTION = (
        'Shader Background\n'
        '=================\n\n'
        'Vertices go in; pixels come out.  See :doc:`shader_1` first.\n'
    )

    @pytest.fixture
    def shaders(self):
        return tutorials.TutorialPath(
            'Shaders', 'The shader path.', 'shaders', ['shader_1', 'shader_2']
        )

    def test_it_is_the_page_in_place_of_the_description(self, shaders):
        page = tutorials.render_path(
            shaders, ['shaders/shader_1'], introduction=self.INTRODUCTION
        )
        assert 'Vertices go in; pixels come out.' in page
        assert 'The shader path.' not in page

    def test_the_page_keeps_the_label_other_pages_link_to(self, shaders):
        page = tutorials.render_path(
            shaders, ['shaders/shader_1'], introduction=self.INTRODUCTION
        )
        assert page.startswith('.. _tutorials-shaders:\n\nShader Background')

    def test_a_label_the_page_declares_is_not_declared_again(self, shaders):
        page = tutorials.render_path(
            shaders,
            [],
            introduction='.. _tutorials-shaders:\n\nTitle\n=====\n\nText.\n',
        )
        assert page.count('.. _tutorials-shaders:') == 1

    def test_the_tutorials_are_listed_after_it_when_it_lists_none(self, shaders):
        page = tutorials.render_path(
            shaders, ['shaders/shader_1'], introduction=self.INTRODUCTION
        )
        assert page.rstrip().endswith('.. toctree::\n   :maxdepth: 1\n\n   shader_1')

    def test_a_list_the_page_makes_is_the_list(self, shaders):
        """Its author chose the order and the headings round it."""
        written = (
            'Title\n=====\n\nText.\n\n.. toctree::\n\n   shader_2\n   shader_1\n'
        )
        page = tutorials.render_path(
            shaders, ['shaders/shader_1', 'shaders/shader_2'], introduction=written
        )
        assert page.count('.. toctree::') == 1
        assert page.index('shader_2') < page.index('shader_1')

    def test_a_link_to_a_tutorial_is_found_wherever_the_tutorial_is(self, shaders):
        page = tutorials.render_path(
            shaders,
            ['shaders/shader_1'],
            introduction=self.INTRODUCTION,
            pages={'shader_1': 'tutorials/shaders/shader_1'},
        )
        assert ':doc:`/tutorials/shaders/shader_1`' in page

    def test_a_path_without_one_is_described_as_before(self, shaders):
        page = tutorials.render_path(shaders, ['shaders/shader_1'])
        assert 'The shader path.' in page


class TestWritingThemAll:
    @pytest.fixture
    def source(self, tmp_path):
        source = tmp_path / 'tutorials'
        (source / 'shaders').mkdir(parents=True)
        (source / 'shaders' / 'shader_1.py').write_text(SCRIPT, encoding='utf8')
        return source

    def test_every_named_script_gets_a_page_in_its_path(self, source, tmp_path):
        output = tmp_path / 'out'
        written = tutorials.write(
            output=str(output),
            source=str(source),
            paths=[tutorials.TutorialPath('Shaders', 'x', 'shaders', ['shader_1'])],
        )
        assert written == ['shaders/shader_1']
        assert (output / 'shaders' / 'shader_1.rst').is_file()
        assert (output / 'shaders' / 'index.rst').is_file()
        assert (output / 'index.rst').is_file()

    def test_an_index_beside_the_scripts_is_the_path_s_page(self, source, tmp_path):
        (source / 'shaders' / 'index.rst').write_text(
            'Background\n==========\n\nBefore you start.\n', encoding='utf8'
        )
        output = tmp_path / 'out'
        tutorials.write(
            output=str(output),
            source=str(source),
            paths=[tutorials.TutorialPath('Shaders', 'x', 'shaders', ['shader_1'])],
        )
        page = (output / 'shaders' / 'index.rst').read_text(encoding='utf8')
        assert 'Before you start.' in page
        assert '   shader_1' in page

    def test_a_script_named_index_is_refused(self, source, tmp_path):
        """Its page would be the path's page."""
        with pytest.raises(ValueError, match='index'):
            tutorials.write(
                output=str(tmp_path / 'out'),
                source=str(source),
                paths=[tutorials.TutorialPath('Shaders', 'x', 'shaders', ['index'])],
            )

    def test_a_page_says_where_its_script_is(self, source, tmp_path):
        output = tmp_path / 'out'
        tutorials.write(
            output=str(output),
            source=str(source),
            paths=[tutorials.TutorialPath('Shaders', 'x', 'shaders', ['shader_1'])],
        )
        page = (output / 'shaders' / 'shader_1.rst').read_text(encoding='utf8')
        assert '``tests/tutorials/shaders/shader_1.py``' in page

    def test_two_scripts_named_alike_are_refused(self, source, tmp_path):
        """Each page carries a label named for its script, and two would clash."""
        (source / 'other').mkdir()
        (source / 'other' / 'shader_1.py').write_text(SCRIPT, encoding='utf8')
        with pytest.raises(ValueError, match='shader_1'):
            tutorials.write(
                output=str(tmp_path / 'out'),
                source=str(source),
                paths=[
                    tutorials.TutorialPath('Shaders', 'x', 'shaders', ['shader_1']),
                    tutorials.TutorialPath('Other', 'x', 'other', ['shader_1']),
                ],
            )

    def test_a_missing_script_is_reported_rather_than_fatal(self, tmp_path, caplog):
        output = tmp_path / 'out'
        written = tutorials.write(
            output=str(output),
            source=str(tmp_path),
            paths=[tutorials.TutorialPath('Shaders', 'x', 'shaders', ['gone'])],
        )
        assert written == []
        assert 'no such tutorial script' in caplog.text

    def test_the_pages_written_by_hand_are_named_by_their_paths(self):
        assert 'physics/physics_getting_started.rst' in tutorials.hand_written()


class TestThePathsThemselves:
    """The paths name the scripts that are in the repository."""

    def test_every_named_script_is_there(self):
        missing = [
            script
            for path in tutorials.PATHS
            for script in path.sources()
            if not os.path.isfile(script)
        ]
        assert missing == []

    def test_every_script_in_a_path_s_directory_is_named(self):
        """A tutorial directory holds the tutorials and what they import."""
        unnamed = [
            os.path.join(path.directory, name)
            for path in tutorials.PATHS
            for name in os.listdir(os.path.join(tutorials.SOURCE, path.directory))
            if name.endswith('.py')
            and not name.startswith('_')
            and name[:-3] not in path.scripts
        ]
        assert unnamed == []

    def test_every_named_script_has_commentary_to_read(self):
        """``'''`` marks it; a script using ``\"\"\"`` documents as an empty page."""
        without = [
            script
            for path in tutorials.PATHS
            for script in path.sources()
            if not [
                piece
                for piece in tutorials.parse(script).pieces
                if piece.kind == 'commentary'
            ]
        ]
        assert without == []

    def test_no_script_is_in_two_paths(self):
        named = [name for path in tutorials.PATHS for name in path.scripts]
        assert len(named) == len(set(named))

    def test_every_picture_a_tutorial_shows_is_there(self):
        """A picture is committed beside the page that shows it."""
        missing = []
        for path in tutorials.PATHS:
            for name, script in zip(path.scripts, path.sources()):
                for piece in tutorials.parse(script).pieces:
                    if piece.kind != 'commentary':
                        continue
                    for url in markup.pictures(piece.text):
                        if not os.path.isfile(
                            os.path.join(tutorials.OUTPUT, path.directory, url)
                        ):
                            missing.append('%s: %s' % (name, url))
        assert missing == []

    def test_every_page_a_path_names_by_hand_is_there(self):
        missing = [
            page
            for page in tutorials.hand_written()
            if not os.path.isfile(os.path.join(tutorials.OUTPUT, page))
        ]
        assert missing == []


class TestEveryLinkedTutorialIsWritten:
    """A page that links ``tutorials/<path>/<name>`` links a page the build
    writes: one of :data:`tutorials.PATHS`, or a hand-written one."""

    def written(self):
        names = {'index'}
        for path in tutorials.PATHS:
            names.add('%s/index' % (path.directory,))
            names.update(
                '%s/%s' % (path.directory, name) for name in path.pages + path.scripts
            )
        return names

    def test_no_documentation_page_links_a_tutorial_nothing_writes(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        linked = set()
        for page in glob.glob(os.path.join(here, 'docs', '*.rst')):
            with open(page, encoding='utf-8') as handle:
                linked.update(re.findall(
                    r':doc:`(?:[^`<]*<)?/?tutorials/([A-Za-z0-9_/]+)>?`',
                    handle.read()))
        assert linked - self.written() == set()


class TestTheZonesPageListsTheReaders:
    def test_every_extension_the_engine_reads_in_a_zone_is_named(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, 'docs', 'zones.rst'),
                  encoding='utf-8') as handle:
            page = handle.read()
        start = page.index('The extensions the loader reads in a zone are')
        sentence = page[start:page.index('. ', start)]
        missing = [name for name in zoning.BUILTIN if name not in sentence]
        assert missing == []


class TestTheStructurePageNamesEveryPackage:
    def test_every_sub_package_has_a_row(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        root = os.path.join(here, 'OpenGLContext')
        with open(os.path.join(here, 'docs', 'structure.rst'),
                  encoding='utf-8') as handle:
            page = handle.read()
        packages = sorted(
            name for name in os.listdir(root)
            if os.path.isfile(os.path.join(root, name, '__init__.py'))
            and name not in ('tests',))
        assert [name for name in packages
                if '``%s``' % (name,) not in page] == []


class TestTheHookSchemaMatchesTheKinds:
    """``docs/extensions/schema/OGLC_hook.schema.json`` names every parameter
    each shipped kind reads, with the ranges the code holds it to."""

    def schema(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, 'docs', 'extensions', 'schema',
                               'OGLC_hook.schema.json'),
                  encoding='utf-8') as handle:
            return json.load(handle)['$defs']

    def test_every_shipped_kind_is_covered(self):
        described = {'water', 'mirror', 'cloth', 'fire', 'smoke', 'sparks'}
        assert set(hooks.BUILTIN) == described

    def test_the_cloth_parameters(self):
        from OpenGLContext.scenegraph.softnodes import CLOTH_PARAMETERS
        cloth = self.schema()['cloth']['properties']
        assert set(CLOTH_PARAMETERS) | {'kind', 'pinned', 'wind'} == set(cloth)

    def test_the_mirror_parameters_and_their_limits(self):
        mirror = self.schema()['mirror']['properties']
        assert set(PARAMETERS) <= set(mirror)
        for name, (low, high) in LIMITS.items():
            assert mirror[name].get('minimum') == low, name
            assert mirror[name].get('maximum') == high, name

    def test_the_particle_fields_and_their_ranges(self):
        particles = self.schema()['particles']['properties']
        assert set(particlehooks.FIELDS) | {'scale', 'density'} <= set(particles)
        for name, (low, high) in particlehooks.RANGES.items():
            assert particles[name].get('minimum') == low, name
            assert particles[name].get('maximum') == high, name
        assert particles['scale']['maximum'] == particlehooks.MULTIPLIER_MAXIMUM

    def test_the_water_parameters_and_styles(self):
        defs = self.schema()
        water = defs['water']['properties']
        assert {'style', 'material', 'medium', 'depth'} <= set(water)
        assert set(water['medium']['enum']) == set(medium.MEDIA)
        style = defs['waterStyle']['properties']
        assert set(style['style']['enum']) == set(gltf.STYLES)
        for name, (low, high) in gltf.STYLE_RANGES.items():
            assert style[name].get('minimum') == low, name
            assert style[name].get('maximum') == high, name
