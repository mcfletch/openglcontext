"""Names a tutorial's code imports, written as links to their reference pages.

``docbuild.codelinks`` reads a script's import statements and rewrites the
highlighted HTML of its code so each imported module, class and function
points at the page that documents it.  The Sphinx side, which resolves a name
to a page, is exercised in ``test_tutorial_extension.py``.
"""

import pytest
from sphinx.highlighting import PygmentsBridge

from docbuild import codelinks, tutorials


def highlighted(code: str) -> str:
    return PygmentsBridge('html', 'sphinx').highlight_block(code, 'python')


def everything(target: str) -> str:
    return '/ref/' + target


class TestImports:
    def test_from_import_binds_the_name_under_its_module(self):
        found = codelinks.imports('from x.y.z import q\n')
        assert found.names == {'q': 'x.y.z.q'}

    def test_an_alias_is_the_name_the_code_uses(self):
        found = codelinks.imports('from x.y import Context as BaseContext\n')
        assert found.names == {'BaseContext': 'x.y.Context'}

    def test_the_name_before_an_alias_is_kept_for_the_import_that_writes_it(self):
        found = codelinks.imports('from x.y import Context as BaseContext\n')
        assert found.originals == {'Context': 'x.y.Context'}

    def test_import_binds_the_first_package_of_a_dotted_name(self):
        found = codelinks.imports('import os.path\n')
        assert found.names == {'os': 'os'}

    def test_import_as_binds_the_whole_module_under_the_alias(self):
        found = codelinks.imports('import os.path as osp\n')
        assert found.names == {'osp': 'os.path'}

    def test_an_import_inside_a_block_is_read(self):
        found = codelinks.imports(
            'import typing\nif typing.TYPE_CHECKING:\n    from a.b import C\n'
        )
        assert found.names == {'typing': 'typing', 'C': 'a.b.C'}

    def test_a_relative_import_names_nothing_absolute(self):
        assert codelinks.imports('from . import sibling\n').names == {}

    def test_a_star_import_is_kept_as_its_module(self):
        found = codelinks.imports('from OpenGL.GL import *\n')
        assert found.names == {}
        assert found.stars == ('OpenGL.GL',)


class TestStarImports:
    def test_a_name_the_module_exports_is_under_that_module(self):
        found = codelinks.Imports(stars=('OpenGL.GL',))
        assert found.target('glClear') == 'OpenGL.GL.glClear'

    def test_a_name_the_module_lacks_is_not_a_target(self):
        found = codelinks.Imports(stars=('OpenGL.GL',))
        assert found.target('NotAnOpenGLName') is None

    def test_a_private_name_is_not_exported_by_a_star(self):
        found = codelinks.Imports(stars=('OpenGLContext.loaders.gltf.samples',))
        assert found.target('_catalogue_cache') is None

    def test_an_explicit_import_outranks_a_star(self):
        found = codelinks.Imports(
            names={'glClear': 'mine.glClear'}, stars=('OpenGL.GL',)
        )
        assert found.target('glClear') == 'mine.glClear'

    def test_a_star_module_that_will_not_import_exports_nothing(self):
        found = codelinks.Imports(stars=('no_such_package_anywhere',))
        assert found.target('anything') is None


class TestCandidates:
    def test_the_name_as_written_comes_first(self):
        assert codelinks.candidates('OpenGLContext.context.Context')[0] == (
            'OpenGLContext.context.Context'
        )

    def test_a_re_exported_function_names_the_module_that_defines_it(self):
        found = codelinks.candidates('OpenGLContext.loaders.gltf.sample_model_url')
        assert found == [
            'OpenGLContext.loaders.gltf.sample_model_url',
            'OpenGLContext.loaders.gltf.samples.sample_model_url',
        ]

    def test_a_module_is_its_own_name(self):
        assert codelinks.candidates('OpenGLContext.loaders.gltf') == [
            'OpenGLContext.loaders.gltf'
        ]

    def test_a_name_that_will_not_import_has_only_the_written_form(self):
        assert codelinks.candidates('not_a_package.Thing') == ['not_a_package.Thing']

    def test_a_constant_has_only_the_written_form(self):
        assert codelinks.candidates('OpenGL.GL.GL_TRIANGLES') == [
            'OpenGL.GL.GL_TRIANGLES'
        ]


