"""The device seam: where mixed blocks go, and what happens when nowhere.

Two ways audio can be unavailable -- the package is not installed, and no device
opens -- and both must end in one warning and a silent run.  Both are exercised
here, because they are the paths a developer with working sound never sees.
"""

import numpy as np
import pytest

from OpenGLContext.audio import device as devicemodule
from OpenGLContext.audio.device import DeviceError, NullDevice, open_device
from OpenGLContext.audio.mixer import Mixer


class FakePlaybackDevice:
    """Stands in for ``miniaudio.PlaybackDevice`` with no hardware behind it."""

    instances = []

    def __init__(self, backend='ALSA', fail=False, **named):
        if fail:
            raise RuntimeError('no device')
        self.backend = backend
        self.named = named
        self.generator = None
        self.closed = False
        FakePlaybackDevice.instances.append(self)

    def start(self, generator):
        self.generator = generator

    def stop(self):
        self.generator = None

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def clear_instances():
    FakePlaybackDevice.instances = []
    yield
    FakePlaybackDevice.instances = []


class TestNullDevice:
    """Silence is a backend, not an error path bolted on the side."""

    def test_it_reports_itself_as_silent(self):
        assert NullDevice().silent is True

    def test_it_has_the_rate_and_channels_it_was_asked_for(self):
        device = NullDevice(sample_rate=22050, channels=2)
        assert (device.sample_rate, device.channels) == (22050, 2)

    def test_starting_and_stopping_are_safe_and_repeatable(self):
        device = NullDevice()
        mixer = Mixer(sample_rate=device.sample_rate)
        device.start(mixer.blocks())
        device.start(mixer.blocks())
        device.stop()
        device.stop()
        device.close()
        device.close()

    def test_it_never_pulls_from_the_mixer(self):
        """No thread, no callback, no cost: a silent run costs nothing."""
        pulled = []

        def watching():
            frames = yield None
            while True:
                pulled.append(frames)
                frames = yield None

        device = NullDevice()
        device.start(watching())
        assert pulled == []

    def test_it_is_not_running_until_started(self):
        device = NullDevice()
        assert device.running is False
        device.start(Mixer().blocks())
        assert device.running is True
        device.stop()
        assert device.running is False


class TestMiniaudioDevice:
    """The real backend, driven through a stand-in for the C library."""

    def test_it_asks_for_float32_stereo_at_the_mixers_rate(self, monkeypatch):
        monkeypatch.setattr(devicemodule, '_backend', lambda: FakeBackend())
        device = devicemodule.MiniaudioDevice(sample_rate=22050, channels=2)
        named = FakePlaybackDevice.instances[0].named
        assert named['sample_rate'] == 22050
        assert named['nchannels'] == 2
        assert named['output_format'] is FakeBackend.SampleFormat.FLOAT32
        assert device.silent is False

    def test_starting_primes_the_generator_before_handing_it_over(self, monkeypatch):
        """A device sends into the generator, so it must already be started."""
        monkeypatch.setattr(devicemodule, '_backend', lambda: FakeBackend())
        device = devicemodule.MiniaudioDevice(sample_rate=8000)
        mixer = Mixer(sample_rate=8000)
        device.start(mixer.blocks())
        block = FakePlaybackDevice.instances[0].generator.send(16)
        assert np.asarray(block).shape == (16, 2)

    def test_closing_closes_the_underlying_device(self, monkeypatch):
        monkeypatch.setattr(devicemodule, '_backend', lambda: FakeBackend())
        device = devicemodule.MiniaudioDevice(sample_rate=8000)
        device.close()
        assert FakePlaybackDevice.instances[0].closed is True

    def test_closing_twice_is_harmless(self, monkeypatch):
        monkeypatch.setattr(devicemodule, '_backend', lambda: FakeBackend())
        device = devicemodule.MiniaudioDevice(sample_rate=8000)
        device.close()
        device.close()

    def test_a_device_that_will_not_open_raises_device_error(self, monkeypatch):
        monkeypatch.setattr(devicemodule, '_backend', lambda: FakeBackend(fail=True))
        with pytest.raises(DeviceError):
            devicemodule.MiniaudioDevice(sample_rate=8000)

    def test_the_backends_own_null_output_counts_as_no_device(self, monkeypatch):
        """A machine with no sound card gets miniaudio's null backend.

        That is the no-device case wearing a disguise; treating it as a device
        would spin an audio thread that can never be heard.
        """
        monkeypatch.setattr(devicemodule, '_backend',
                            lambda: FakeBackend(backend='Null'))
        with pytest.raises(DeviceError):
            devicemodule.MiniaudioDevice(sample_rate=8000)

    def test_without_the_package_it_raises_device_error(self, monkeypatch):
        monkeypatch.setattr(devicemodule, '_backend', lambda: None)
        with pytest.raises(DeviceError):
            devicemodule.MiniaudioDevice(sample_rate=8000)


class TestOpenDevice:
    """The one call an application makes, which can never fail."""

    def test_it_returns_the_real_device_when_one_opens(self, monkeypatch):
        monkeypatch.setattr(devicemodule, '_backend', lambda: FakeBackend())
        assert open_device(sample_rate=8000).silent is False

    def test_a_missing_package_gives_silence_and_one_warning(self, monkeypatch, caplog):
        monkeypatch.setattr(devicemodule, '_backend', lambda: None)
        with caplog.at_level('WARNING'):
            device = open_device(sample_rate=8000)
        assert device.silent is True
        assert len(caplog.records) == 1
        assert 'miniaudio' in caplog.records[0].getMessage()

    def test_a_device_that_will_not_open_gives_silence_and_one_warning(
            self, monkeypatch, caplog):
        monkeypatch.setattr(devicemodule, '_backend', lambda: FakeBackend(fail=True))
        with caplog.at_level('WARNING'):
            device = open_device(sample_rate=8000)
        assert device.silent is True
        assert len(caplog.records) == 1

    def test_the_silent_device_keeps_the_requested_rate(self, monkeypatch):
        """The mixer is built around the device's rate, so it must be honest."""
        monkeypatch.setattr(devicemodule, '_backend', lambda: None)
        assert open_device(sample_rate=22050).sample_rate == 22050

    def test_opening_never_raises_whatever_the_backend_does(self, monkeypatch):
        class Exploding:
            def __getattr__(self, name):
                raise RuntimeError('this backend is broken')

        monkeypatch.setattr(devicemodule, '_backend', lambda: Exploding())
        assert open_device(sample_rate=8000).silent is True


class TestAvailability:
    def test_availability_is_reported_as_a_boolean(self):
        assert isinstance(devicemodule.miniaudio_available(), bool)

    def test_availability_follows_the_backend(self, monkeypatch):
        monkeypatch.setattr(devicemodule, '_backend', lambda: None)
        assert devicemodule.miniaudio_available() is False


class FakeBackend:
    """A stand-in ``miniaudio`` module: just what the device seam touches."""

    class SampleFormat:
        FLOAT32 = 'float32'

    def __init__(self, backend='ALSA', fail=False):
        self._backend = backend
        self._fail = fail

    def PlaybackDevice(self, **named):
        return FakePlaybackDevice(backend=self._backend, fail=self._fail, **named)


@pytest.mark.skipif(not devicemodule.miniaudio_available(),
                    reason='miniaudio is not installed')
def test_opening_a_real_device_never_raises():
    """Whatever this machine has -- a card, or nothing -- opening is safe."""
    device = open_device(sample_rate=8000)
    try:
        assert device.sample_rate == 8000
    finally:
        device.close()
