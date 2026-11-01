"""The directives the generated walkthroughs are written in.

``tutorial-code`` is ``code-block`` with an ``:indent:`` option: the columns a
piece of code sits at in its script, which docutils would otherwise strip.
``tutorial-imports`` carries the names the script imports, and the HTML writer
uses them to turn each imported module, class and function in the code into a
link to the page that documents it (``docbuild.codelinks``).
``docbuild.tutorials`` writes both; ``plans/SPHINX-DOCS.md`` describes why.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from docbuild import codelinks
from docutils import nodes
from docutils.nodes import Node
from docutils.parsers.rst import Directive, directives
from docutils.statemachine import StringList
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.directives.code import CodeBlock
from sphinx.errors import NoUri
from sphinx.util.docutils import SphinxTranslator
from sphinx.writers.html5 import HTML5Translator

#: The document attribute ``tutorial-imports`` leaves its declaration in.
IMPORTS = 'tutorial_imports'


class tutorial_literal_block(nodes.literal_block):
    """A tutorial's code, written with its imported names as links."""


class TutorialImports(Directive):
    """The names the page's script imports, for its code to link to."""

    has_content = True

    def run(self) -> list[Node]:
        self.state.document[IMPORTS] = '\n'.join(self.content)
        return []


class TutorialCode(CodeBlock):
    """``code-block``, shown at the indent the code has in its script."""

    option_spec: ClassVar[dict[str, Callable[[str], Any]]] = dict(CodeBlock.option_spec, indent=directives.nonnegative_int)
    content: StringList

    def run(self) -> list[Node]:
        prefix = ' ' * self.options.get('indent', 0)
        if prefix:
            self.content = StringList(
                [prefix + line if line.strip() else line for line in self.content],
                items=self.content.items,
            )
        return [
            _tutorial_block(node) if isinstance(node, nodes.literal_block) else node
            for node in super().run()
        ]


def _tutorial_block(block: nodes.literal_block) -> tutorial_literal_block:
    return tutorial_literal_block(
        block.rawsource, block.astext(), **block.attributes
    )


def _address(translator: HTML5Translator, dotted: str) -> str | None:
    """Where the page for ``dotted`` is, relative to the page being written.

    The Python domain answers for what these pages document; the intersphinx
    inventories (PyOpenGL's, the standard library's) answer for the rest.
    """
    env = translator.builder.env
    docname = translator.builder.current_docname
    request = addnodes.pending_xref(
        '',
        nodes.Text(dotted),
        refdomain='py',
        reftype='obj',
        reftarget=dotted,
        refexplicit=False,
    )
    content = nodes.literal(dotted, dotted)
    reference = env.get_domain('py').resolve_xref(
        env, docname, translator.builder, 'obj', dotted, request, content
    )
    if reference is None:
        reference = env.events.emit_firstresult(
            'missing-reference', env, request, content, allowed_exceptions=(NoUri,)
        )
    if reference is None:
        return None
    return str(reference.get('refuri') or '#' + reference['refid'])


def _resolver(translator: HTML5Translator) -> Callable[[str], str | None]:
    """The function :func:`docbuild.codelinks.link_code` finds pages with."""

    def resolve(dotted: str) -> str | None:
        # A name is looked up as the code wrote it before its module is
        # imported to learn where it is defined.
        found = _address(translator, dotted)
        if found is not None:
            return found
        for other in codelinks.candidates(dotted)[1:]:
            found = _address(translator, other)
            if found is not None:
                return found
        return None

    return resolve


def visit_html(self: HTML5Translator, node: tutorial_literal_block) -> None:
    """Highlight the code as ``code-block`` does, with its names linked."""
    highlighted = self.highlighter.highlight_block(
        node.rawsource,
        node.get('language', 'python'),
        opts=self.config.highlight_options.get(node.get('language', 'python'), {}),
        location=node,
    )
    linked = codelinks.link_code(
        highlighted,
        codelinks.read_declaration(node.document.get(IMPORTS, '')),
        _resolver(self),
    )
    starttag = self.starttag(
        node, 'div', suffix='', CLASS='highlight-python notranslate'
    )
    self.body.append(starttag + linked + '</div>\n')
    raise nodes.SkipNode


def visit_plain(self: SphinxTranslator, node: tutorial_literal_block) -> None:
    """Every other writer shows the code as any literal block."""
    self.visit_literal_block(node)


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive('tutorial-code', TutorialCode)
    app.add_directive('tutorial-imports', TutorialImports)
    app.add_node(
        tutorial_literal_block,
        html=(visit_html, None),
        latex=(visit_plain, None),
        text=(visit_plain, None),
        man=(visit_plain, None),
        texinfo=(visit_plain, None),
    )
    return {
        'version': '1.0',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
