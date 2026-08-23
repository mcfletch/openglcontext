"""The error and fallback paths of the older scenegraph and loader modules.

These are the branches a user reaches once something has already gone wrong: an
``Inline`` whose URLs are all unreachable, a ``Timer`` registered against a
context with no time manager, a loader handed a file it cannot parse.  Each is
checked for the exception it raises and the message it carries, because a path
that reports the wrong thing sends whoever hits it after the wrong problem.
"""
import gzip
import io
import logging

import pytest

from OpenGLContext.events.timer import Timer
from OpenGLContext.loaders import base
from OpenGLContext.scenegraph.inline import Inline

URL = 'http://example.com/scene.wrl'


class NullTimeManagerContext:
    """A context that answers the time-manager query with nothing."""

    def getTimeManager(self):
        return None


class NoTimeManagerContext:
    """A context that does not answer the time-manager query at all."""


def test_inline_logs_when_no_url_loads(caplog):
    """A failed background load reports the node and the URLs it tried."""
    node = Inline()
    with caplog.at_level(logging.WARNING, logger='OpenGLContext.scenegraph.inline'):
        node.loadBackground([])
    messages = [record.getMessage() for record in caplog.records]
    assert any('Unable to load any scene' in message for message in messages), messages


@pytest.mark.parametrize('method', ['register', 'deregister'])
@pytest.mark.parametrize(
    'context', [NullTimeManagerContext(), NoTimeManagerContext()], ids=['null', 'missing']
)
def test_timer_without_time_manager_raises_valueerror(method, context):
    """Both ways of failing to find a time manager report the same kind of error."""
    timer = Timer()
    with pytest.raises(ValueError) as raised:
        getattr(timer, method)(context)
    assert type(context).__name__ in str(raised.value)


def _handler(result):
    """A handler whose parse returns ``result`` over an empty file."""

    class Handler(base.BaseHandler):
        def getData(self, baseURL, filename, file):
            return b''

        def parse(self, data, baseURL, filename, file, *args, **named):
            return result

    return Handler()


def test_base_handler_parse_is_abstract():
    """The un-overridden parse tells the sub-class author what is missing."""
    with pytest.raises(NotImplementedError) as raised:
        base.BaseHandler().parse(b'', URL, 'scene.wrl', None)
    assert 'parse' in str(raised.value)


def test_parse_failure_names_the_url():
    with pytest.raises(ValueError) as raised:
        _handler((False, None))(URL, 'scene.wrl', io.BytesIO(b''))
    assert str(raised.value) == 'Parse failure for url %s' % (URL,)


def test_null_document_names_the_url():
    with pytest.raises(ValueError) as raised:
        _handler((True, None))(URL, 'scene.wrl', io.BytesIO(b''))
    assert str(raised.value) == 'NULL results for url %s' % (URL,)


def test_null_document_is_logged_with_the_url(caplog):
    with caplog.at_level(logging.WARNING, logger='OpenGLContext.loaders.base'):
        with pytest.raises(ValueError):
            _handler((True, None))(URL, 'scene.wrl', io.BytesIO(b''))
    assert [record for record in caplog.records if URL in record.getMessage()]


def test_gzip_is_detected_and_expanded():
    """A gzipped scene file is recognised from its magic number and read back."""
    payload = b'#VRML V2.0 utf8\nGroup {}\n'
    stream = io.BytesIO(gzip.compress(payload))
    assert base.BaseHandler.isGzip(stream) is True
    assert stream.tell() == 0, 'isGzip must leave the read position where it found it'
    assert base.BaseHandler().getData(URL, 'scene.wrl.gz', stream) == payload


def test_plain_data_is_not_taken_for_gzip():
    payload = b'#VRML V2.0 utf8\nGroup {}\n'
    stream = io.BytesIO(payload)
    assert base.BaseHandler.isGzip(stream) is False
    assert base.BaseHandler().getData(URL, 'scene.wrl', stream) == payload


def test_gzipped_vrml97_file_loads(tmp_path):
    """A ``.wrl.gz`` scene reaches the parser expanded."""
    from OpenGLContext.loaders.loader import Loader

    source = b'#VRML V2.0 utf8\nGroup { children [ Shape { geometry Box {} } ] }\n'
    path = tmp_path / 'scene.wrl.gz'
    path.write_bytes(gzip.compress(source))
    scenegraph = Loader.load(str(path))
    assert scenegraph is not None
    assert len(scenegraph.children) == 1
