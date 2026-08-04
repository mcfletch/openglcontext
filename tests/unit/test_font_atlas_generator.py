"""What the font-atlas generator is allowed to write.

The atlases are committed as generated modules carrying a licence notice, so the
notice has to describe the font whose glyphs are actually in the image. A
generator that quietly substituted whatever monospace font a machine happened to
have would produce an atlas labelled with someone else's licence -- and several
of the fonts it might reach for (Consolas, Menlo) are not redistributable at all.

So: no DejaVu, no output. An explicitly chosen font is a deliberate override and
is allowed, but it does not inherit DejaVu's terms.
"""
import pytest

from scripts import generate_font_atlas as gen


class TestTheLicenceNoticeDescribesTheFontUsed:
    def test_dejavu_carries_the_dejavu_terms(self):
        notice = gen.license_notice('DejaVu Sans Mono')
        assert 'DejaVu Fonts License' in notice
        assert 'Bitstream Vera' in notice

    def test_another_font_does_not_claim_dejavu_terms(self):
        notice = gen.license_notice('LiberationMono-Regular')
        assert 'DejaVu' not in notice
        assert 'LiberationMono-Regular' in notice

    def test_another_font_says_its_licence_is_unverified(self):
        notice = gen.license_notice('consola')
        assert 'not been recorded' in notice.lower() or 'verify' in notice.lower()


class TestARunWithoutDejaVuWritesNothing:
    def test_it_exits_non_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gen, 'find_dejavu_font', lambda: None)
        with pytest.raises(SystemExit) as exit:
            gen.main(['--output-dir', str(tmp_path)])
        assert exit.value.code != 0

    def test_it_leaves_the_output_directory_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gen, 'find_dejavu_font', lambda: None)
        with pytest.raises(SystemExit):
            gen.main(['--output-dir', str(tmp_path)])
        assert list(tmp_path.glob('*.py')) == []

    def test_there_is_no_substitute_font_search(self):
        # The fallback chain is the mislabelling vector; it must not exist.
        assert not hasattr(gen, 'find_monospace_font')
