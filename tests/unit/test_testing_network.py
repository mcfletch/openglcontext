"""Whether a remote asset can be had, asked without fetching it."""

import socket

import pytest

from OpenGLContext.loaders.resolver import cached_path
from OpenGLContext.testing import network


@pytest.fixture(autouse=True)
def no_remembered_hosts(monkeypatch):
    monkeypatch.setattr(network, '_HOSTS', {})


@pytest.fixture
def listening():
    """A port on this machine that accepts connections."""
    with socket.create_server(('127.0.0.1', 0)) as server:
        yield server.getsockname()[1]


@pytest.fixture
def closed():
    """A port on this machine that nothing is listening on."""
    with socket.create_server(('127.0.0.1', 0)) as server:
        port = server.getsockname()[1]
    return port


def test_a_host_that_answers_can_be_fetched_from(listening, tmp_path):
    url = 'http://127.0.0.1:%d/model.glb' % (listening,)
    assert network.unreachable(url, str(tmp_path)) is None


def test_a_host_that_does_not_answer_says_so(closed, tmp_path):
    url = 'http://127.0.0.1:%d/model.glb' % (closed,)
    reason = network.unreachable(url, str(tmp_path))
    assert reason.startswith('%s is not cached and cannot be fetched' % (url,))
    assert '127.0.0.1:%d' % (closed,) in reason


def test_a_cached_asset_needs_no_host(closed, tmp_path):
    url = 'http://127.0.0.1:%d/model.glb' % (closed,)
    with open(cached_path(url, str(tmp_path)), 'wb') as cached:
        cached.write(b'glTF')
    assert network.unreachable(url, str(tmp_path)) is None


def test_a_host_is_asked_once(listening, tmp_path, monkeypatch):
    asked = []
    real = network._connection_refused  # noqa: SLF001 wrapped to count the probes the module makes
    monkeypatch.setattr(network, '_connection_refused',
                        lambda host, port: asked.append((host, port)) or real(host, port))
    for name in ('a.glb', 'b.glb'):
        network.unreachable('http://127.0.0.1:%d/%s' % (listening, name), str(tmp_path))
    assert asked == [('127.0.0.1', listening)]


def test_the_port_follows_the_scheme(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(network, '_connection_refused',
                        lambda host, port: asked.append((host, port)))
    network.unreachable('https://example.invalid/a.glb', str(tmp_path))
    network.unreachable('http://example.invalid/a.glb', str(tmp_path))
    assert asked == [('example.invalid', 443), ('example.invalid', 80)]


def test_a_host_that_refused_is_asked_again_after_a_while(tmp_path, monkeypatch):
    """A blip early in a run does not skip every later test that needs the host."""
    answers = ['refused', None]
    monkeypatch.setattr(network, '_connection_refused',
                        lambda host, port: answers.pop(0))
    clock = [100.0]
    monkeypatch.setattr(network.time, 'monotonic', lambda: clock[0])
    url = 'http://example.invalid/model.glb'
    assert network.unreachable(url, str(tmp_path)) is not None
    assert network.unreachable(url, str(tmp_path)) is not None
    clock[0] += network.RETRY_SECONDS
    assert network.unreachable(url, str(tmp_path)) is None
    assert answers == []
