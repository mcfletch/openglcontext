"""The ``tutorial-code`` directive the generated walkthroughs are written in.

``code-block`` with an ``:indent:`` option: the columns a piece of code sits at
in its script, which docutils would otherwise strip.  ``docbuild.tutorials``
writes it; ``plans/SPHINX-DOCS.md`` describes why.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from docutils.nodes import Node
from docutils.parsers.rst import directives
from docutils.statemachine import StringList
from sphinx.application import Sphinx
from sphinx.directives.code import CodeBlock


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
        return super().run()


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive('tutorial-code', TutorialCode)
    return {
        'version': '1.0',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
