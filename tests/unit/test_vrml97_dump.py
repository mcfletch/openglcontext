"""``VRML97Handler.dump`` writing to a path and to an open file."""
from typing import Any

from OpenGLContext.loaders.vrml97 import VRML97Handler
from OpenGLContext.scenegraph import basenodes


def _node() -> Any:
    return basenodes.Transform(
        DEF='Root',
        children=[basenodes.Shape(geometry=basenodes.Box(size=(1, 2, 3)))],
    )


class TestDump:
    def test_a_path_is_opened_and_written(self, tmp_path: Any) -> None:
        target = tmp_path / 'scene.wrl'
        text = VRML97Handler.dump(_node(), str(target))
        assert target.read_text() == text
        assert 'Transform' in text

    def test_an_open_file_is_left_open_for_its_owner(self, tmp_path: Any) -> None:
        """The caller's handle stays usable, so several nodes make one file."""
        target = tmp_path / 'scene.wrl'
        with open(target, 'w', encoding='utf-8') as handle:
            VRML97Handler.dump(_node(), handle)
            handle.write('\n')
            VRML97Handler.dump(_node(), handle)
        assert target.read_text().count('Transform') == 2
