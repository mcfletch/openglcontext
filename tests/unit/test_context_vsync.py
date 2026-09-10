"""What ``setVSync`` answers before there is a definition to write it on.

``contextDefinition`` is a class attribute defaulting to ``None``; a context has
one from the moment ``Context.__init__`` resolves it, and one that has been
allocated but not initialised does not.  ``setVSync`` answers whether the wait
was applied, and "there was nothing to apply it to" is an answer a caller can act
on where an ``AttributeError`` is not.
"""
from OpenGLContext.context import Context


def test_a_context_with_no_definition_yet_answers_rather_than_raising():
    bare = Context.__new__(Context)
    assert bare.contextDefinition is None
    assert Context.setVSync(bare, False) is False
