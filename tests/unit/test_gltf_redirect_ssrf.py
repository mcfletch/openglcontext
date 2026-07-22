"""Regression: glTF remote fetch re-checks origin on redirect (no network).

The same-origin guard validated only the pre-request URL; urllib then followed
3xx redirects without re-validating, so a same-origin URL that 302s to
169.254.169.254 defeated the check (an SSRF bypass). The fetch now uses an
opener whose redirect handler re-applies the same-origin policy on every hop.
These tests exercise that handler directly, without opening a socket.
"""
import email.message

import pytest

from OpenGLContext.loaders.resolver import _OriginLockedRedirectHandler
import urllib.error
import urllib.request


def _handler(base):
    return _OriginLockedRedirectHandler(base)


def _headers():
    return email.message.Message()


def test_cross_origin_redirect_is_refused():
    h = _handler('http://example.com/models/scene.gltf')
    req = urllib.request.Request('http://example.com/models/scene.gltf')
    with pytest.raises(urllib.error.HTTPError):
        h.redirect_request(req, None, 302, 'Found', _headers(),
                           'http://169.254.169.254/latest/meta-data/')


def test_scheme_downgrade_to_file_is_refused():
    h = _handler('http://example.com/a/scene.gltf')
    req = urllib.request.Request('http://example.com/a/scene.gltf')
    with pytest.raises(urllib.error.HTTPError):
        h.redirect_request(req, None, 302, 'Found', _headers(),
                           'file:///etc/passwd')


def test_cross_host_redirect_is_refused():
    h = _handler('https://cdn.example.com/scene.gltf')
    req = urllib.request.Request('https://cdn.example.com/scene.gltf')
    with pytest.raises(urllib.error.HTTPError):
        h.redirect_request(req, None, 301, 'Moved', _headers(),
                           'https://evil.example.net/scene.gltf')


def test_same_origin_redirect_is_allowed():
    # A same-origin redirect (e.g. path normalisation) still proceeds.
    h = _handler('http://example.com/a/scene.gltf')
    req = urllib.request.Request('http://example.com/a/scene.gltf')
    new = h.redirect_request(req, None, 302, 'Found', _headers(),
                             'http://example.com/a/real-scene.gltf')
    assert new is not None
    assert new.get_full_url() == 'http://example.com/a/real-scene.gltf'
