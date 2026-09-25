"""The screen a player downloads content on.

Driven with a real :class:`~OpenGLContext.contentpacks.fetch.FetchJob` whose
fetch is a function here, so what is checked is the screen over the job the
engine runs: the offer, the bar and its words, Stop, and each way a download
ends. No GL.
"""

import threading

import pytest

from OpenGLContext.contentpacks.fetch import Cancelled, FetchJob
from OpenGLContext.contentpacks.pack import ContentPack
from OpenGLContext.ui import contentscreen
from OpenGLContext.ui.contentscreen import ContentScreen
from OpenGLContext.ui.metrics import FontMetrics


def a_pack(key, title, size=2_000_000, **extra):
    fields = dict(key='racer/%s' % (key,), title=title,
                  url='https://example.invalid/%s.tar.gz' % (key,),
                  directory=key, archive='tar', approximate_bytes=size,
                  copyright='%s by somebody, CC-BY 4.0' % (title,),
                  marker='x')
    fields.update(extra)
    return ContentPack(**fields)


ART = a_pack('art', 'Forest art', 30_000_000)
ASHDOWN = a_pack('ashdown', 'Ashdown', 22_000_000, notes='A lap of hills.',
                 needs=('racer/art',))
BEACON = a_pack('beacon', 'Beacon', 10_000_000, needs=('racer/art',))


def wanted(pack):
    return [pack] + ([ART] if pack.needs else [])


class Gate:
    """A fetch that waits to be let through, or fails, or notices a stop."""

    def __init__(self, fail=None):
        self.go = threading.Event()
        self.fail = fail

    def __call__(self, pack, progress, cancel):
        progress(pack.approximate_bytes // 2, pack.approximate_bytes)
        while not self.go.wait(0.01):
            if cancel():
                raise Cancelled('stopped')
        if self.fail is not None:
            raise self.fail
        return '/content/%s' % (pack.directory,)


def finish(screen):
    screen.job._thread.join(timeout=10)
    screen.poll()


@pytest.fixture
def gate():
    return Gate()


@pytest.fixture
def screen(gate):
    finished = []
    made = ContentScreen(
        [ASHDOWN, BEACON], wanted=wanted,
        on_fetch=lambda pack: FetchJob(wanted(pack), store=None, fetch=gate),
        on_finished=finished.append)
    made.finished = finished
    yield made
    gate.go.set()


class TestTheOffer:
    def test_the_size_is_the_whole_set_the_choice_fetches(self, screen):
        assert screen.caption.text.startswith('Ashdown — 52 MB')

    def test_what_comes_with_it_is_named(self, screen):
        assert 'with Forest art — 30 MB' in screen.caption.text

    def test_the_terms_of_everything_in_the_set_are_shown(self, screen):
        assert ASHDOWN.copyright in screen.caption.text
        assert ART.copyright in screen.caption.text

    def test_choosing_another_describes_that_one(self, screen):
        screen.chooser.write('racer/beacon')
        assert screen.caption.text.startswith('Beacon — 40 MB')

    def test_nothing_on_offer_says_so_and_offers_no_download(self):
        screen = ContentScreen([])
        assert screen.caption.text == contentscreen.ALL_HERE
        assert not screen.fetch_button.enabled

    def test_a_set_offered_together_is_one_choice(self):
        screen = ContentScreen([ART, BEACON], together=True)
        assert screen.whole() == [ART, BEACON]
        assert screen.caption.text.startswith('Forest art — 40 MB')

    def test_a_new_offer_keeps_the_choice_where_it_is_still_there(
            self, screen):
        screen.chooser.write('racer/beacon')
        screen.offer([BEACON])
        assert screen.chosen() is BEACON
        screen.offer([ASHDOWN])
        assert screen.chosen() is ASHDOWN

    def test_it_lays_out_inside_a_window(self):
        screen = ContentScreen([ASHDOWN, BEACON], wanted=wanted)
        screen.panel.layout((800, 600), FontMetrics(char_width=8,
                                                    char_height=16,
                                                    line_gap=2))
        for name in ('fetch', 'stop', 'close', 'progress', 'offer'):
            widget = screen.panel.find(name)
            assert screen.panel.rect.contains(widget.rect.x, widget.rect.y)


class TestADownload:
    def test_download_starts_the_job_for_the_choice(self, screen, gate):
        screen.fetch_button.on_activate(screen.fetch_button)
        assert screen.running
        assert screen.job.packs == [ASHDOWN, ART]

    def test_while_it_runs_it_can_be_stopped_and_not_started_again(
            self, screen):
        screen.fetch_button.on_activate(screen.fetch_button)
        assert screen.stop_button.enabled
        assert not screen.fetch_button.enabled

    def test_the_bar_and_its_words_follow_the_job(self, screen, gate):
        screen.fetch_button.on_activate(screen.fetch_button)
        for _ in range(200):
            screen.poll()
            if screen.progress.fraction > 0:
                break
            screen.job._thread.join(timeout=0.01)
        assert 0 < screen.progress.fraction < 1
        assert screen.progress.text.startswith('Ashdown — ')

    def test_one_that_arrives_says_done(self, screen, gate):
        screen.fetch_button.on_activate(screen.fetch_button)
        gate.go.set()
        finish(screen)
        assert screen.progress.text == contentscreen.DONE
        assert screen.fetch_button.enabled and not screen.stop_button.enabled
        assert screen.finished == [screen.job]

    def test_one_that_failed_says_why_and_stays_said(self, screen):
        failing = Gate(fail=IOError('the server said 404'))
        screen.on_fetch = lambda pack: FetchJob(wanted(pack), store=None,
                                                fetch=failing)
        screen.fetch_button.on_activate(screen.fetch_button)
        failing.go.set()
        finish(screen)
        assert screen.progress.text == \
            'Could not download: the server said 404'
        screen.poll()
        assert screen.progress.text.endswith('404')

    def test_one_the_player_stopped_is_not_called_a_failure(self, screen):
        screen.fetch_button.on_activate(screen.fetch_button)
        screen.stop_button.on_activate(screen.stop_button)
        finish(screen)
        assert screen.progress.text == contentscreen.STOPPED

    def test_the_end_is_reported_once(self, screen, gate):
        screen.fetch_button.on_activate(screen.fetch_button)
        gate.go.set()
        finish(screen)
        screen.poll()
        screen.poll()
        assert len(screen.finished) == 1

    def test_a_caller_that_starts_nothing_leaves_the_screen_idle(self):
        screen = ContentScreen([ASHDOWN], on_fetch=lambda pack: None)
        screen.fetch_button.on_activate(screen.fetch_button)
        assert screen.job is None and screen.fetch_button.enabled


class TestClosing:
    def test_close_closes_it_and_says_so_once(self):
        closed = []
        screen = ContentScreen([ASHDOWN], on_close=lambda: closed.append(1))
        screen.close_button.on_activate(screen.close_button)
        screen.panel.key('<escape>', (0, 0, 0))
        assert screen.panel.closed
        assert closed == [1]

    def test_escape_closes_it(self):
        closed = []
        screen = ContentScreen([ASHDOWN], on_close=lambda: closed.append(1))
        screen.panel.key('<escape>', (0, 0, 0))
        assert screen.panel.closed and closed == [1]


class TestTheWords:
    def test_no_job_says_nothing(self):
        assert contentscreen.progress_text(None) == ''

    def test_no_pack_is_everything_here(self):
        assert contentscreen.offer_text(None) == contentscreen.ALL_HERE
