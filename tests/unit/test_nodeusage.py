"""Which files use a scenegraph node: the three scanners, the index and the
section a node's API page carries."""

import textwrap

import pytest

from docbuild import nodeusage

NAMES = frozenset({'Box', 'Transform', 'Shape', 'TimeSensor'})


def python(source):
    return nodeusage.scan_python(textwrap.dedent(source), NAMES)


class TestPython:
    def test_a_name_imported_from_the_engine_is_a_use(self):
        found = python(
            '''
            from OpenGLContext.scenegraph.basenodes import Box

            shape = Box(size=(1, 1, 1))
            '''
        )
        assert found == {'Box': [4]}

    def test_every_line_a_node_is_used_on_is_kept(self):
        found = python(
            '''
            from vrml.x3d.nodes import Transform
            a = Transform()
            b = Transform()
            '''
        )
        assert found == {'Transform': [3, 4]}

    def test_an_aliased_import_is_the_node_it_names(self):
        found = python(
            '''
            from OpenGLContext.scenegraph.basenodes import Box as Cube
            Cube()
            '''
        )
        assert found == {'Box': [3]}

    def test_a_node_reached_through_a_module_is_a_use(self):
        found = python(
            '''
            from OpenGLContext.scenegraph import basenodes
            import OpenGLContext.scenegraph.basenodes as bn
            basenodes.Box()
            bn.Shape()
            '''
        )
        assert found == {'Box': [4], 'Shape': [5]}

    def test_a_name_from_another_package_is_not(self):
        assert python(
            '''
            from mylib import Box
            Box()
            '''
        ) == {}

    def test_a_local_name_the_node_happens_to_share_is_not(self):
        assert python(
            '''
            from OpenGLContext.scenegraph.basenodes import Shape
            Box = 4
            print(Box)
            '''
        ) == {}

    def test_a_star_import_binds_the_names_the_file_does_not_define(self):
        found = python(
            '''
            from OpenGLContext.scenegraph.basenodes import *
            class Shape: pass
            Box()
            Shape()
            '''
        )
        assert found == {'Box': [4]}

    def test_a_base_class_is_a_use(self):
        found = python(
            '''
            from OpenGLContext.scenegraph.basenodes import Transform
            class Spinner(Transform):
                pass
            '''
        )
        assert found == {'Transform': [3]}

    def test_the_import_itself_is_not(self):
        assert python('from OpenGLContext.scenegraph.basenodes import Box\n') == {}

    def test_a_node_named_in_a_string_or_comment_is_not(self):
        assert python(
            '''
            # Box
            """A Box."""
            x = "Box"
            '''
        ) == {}

    def test_a_file_that_is_not_python_is_no_use(self):
        assert nodeusage.scan_python('def (:', NAMES) == {}


class TestX3D:
    def test_each_element_is_a_use_on_its_line(self):
        found = nodeusage.scan_x3d(
            '<X3D>\n<Scene>\n  <Shape>\n    <Box/>\n  </Shape>\n</Scene>\n</X3D>\n',
            NAMES,
        )
        assert found == {'Shape': [3], 'Box': [4]}

    def test_an_attribute_value_is_not(self):
        assert nodeusage.scan_x3d('<X3D><Scene><Group DEF="Box"/></Scene></X3D>', NAMES) == {}

    def test_what_was_read_before_a_fault_is_kept(self):
        found = nodeusage.scan_x3d('<X3D>\n<Box/>\n<Shape>\n&nothing;\n', NAMES)
        assert found == {'Box': [2], 'Shape': [3]}


class TestClassicVRML:
    def scan(self, text):
        return nodeusage.scan_classic(text, NAMES)

    def test_a_node_is_a_name_before_a_brace(self):
        found = self.scan(
            '#VRML V2.0 utf8\nShape {\n  geometry Box { size 1 1 1 }\n}\n'
        )
        assert found == {'Shape': [2], 'Box': [3]}

    def test_a_def_name_is_not_the_node(self):
        assert self.scan('DEF Box Group { }') == {}

    def test_a_comment_is_not(self):
        assert self.scan('# Box {\nGroup { }') == {}

    def test_a_string_is_not(self):
        assert self.scan('Script { url "javascript: Box {" }') == {}

    def test_a_string_with_an_escaped_quote_ends_where_it_ends(self):
        found = self.scan('Script { url "a \\" b" }\nBox { }')
        assert found == {'Box': [2]}

    def test_a_brace_on_the_next_line_still_counts(self):
        assert self.scan('Box\n\n{\n}') == {'Box': [1]}

    def test_a_proto_declaration_is_not_a_use(self):
        assert self.scan('PROTO Box [ ] { Group { } }') == {}


