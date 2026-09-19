"""A URL that arrived in a response is still a URL somebody else chose.

A loader that asks a catalogue where an asset lives gets a URL back and fetches
it. That answer is data: it comes over the wire, and a service that is
compromised, misconfigured, or simply wrong can put anything in it -- a
``file://`` path, a host on the local network, a plaintext ``http`` link to the
same name. Fetching it because we were told to is the same mistake as reading a
document's ``../../etc/passwd``, one hop further out.

:func:`~OpenGLContext.loaders.resolver.require_host` is the check: a fetched-for
URL must be ``https`` on a host the caller named in advance.
"""

import pytest

from OpenGLContext.loaders import resolver

ALLOWED = ('polyhaven.com', 'dl.polyhaven.org')


class TestAUrlAServiceHandedBack:
    def test_an_expected_host_passes_through_unchanged(self):
        url = 'https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/bust.gltf'

        assert resolver.require_host(url, ALLOWED) == url

    def test_any_of_the_named_hosts_is_accepted(self):
        """A provider serves its files from a different host than its API."""
        assert resolver.require_host('https://polyhaven.com/a/bust', ALLOWED)

    def test_another_host_is_refused(self):
        with pytest.raises(IOError):
            resolver.require_host('https://evil.example/payload.zip', ALLOWED)

    def test_a_subdomain_of_an_allowed_host_is_refused(self):
        """``polyhaven.com.evil.example`` ends with an allowed name and is not
        one; matching by suffix is how that gets through."""
        with pytest.raises(IOError):
            resolver.require_host('https://polyhaven.com.evil.example/x', ALLOWED)

    def test_a_host_smuggled_in_userinfo_is_refused(self):
        """``https://dl.polyhaven.org@evil.example/`` fetches from evil.example."""
        with pytest.raises(IOError):
            resolver.require_host('https://dl.polyhaven.org@evil.example/x', ALLOWED)

    def test_a_file_url_is_refused(self):
        with pytest.raises(IOError):
            resolver.require_host('file:///etc/passwd', ALLOWED)

    def test_plain_http_is_refused(self):
        """What comes back is written to disk and read as art; it is not going
        to arrive over a connection anyone can rewrite."""
        with pytest.raises(IOError):
            resolver.require_host('http://dl.polyhaven.org/file/x.hdr', ALLOWED)

    def test_a_link_local_address_is_refused(self):
        with pytest.raises(IOError):
            resolver.require_host('https://169.254.169.254/latest/meta-data/', ALLOWED)

    def test_an_unexpected_port_is_refused(self):
        with pytest.raises(IOError):
            resolver.require_host('https://dl.polyhaven.org:8080/x', ALLOWED)

    def test_the_default_https_port_written_out_is_accepted(self):
        assert resolver.require_host('https://dl.polyhaven.org:443/x', ALLOWED)

    def test_the_host_comparison_ignores_case(self):
        assert resolver.require_host('https://DL.PolyHaven.ORG/x', ALLOWED)

    def test_what_was_refused_is_named_in_the_error(self):
        """A developer meeting this needs to know which URL and which hosts."""
        with pytest.raises(IOError) as raised:
            resolver.require_host('https://evil.example/x', ALLOWED)

        assert 'evil.example' in str(raised.value)
        assert 'dl.polyhaven.org' in str(raised.value)
