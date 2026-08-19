"""Unit tests for the contact-sheet tool's arithmetic and its page.

No GL: what is under test is which cells a sheet asks for, in what order, and
the index page it writes. The rendering itself is the ordinary viewer path and
is covered by the viewer's own tests.
"""
import os

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext import contactsheet
from OpenGLContext.bin import character_sheet as sheet_tool

from ._character_assets import character_glb


class _Model:
    """Enough of a CharacterModel for the planning to be exercised."""

    def __init__(self, names):
        self.clips = dict.fromkeys(names)


class TestPhases:
    def test_the_last_column_is_the_end(self):
        sheet = sheet_tool.CharacterSheet('x.glb', 'out', phases=5)
        assert sheet.phase(0) == 0.0
        assert sheet.phase(4) == 1.0

    def test_one_column_is_the_beginning(self):
        sheet = sheet_tool.CharacterSheet('x.glb', 'out', phases=1)
        assert sheet.phase(0) == 0.0

    def test_a_sheet_needs_at_least_one_column(self):
        assert sheet_tool.CharacterSheet('x.glb', 'out', phases=0).phases == 1


class TestClips:
    def test_all_of_them_by_default(self):
        sheet = sheet_tool.CharacterSheet('x.glb', 'out')
        assert sheet.clips_of(_Model(['walk', 'run'])) == ['walk', 'run']

    def test_only_the_ones_asked_for_in_the_order_asked(self):
        sheet = sheet_tool.CharacterSheet('x.glb', 'out', clips=['run', 'walk'])
        assert sheet.clips_of(_Model(['walk', 'run'])) == ['run', 'walk']

    def test_a_clip_the_model_has_not_got(self):
        sheet = sheet_tool.CharacterSheet('x.glb', 'out', clips=['sprint'])
        with pytest.raises(SystemExit) as raised:
            sheet.clips_of(_Model(['walk']))
        assert 'sprint' in str(raised.value)


class TestPlan:
    def test_every_cell_of_every_sheet_then_the_overview(self):
        sheet = sheet_tool.CharacterSheet('x.glb', 'out', phases=2)
        plan = sheet.plan(_Model(['walk']))
        views = len(sheet.views)
        assert len(plan) == views * 2 + views       # the sheet, then its row
        assert plan[0] == ('walk', 0.0, sheet.views[0][1])
        assert plan[1] == ('walk', 1.0, sheet.views[0][1])
        assert plan[-1] == ('walk', 0.35, sheet.views[-1][1])

    def test_the_clips_come_in_the_order_they_are_drawn(self):
        sheet = sheet_tool.CharacterSheet('x.glb', 'out', phases=1)
        plan = sheet.plan(_Model(['walk', 'run']))
        assert [clip for clip, _, _ in plan[:len(sheet.views)]] == ['walk'] * 4


class TestIndexPage:
    def _sheets(self, directory, names):
        for name in names:
            path = os.path.join(directory, name)
            contactsheet.tile(path, name,
                              [('front', [np.zeros((4, 4, 3), 'u1')])], ['0%'])
        return directory

    def test_lists_every_model_in_the_directory(self, tmp_path):
        out = self._sheets(str(tmp_path), ['a_character-walk.png',
                                           'a_character-overview.png',
                                           'b_character-run.png'])
        page = sheet_tool._index(out, 'a_character')
        text = open(page).read()
        assert 'a character' in text and 'b character' in text
        assert 'a_character-walk.png' in text and 'b_character-run.png' in text

    def test_the_overview_comes_first(self, tmp_path):
        out = self._sheets(str(tmp_path), ['a-walk.png', 'a-overview.png'])
        text = open(sheet_tool._index(out, 'a')).read()
        assert text.index('a-overview.png') < text.index('a-walk.png')


class TestHoldArguments:
    def test_a_point_and_a_model(self):
        options = sheet_tool.build_parser().parse_args(
            ['x.glb', '--hold', 'grip=gun.glb'])
        assert dict(item.split('=', 1) for item in options.hold) == {
            'grip': 'gun.glb'}


class TestAgainstARealModel:
    def test_the_clips_of_a_loaded_character(self):
        from OpenGLContext.character import CharacterModel
        model = CharacterModel.load(character_glb())
        sheet = sheet_tool.CharacterSheet('x.glb', 'out', phases=3)
        assert set(sheet.clips_of(model)) == {'raise', 'kick'}
        assert len(sheet.plan(model)) == 2 * len(sheet.views) * 3 \
            + 2 * len(sheet.views)


@pytest.mark.slow
class TestDrawingOne:
    """The tool end to end, through a real GL context.

    A subprocess because the tool takes the process's rendering environment and
    then owns the main loop: it is a command, and running it as one is the only
    way to see what it actually produces.
    """

    def test_writes_a_sheet_per_clip_and_an_index(self, tmp_path):
        import subprocess
        import sys
        model = tmp_path / 'figure.glb'
        model.write_bytes(character_glb())
        out = tmp_path / 'sheets'
        finished = subprocess.run(
            [sys.executable, '-m', 'OpenGLContext.bin.character_sheet',
             str(model), '--out', str(out), '--phases', '2', '--size', '64x64'],
            capture_output=True, text=True, timeout=180)
        assert finished.returncode == 0, finished.stderr[-2000:]
        written = sorted(path.name for path in out.iterdir())
        assert written == ['figure-kick.png', 'figure-overview.png',
                           'figure-raise.png', 'index.html']