class TestTheFilesOfAWorkspace:
    @pytest.fixture
    def workspace(self, tmp_path):
        (tmp_path / '.gitmodules').write_text(
            '[submodule "demo"]\n\tpath = demo\n\turl = git@github.com:someone/demo.git\n'
            '[submodule "website"]\n\tpath = website\n\turl = git@github.com:someone/website.git\n',
            encoding='utf8',
        )
        demo = tmp_path / 'demo'
        (demo / 'tests' / 'tutorials' / 'path').mkdir(parents=True)
        (demo / 'tests' / 'unit').mkdir()
        (demo / 'worlds').mkdir()
        (demo / 'tests' / 'tutorials' / 'path' / 'first.py').write_text(
            'from vrml.x3d.nodes import Box\nBox()\n', encoding='utf8'
        )
        (demo / 'tests' / 'unit' / 'test_x.py').write_text(
            'from vrml.x3d.nodes import Box\nBox()\n', encoding='utf8'
        )
        (demo / 'worlds' / 'a.x3d').write_text('<X3D><Box/></X3D>', encoding='utf8')
        (demo / 'worlds' / 'a.wrl').write_text('Box { }', encoding='utf8')
        (demo / 'worlds' / 'notes.txt').write_text('Box { }', encoding='utf8')
        (tmp_path / 'website').mkdir()
        (tmp_path / 'website' / 'a.wrl').write_text('Box { }', encoding='utf8')
        return tmp_path

    @pytest.fixture
    def index(self, workspace):
        return nodeusage.build(str(workspace), NAMES)

    def test_a_node_is_found_in_each_kind_of_file(self, index):
        paths = {use.path for use in index.uses('Box')}
        assert paths == {
            'tests/tutorials/path/first.py',
            'worlds/a.x3d',
            'worlds/a.wrl',
        }

    def test_a_package_that_implements_nodes_is_not_an_example(self, workspace):
        for where in ('OpenGLContext', 'src/vrml'):
            package = workspace / 'demo' / where
            package.mkdir(parents=True)
            (package / 'lib.py').write_text(
                'from vrml.x3d.nodes import Box\nBox()\n', encoding='utf8'
            )
        (workspace / 'demo' / 'OpenGLContext' / 'bin').mkdir()
        (workspace / 'demo' / 'OpenGLContext' / 'bin' / 'cmd.py').write_text(
            'from vrml.x3d.nodes import Box\nBox()\n', encoding='utf8'
        )
        paths = {use.path for use in nodeusage.build(str(workspace), NAMES).uses('Box')}
        assert 'OpenGLContext/bin/cmd.py' in paths
        assert 'OpenGLContext/lib.py' not in paths
        assert 'src/vrml/lib.py' not in paths

    def test_a_unit_test_is_not_an_example(self, index):
        assert 'tests/unit/test_x.py' not in {u.path for u in index.uses('Box')}

    def test_a_project_that_is_not_scanned_is_left_out(self, index):
        assert {u.project for u in index.uses('Box')} == {'demo'}

    def test_a_link_goes_to_the_line_on_the_project_s_page(self, index):
        use = next(u for u in index.uses('Box') if u.path.endswith('first.py'))
        assert use.lines == (2,)
        assert use.url == 'https://github.com/someone/demo/blob/main/tests/tutorials/path/first.py#L2'

    def test_a_tutorial_comes_before_a_world(self, index):
        assert index.uses('Box')[0].path == 'tests/tutorials/path/first.py'

    def test_a_node_nothing_uses_has_no_uses(self, index):
        assert index.uses('TimeSensor') == []


class TestTheSection:
    def uses(self, count):
        return [
            nodeusage.FileUse(
                project='demo',
                path='worlds/w%02d.x3d' % (n,),
                lines=(n + 1,),
                url='https://example/w%02d' % (n,),
                rank=4,
            )
            for n in range(count)
        ]

    def test_it_lists_each_file_with_the_lines_it_uses_the_node_on(self):
        blocks = nodeusage.section('Box', self.uses(1), tutorials=set())
        assert len(blocks) == 1
        assert blocks[0].startswith('.. rubric:: Where this node is used')
        assert '`demo: worlds/w00.x3d <https://example/w00>`__ (line 1)' in blocks[0]

    def test_a_long_list_is_cut_with_a_count_of_the_rest(self):
        text = nodeusage.section('Box', self.uses(15), tutorials=set())[0]
        assert 'w11' in text
        assert 'w12' not in text
        assert 'and 3 more files' in text

    def test_a_tutorial_script_links_its_walkthrough(self):
        use = nodeusage.FileUse(
            project='openglcontext',
            path='tests/tutorials/shaders/shader_1.py',
            lines=(4, 9),
            url='https://example/s',
            rank=0,
        )
        text = nodeusage.section('Box', [use], tutorials={'shaders/shader_1'})[0]
        assert ':doc:`walkthrough </tutorials/shaders/shader_1>`' in text
        assert '(lines 4, 9)' in text

    def test_a_script_that_is_not_a_tutorial_links_no_walkthrough(self):
        use = nodeusage.FileUse('openglcontext', 'tests/tutorials/s/_x.py', (1,), 'u', 0)
        assert 'walkthrough' not in nodeusage.section('Box', [use], tutorials=set())[0]

    def test_a_node_with_no_uses_has_no_section(self):
        assert nodeusage.section('Box', [], tutorials=set()) == []


class TestWhichClassesAreNodes:
    def test_the_class_the_document_names_is_a_node(self):
        from vrml.x3d import nodes

        assert nodeusage.node_name(nodes.Box) == 'Box'

    def test_an_engine_class_of_that_name_is_one(self):
        from OpenGLContext.scenegraph.box import Box

        assert nodeusage.node_name(Box) == 'Box'

    def test_a_class_that_is_not_a_node_is_not(self):
        assert nodeusage.node_name(dict) is None

    def test_a_subclass_under_a_name_of_its_own_is_not_that_node(self):
        from vrml.x3d import nodes

        class MyBox(nodes.Box):
            pass

        assert nodeusage.node_name(MyBox) is None

    def test_the_names_include_the_engine_s_and_x3d_s(self):
        names = nodeusage.node_names()
        assert {'Box', 'TimeSensor', 'Transform'} <= names

    def test_the_callable_for_the_api_pages_answers_blocks_for_a_used_node(self):
        from vrml.x3d import nodes

        index = nodeusage.Index()
        index.add(
            'Box',
            nodeusage.FileUse('demo', 'a.x3d', (2,), 'https://example/a', 4),
        )
        sections = nodeusage.class_sections(index, tutorials=set())
        assert 'a.x3d' in sections(nodes.Box)[0]
        assert sections(nodes.Transform) == []
        assert sections(dict) == []
