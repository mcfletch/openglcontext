"""Where a download may be redirected to.

A document's own references are held to the document's origin, redirects
included. A content pack is different: its URL comes from a registry the
application trusts, its integrity is its digest, and the hosts that serve
release assets answer every request with a redirect to a CDN on another host.
Content downloads therefore follow redirects to any public host, and still
refuse a redirect that leaves http(s), that downgrades https to plaintext, or
that reaches a private, loopback or link-local address from a public one.

Two real servers on this machine carry the end-to-end case; the address rules
are checked on literal addresses, which need no DNS.
"""

import functools
import http.server
import threading
import urllib.error

import pytest

from OpenGLContext.loaders import resolver


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        """A suite is not a place for a request log."""


def _redirecting_to(target_base):
    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header(
                'Location',
                target_base + self.path + '?sig=SECRET&jwt=TOKEN')
            self.end_headers()

        def log_message(self, *args):
            """Quiet."""
    return Redirect


def _serve(handler):
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, 'http://127.0.0.1:%d' % (server.server_address[1],)


@pytest.fixture
def two_hosts(tmp_path):
    """A file server, and a second server that redirects everything to it.

    Two ports on one address are two origins, which is what a release host and
    its CDN are.
    """
    where = tmp_path / 'cdn'
    where.mkdir()
    (where / 'pack.tar.gz').write_bytes(b'the content')
    cdn, cdn_thread, cdn_base = _serve(functools.partial(_Quiet,
                                                         directory=str(where)))
    front, front_thread, front_base = _serve(_redirecting_to(cdn_base))
    try:
        yield front_base, cdn_base
    finally:
        for server, thread in ((front, front_thread), (cdn, cdn_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class TestAReleaseAssetRedirectedToItsCDN:
    def test_content_follows_the_redirect_to_another_host(self, two_hosts,
                                                          tmp_path):
        front, _ = two_hosts
        path = resolver.fetch_to_cache(front + '/pack.tar.gz',
                                       cache_dir=str(tmp_path / 'cache'),
                                       redirects=resolver.PUBLIC_HOSTS)
        with open(path, 'rb') as handle:
            assert handle.read() == b'the content'

    def test_a_document_fetch_still_refuses_it(self, two_hosts, tmp_path):
        """The same-origin lock stays the default."""
        front, _ = two_hosts
        with pytest.raises(urllib.error.HTTPError):
            resolver.fetch_to_cache(front + '/pack.tar.gz',
                                    cache_dir=str(tmp_path / 'cache'))

    def test_the_refusal_does_not_carry_the_signed_query(self, two_hosts,
                                                         tmp_path):
        """A CDN's redirect is signed; the signature is not for a log."""
        front, _ = two_hosts
        with pytest.raises(urllib.error.HTTPError) as caught:
            resolver.fetch_to_cache(front + '/pack.tar.gz',
                                    cache_dir=str(tmp_path / 'cache'))
        assert 'SECRET' not in str(caught.value)
        assert 'TOKEN' not in str(caught.value)
        assert 'SECRET' not in str(caught.value.filename)


class TestWhereARedirectMayGo:
    policy = resolver.PUBLIC_HOSTS
    public = 'https://github.com/owner/repo/releases/download/v1/a.tar.gz'

    @pytest.mark.parametrize('target', [
        'https://185.199.108.133/asset',
        'https://[2606:50c0:8000::154]/asset',
    ])
    def test_a_public_https_host_is_followed(self, target):
        assert self.policy.refusal(self.public, target) is None

    @pytest.mark.parametrize('target', [
        'https://10.0.0.1/asset',
        'https://192.168.1.1/asset',
        'https://169.254.169.254/latest/meta-data/',
        'https://127.0.0.1/asset',
        'https://[::1]/asset',
        'https://[::ffff:10.0.0.1]/asset',
        'https://0.0.0.0/asset',
    ])
    def test_a_private_address_is_refused_from_a_public_one(self, target):
        assert self.policy.refusal(self.public, target)

    def test_plaintext_is_refused(self):
        assert self.policy.refusal(self.public, 'http://185.199.108.133/a')

    @pytest.mark.parametrize('target', ['file:///etc/passwd',
                                        'ftp://185.199.108.133/a',
                                        'data:,x'])
    def test_another_scheme_is_refused(self, target):
        assert self.policy.refusal(self.public, target)

    def test_loopback_to_loopback_is_followed(self):
        """A mirror or a test server on this machine redirecting to itself."""
        assert self.policy.refusal('http://127.0.0.1:8000/a',
                                   'http://127.0.0.1:9000/a') is None

    def test_loopback_may_not_reach_the_local_network(self):
        assert self.policy.refusal('http://127.0.0.1:8000/a',
                                   'http://10.0.0.1/a')

    def test_a_host_that_does_not_resolve_is_refused(self):
        assert self.policy.refusal(self.public,
                                   'https://no-such-host.invalid/a')

    def test_same_origin_policy_refuses_another_host(self):
        assert resolver.SAME_ORIGIN.refusal(
            self.public, 'https://objects.githubusercontent.com/a')
        assert resolver.SAME_ORIGIN.refusal(self.public, self.public) is None


class TestWhatAFetchWillOpen:
    """`fetch_url` is a network primitive; a local file is not its business."""

    @pytest.mark.parametrize('url', ['file:///etc/hostname', 'data:,x',
                                     'ftp://example.invalid/a'])
    def test_a_scheme_other_than_http_is_refused(self, url, tmp_path):
        with pytest.raises(IOError):
            resolver.fetch_url(url, cache_dir=str(tmp_path))
        assert not list(tmp_path.iterdir()), 'something was cached'


class TestAServiceThatNamesItsHosts:
    """A catalogue publishes from hosts known in advance, and every hop of a
    download it names is held to them, not only the URL it answered with."""

    policy = resolver.AllowedHosts(('api.polyhaven.com', 'dl.polyhaven.org'))
    asked = 'https://api.polyhaven.com/files/fern_02'

    def test_a_hop_to_a_named_host_is_followed(self):
        assert self.policy.refusal(
            self.asked, 'https://dl.polyhaven.org/file/fern_02.gltf') is None

    @pytest.mark.parametrize('target', [
        'https://evil.example/payload',
        'https://dl.polyhaven.org.example/payload',
        'http://dl.polyhaven.org/file/fern_02.gltf',
        'https://dl.polyhaven.org:8443/file/fern_02.gltf',
        'https://169.254.169.254/latest/meta-data/',
        'file:///etc/passwd',
    ])
    def test_a_hop_anywhere_else_is_refused(self, target):
        assert self.policy.refusal(self.asked, target)

    def test_a_download_redirected_off_the_list_is_refused(self, two_hosts):
        front, _ = two_hosts
        with pytest.raises(urllib.error.HTTPError):
            resolver.open_url(front + '/pack.tar.gz',
                              redirects=resolver.AllowedHosts(('127.0.0.1',)))

    def test_the_caller_names_itself(self):
        """A service that refuses anonymous clients is told who is asking."""
        heard = []

        class Recording(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                heard.append(self.headers['User-Agent'])
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'ok')

            def log_message(self, *args):
                """Quiet."""
        server, thread, base = _serve(Recording)
        try:
            with resolver.open_url(base + '/a', agent='Tester/1') as found:
                assert found.read() == b'ok'
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        assert heard == ['Tester/1']
