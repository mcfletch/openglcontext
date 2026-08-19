"""Laying captured frames out into a sheet, and the page that shows them."""
import os

import numpy as np
import pytest

from OpenGLContext import contactsheet


def frame(value=200, size=(6, 8)):
    return np.full(size + (3,), value, dtype='u1')


class TestTiling:
    def test_the_sheet_is_big_enough_for_what_is_on_it(self, tmp_path):
        path = str(tmp_path / 'sheet.png')
        contactsheet.tile(path, 'a title',
                          [('front', [frame(), frame()]),
                           ('side', [frame(), frame()])], ['0%', '50%'])
        from PIL import Image
        with Image.open(path) as sheet:
            width, height = sheet.size
        assert width >= contactsheet.GUTTER + 2 * 8
        assert height >= 2 * (6 + contactsheet.LABEL)

    def test_every_cell_lands_on_the_sheet(self, tmp_path):
        """A row of distinct frames comes out as distinct columns."""
        path = str(tmp_path / 'sheet.png')
        contactsheet.tile(path, 't', [('row', [frame(40), frame(220)])],
                          ['a', 'b'])
        from PIL import Image
        pixels = np.asarray(Image.open(path).convert('RGB'))
        values = {int(v) for v in np.unique(pixels)}
        assert 40 in values and 220 in values

    def test_it_answers_where_it_wrote(self, tmp_path):
        path = str(tmp_path / 'sheet.png')
        assert contactsheet.tile(path, 't', [('r', [frame()])], ['a']) == path

    def test_nothing_to_draw_is_an_error_rather_than_an_empty_file(self, tmp_path):
        with pytest.raises(SystemExit):
            contactsheet.tile(str(tmp_path / 'x.png'), 't', [('r', [])], [])


class TestTheIndexPage:
    def _sheets(self, directory, names):
        for name in names:
            contactsheet.tile(os.path.join(directory, name), name,
                              [('r', [frame()])], ['a'])
        return directory

    def test_it_lists_every_sheet_in_the_directory(self, tmp_path):
        out = self._sheets(str(tmp_path), ['a-walk.png', 'b-run.png'])
        text = open(contactsheet.index(out)).read()
        assert 'a-walk.png' in text and 'b-run.png' in text

    def test_sheets_are_grouped_by_what_they_are_of(self, tmp_path):
        out = self._sheets(str(tmp_path), ['a-walk.png', 'a-run.png',
                                           'b-run.png'])
        text = open(contactsheet.index(out)).read()
        assert text.count('<h1>') == 2

    def test_the_named_ones_come_first_in_their_group(self, tmp_path):
        out = self._sheets(str(tmp_path), ['a-walk.png', 'a-overview.png'])
        text = open(contactsheet.index(out, order=('overview',))).read()
        assert text.index('a-overview.png') < text.index('a-walk.png')

    def test_the_caption_and_title_are_the_caller_s(self, tmp_path):
        out = self._sheets(str(tmp_path), ['a-walk.png'])
        text = open(contactsheet.index(out, caption='look at this',
                                       title='My Review')).read()
        assert 'look at this' in text and '<title>My Review</title>' in text

    def test_a_directory_with_no_sheets_still_gets_a_page(self, tmp_path):
        page = contactsheet.index(str(tmp_path))
        assert os.path.exists(page) and '<h1>' not in open(page).read()