class TestLinkCode:
    def link(self, code: str, resolve=everything) -> str:
        return codelinks.link_code(
            highlighted(code), codelinks.imports(code), resolve
        )

    def test_each_package_of_a_module_path_links_to_its_own_page(self):
        html = self.link('from x.y.z import q\n')
        assert (
            '<a class="code-link" href="/ref/x"><span class="nn">x</span></a>'
            '<span class="nn">.</span>'
            '<a class="code-link" href="/ref/x.y"><span class="nn">y</span></a>'
            '<span class="nn">.</span>'
            '<a class="code-link" href="/ref/x.y.z"><span class="nn">z</span></a>'
        ) in html

    def test_the_imported_name_links_to_the_page_for_it(self):
        html = self.link('from x.y.z import q\n')
        assert (
            '<a class="code-link" href="/ref/x.y.z.q"><span class="n">q</span></a>'
        ) in html

    def test_the_name_an_alias_stands_for_links_where_the_import_writes_it(self):
        html = self.link('from x.y import Context as Base\nContext\n')
        assert '<a class="code-link" href="/ref/x.y.Context"><span class="n">Context</span></a> <span class="k">as</span>' in html
        assert html.count('href="/ref/x.y.Context"') == 2  # the original and the alias

    def test_the_name_an_alias_stands_for_is_not_bound_outside_the_import(self):
        html = self.link('from x.y import Context as Base\nContext\n')
        assert html.endswith('<span class="n">Context</span>\n</pre></div>\n')

    def test_a_later_use_of_the_name_links_the_same_way(self):
        html = self.link('from x import Shape\nShape()\n')
        assert html.count('href="/ref/x.Shape"') == 2

    def test_an_attribute_that_shares_a_name_is_not_a_use_of_it(self):
        html = self.link('from x import Shape\nself.Shape\n')
        assert html.count('href="/ref/x.Shape"') == 1

    def test_the_alias_in_an_import_links_to_what_it_names(self):
        html = self.link('import os.path as osp\nosp.join\n')
        assert html.count('href="/ref/os.path"') == 3

    def test_a_name_that_resolves_to_nothing_is_left_as_it_was(self):
        code = 'from x import Shape\n'
        assert self.link(code, lambda target: None) == highlighted(code)

    def test_a_name_inside_a_string_or_comment_is_left_alone(self):
        code = 'from x import Shape\n"Shape"\n# Shape\n'
        assert self.link(code).count('href="/ref/x.Shape"') == 1

    def test_a_star_imported_name_links_to_its_module(self):
        code = 'from OpenGL.GL import *\nglClear(0)\n'
        html = self.link(code)
        assert 'href="/ref/OpenGL.GL.glClear"' in html

    def test_a_relative_module_is_not_linked(self):
        code = 'from .sibling import q\n'
        assert 'href="/ref/sibling"' not in self.link(code)

    def test_the_resolver_is_asked_once_for_a_target_a_page_repeats(self):
        asked: list[str] = []

        def resolve(target: str) -> str:
            asked.append(target)
            return '/ref/' + target

        self.link('from x import Shape\nShape()\nShape()\n', resolve)
        assert asked.count('x.Shape') == 1


class TestTutorialPage:
    def test_a_tutorial_carries_the_imports_of_its_script(self, tmp_path):
        script = tmp_path / 'demo.py'
        script.write_text(
            "'''=Demo=\n\nWords.\n'''\nfrom a.b import C\nfrom d import *\nC()\n"
        )
        tutorial = tutorials.parse(str(script))
        assert tutorial.imports.names == {'C': 'a.b.C'}
        assert tutorial.imports.stars == ('d',)

    def test_the_page_declares_them_before_its_first_code_block(self, tmp_path):
        script = tmp_path / 'demo.py'
        script.write_text(
            "'''=Demo=\n\nWords.\n'''\nfrom a.b import C\nfrom d import *\nC()\n"
        )
        page = tutorials.render(tutorials.parse(str(script)))
        declaration = (
            '.. tutorial-imports::\n\n'
            '   C a.b.C\n'
            '   * d\n'
        )
        assert declaration in page
        assert page.index(declaration) < page.index('.. tutorial-code::')

    def test_a_script_with_no_imports_declares_nothing(self, tmp_path):
        script = tmp_path / 'demo.py'
        script.write_text("'''=Demo=\n\nWords.\n'''\nx = 1\n")
        page = tutorials.render(tutorials.parse(str(script)))
        assert 'tutorial-imports' not in page

    @pytest.mark.parametrize('line', ['C a.b.C', '* d', 'B a.b.B as'])
    def test_the_declaration_reads_back_as_the_imports_it_was_made_from(self, line):
        imports = codelinks.Imports(
            names={'C': 'a.b.C'}, stars=('d',), originals={'B': 'a.b.B'}
        )
        assert line in codelinks.declare(imports).splitlines()
        assert codelinks.read_declaration(codelinks.declare(imports)) == imports
