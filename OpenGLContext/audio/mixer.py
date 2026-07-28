"""Summing the sounds that are playing into blocks of stereo samples.

This is the part that runs on the **audio thread**, and everything about its
shape follows from that:

* **The pool is fixed.**  :class:`Voice` slots are made once, at construction,
  and reused.  Starting a sound configures a slot; it never allocates one.  A
  scene that fires a thousand sounds a second therefore costs what a scene
  firing ten does, and the cost is known before it runs.
* **The buffers are made once too.**  :meth:`Mixer.mix` writes into
  pre-allocated arrays with numpy's ``out=`` parameters and returns a *view*.
  An allocation on the audio thread is a garbage collection on the audio thread,
  and a garbage collection on the audio thread is an audible gap.
* **Nothing here blocks, decodes, resolves a path or logs.**  Those all happen
  on the control thread, before a clip ever reaches a voice.
* **The control thread only ever writes plain floats and one flag.**  The lock
  is taken by :meth:`Mixer.play` to stop two *control* threads claiming one
  slot, and never by the mixing.

Gains are *ramped* across a block rather than applied as a step.  A gain that
jumps from one block to the next is a discontinuity, and a discontinuity is a
click -- which is also why the ramp is what smooths the hard edge at the outer
boundary of a VRML97 sound's ellipsoid, rather than that curve being fudged.

The pool has to be able to refuse, and it has to be able to *take back*.  When
every voice is busy the newcomer is weighed against the weakest one playing --
by ``priority`` first, then by how audible it currently is -- and either steals
it or is refused.  Stealing the quietest sound of the lowest priority is the
least audible theft available.

Because a slot can be taken back, :meth:`Mixer.play` hands out a
:class:`VoiceHandle` rather than the slot itself.  A handle remembers *which*
sound it was for, so a caller still steering a sound whose slot was recycled
steers nothing instead of steering somebody else's explosion.  That mistake is
silent, intermittent and very hard to find, which is why it is designed out
rather than documented.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any, Generator, Optional, Tuple

import numpy as np

from OpenGLContext.audio.clip import DEFAULT_SAMPLE_RATE, Clip
from OpenGLContext.audio.spatial import equal_power_pan

log = logging.getLogger(__name__)

#: How many sounds may play at once by default.  Well past what a scene needs
#: to sound busy, and far below what a mixing budget notices.
DEFAULT_VOICES = 32

#: Largest block the mixer prepares for, in frames.  4096 frames is ~93 ms at
#: 44.1 kHz, which no sane device period exceeds.
DEFAULT_MAX_BLOCK = 4096

#: How many two-tap averaging stages the muffle filter cascades.  Each stage has
#: the response ``cos(w/2)``, so four of them are ``cos^4(w/2)``: about -33 dB
#: near Nyquist and under -0.03 dB at a hundredth of it.  That is the shape of
#: "heard through water" -- the top gone, the bottom untouched -- and it is
#: reached with three vector operations per stage and no recursion, which is
#: what makes it affordable on the audio thread.
MUFFLE_STAGES = 4


class Voice:
    """One slot of the pool: a cursor, a rate and a pair of gains.

    Slots are not created by callers and outlive the sounds that occupy them.
    :attr:`generation` counts how many sounds a slot has held, and is what tells
    a :class:`VoiceHandle` whether it still refers to the sound it was made for.
    """

    __slots__ = (
        'clip', 'position', 'rate', 'loop', 'priority', 'active', 'generation',
        'gain_left', 'gain_right', 'target_left', 'target_right',
    )

    def __init__(self) -> None:
        self.clip: Optional[Clip] = None
        self.position = 0.0         # cursor, in clip samples; fractional
        self.rate = 1.0             # clip samples consumed per output frame
        self.loop = False
        self.priority = 0.0
        self.active = False
        self.generation = 0
        self.gain_left = 0.0        # what the last block ended at
        self.gain_right = 0.0
        self.target_left = 0.0      # what this block ramps to
        self.target_right = 0.0

    def __repr__(self) -> str:
        if not self.active or self.clip is None:
            return '<Voice idle>'
        return '<Voice %r %d%% L%.2f R%.2f>' % (
            self.clip.name, int(100.0 * self.position / max(self.clip.frames, 1)),
            self.target_left, self.target_right)

    @property
    def audibility(self) -> float:
        """How loud this voice is about to be, for the stealing comparison."""
        return max(self.target_left, self.target_right)

    def release(self) -> None:
        """Free the slot.

        ``active`` is cleared first: the audio thread reads it to decide whether
        to touch a slot at all, so clearing it first means the thread cannot see
        a half-released voice.
        """
        self.active = False
        self.clip = None


class VoiceHandle:
    """A caller's grip on one playing sound.

    Every operation checks that the slot still holds *this* sound.  Once it does
    not -- the clip finished, or a more important sound stole the slot -- the
    handle is inert: :attr:`playing` is False and the rest do nothing.  A caller
    may therefore hold a handle for as long as it likes and never test first.
    """

    __slots__ = ('_voice', '_generation')

    def __init__(self, voice: Voice, generation: int) -> None:
        self._voice = voice
        self._generation = generation

    def __repr__(self) -> str:
        return '<VoiceHandle %s>' % ('playing' if self.playing else 'finished',)

    @property
    def _live(self) -> bool:
        return self._voice.active and self._voice.generation == self._generation

    @property
    def playing(self) -> bool:
        """Whether the sound this handle was made for is still sounding."""
        return self._live

    @property
    def elapsed(self) -> float:
        """How far into the clip the sound has played, in seconds."""
        voice = self._voice
        if not self._live or voice.clip is None:
            return 0.0
        return voice.position / float(voice.clip.sample_rate)

    def set_gain(self, left: float, right: float) -> None:
        """Aim the sound at new per-ear gains, reached by the end of the block.

        Called every frame for a moving sound; it writes two floats, so calling
        it for every emitter in a scene costs nothing worth measuring.
        """
        if self._live:
            self._voice.target_left = float(left)
            self._voice.target_right = float(right)

    def set_gain_pan(self, gain: float, pan: float) -> None:
        """Aim the sound with a gain and a ``-1``-left-to-``+1``-right pan."""
        left, right = _pan_gains(pan)
        self.set_gain(gain * left, gain * right)

    def stop(self) -> None:
        """Silence this sound and return its slot to the pool."""
        if self._live:
            self._voice.release()


def _pan_gains(pan: float) -> Tuple[float, float]:
    """Equal-power gains for a pan position from -1 (left) to +1 (right)."""
    return equal_power_pan(max(-1.0, min(1.0, pan)) * math.pi / 2.0)


class Mixer:
    """A fixed pool of voices, summed into stereo blocks on demand.

    The application calls :meth:`play` and steers the handles it gets back; the
    device drives :meth:`blocks`.  Nothing else crosses between the two threads.
    """

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE,
                 voices: int = DEFAULT_VOICES,
                 max_block: int = DEFAULT_MAX_BLOCK,
                 master_gain: float = 1.0,
                 muffle: float = 0.0) -> None:
        self.sample_rate = int(sample_rate)
        self.max_block = int(max_block)
        self.master_gain = float(master_gain)
        self.voices: Tuple[Voice, ...] = tuple(Voice() for _ in range(voices))
        self._claim = threading.Lock()
        self._muffle = 0.0
        self.muffle = muffle

        size = self.max_block
        #: The block handed to the device: interleaved stereo, (frames, 2).
        self._out = np.zeros((size, 2), dtype=np.float32)
        #: Silence of the same shape, for a device that asks for too much.
        self._silence = np.zeros((size, 2), dtype=np.float32)
        #: One voice's samples, before its gains are applied.
        self._voice = np.zeros(size, dtype=np.float32)
        #: Fractional clip positions, and the integer neighbours the linear
        #: interpolation reads between.
        self._index = np.zeros(size, dtype=np.float64)
        self._lower = np.zeros(size, dtype=np.int64)
        self._upper = np.zeros(size, dtype=np.int64)
        self._fraction = np.zeros(size, dtype=np.float32)
        #: The per-ear gain ramp, and scratch for the multiplied samples.
        self._ramp = np.zeros(size, dtype=np.float32)
        self._scratch = np.zeros(size, dtype=np.float32)
        #: 1, 2, 3, ... n -- the shape of every gain ramp, scaled per block.
        self._steps = np.arange(1, size + 1, dtype=np.float32)
        #: 0, 1, 2, ... n-1 -- the shape of every cursor advance.
        self._offsets = np.arange(size, dtype=np.float64)
        #: The unfiltered mix, kept so the muffle can be blended against it.
        self._dry = np.zeros((size, 2), dtype=np.float32)
        #: Each filter stage's delayed sample, one per channel, carried from one
        #: block to the next -- without it the filter would restart every block
        #: and tick at the seam.
        self._delayed = np.zeros((MUFFLE_STAGES, 2), dtype=np.float32)
        self._shifted = np.zeros((size, 2), dtype=np.float32)

    # ------------------------------------------------------------------
    # Control thread
    # ------------------------------------------------------------------

    @property
    def muffle(self) -> float:
        """How much the mix is low-passed: 0 clear, 1 fully underwater.

        A blend rather than a switch, so an application can fade it in as a
        listener submerges.  Clamped, because a value outside the range would
        make the blend extrapolate and ring.
        """
        return self._muffle

    @muffle.setter
    def muffle(self, value: float) -> None:
        self._muffle = max(0.0, min(1.0, float(value)))

    @property
    def active_voices(self) -> int:
        """How many voices are playing right now."""
        return sum(1 for voice in self.voices if voice.active)

    def play(self, clip: Clip, gain: float = 1.0, pan: float = 0.0,
             priority: float = 0.0, loop: bool = False,
             rate: float = 1.0) -> Optional[VoiceHandle]:
        """Start ``clip``, or return None if the pool refuses it.

        ``gain`` is a linear multiplier and ``pan`` runs from -1 (hard left) to
        +1 (hard right).  ``priority`` follows ``KHR_audio_emitter`` and VRML97
        -- 1.0 is the most important -- and decides what this sound may steal and
        what it may be refused for.  ``rate`` multiplies playback speed and pitch
        together, as speeding up a record does.

        Returns a :class:`VoiceHandle` to steer the sound with, or None where
        the clip is empty, the rate is not positive, or every voice is busy with
        something more important.
        """
        left, right = _pan_gains(pan)
        return self.play_gains(clip, gain * left, gain * right,
                               priority=priority, loop=loop, rate=rate)

    def play_gains(self, clip: Clip, left: float, right: float,
                   priority: float = 0.0, loop: bool = False,
                   rate: float = 1.0) -> Optional[VoiceHandle]:
        """Start ``clip`` with per-ear gains already worked out.

        This is what the engine uses: it has the emitter's distance, cone and
        pan gains in hand and nothing left to convert.
        """
        if clip.frames <= 0 or rate <= 0.0:
            return None
        # A clip recorded at another rate plays back proportionally faster or
        # slower, which is exactly what resampling it would have done.
        step = float(rate) * clip.sample_rate / self.sample_rate
        with self._claim:
            voice = self._claim_voice(priority, max(left, right))
            if voice is None:
                return None
            voice.clip = clip
            voice.position = 0.0
            voice.rate = step
            voice.loop = bool(loop)
            voice.priority = float(priority)
            voice.gain_left = voice.target_left = float(left)
            voice.gain_right = voice.target_right = float(right)
            voice.generation += 1
            # Written last: the audio thread reads this to decide whether the
            # rest of the slot is worth looking at.
            voice.active = True
            return VoiceHandle(voice, voice.generation)

    def _claim_voice(self, priority: float, audibility: float) -> Optional[Voice]:
        """A free slot, the weakest busy one worth taking, or None.

        Held under :attr:`_claim` so two control threads cannot be handed the
        same slot.  The audio thread never takes this lock.
        """
        weakest: Optional[Voice] = None
        weakest_rank = (priority, audibility)
        for voice in self.voices:
            if not voice.active:
                return voice
            rank = (voice.priority, voice.audibility)
            if rank < weakest_rank:
                weakest, weakest_rank = voice, rank
        if weakest is not None:
            weakest.release()
        return weakest

    def stop_all(self) -> None:
        """Silence every voice."""
        for voice in self.voices:
            voice.release()

    # ------------------------------------------------------------------
    # Audio thread
    # ------------------------------------------------------------------

    def mix(self, frames: int) -> np.ndarray:
        """The next ``frames`` frames of the mix, as an ``(frames, 2)`` view.

        The array is a window onto the mixer's own buffer and is overwritten by
        the next call, which is what keeps this allocation-free.  Copy it if it
        must outlive the call.

        Raises:
            ValueError: for a block larger than ``max_block``.  There is no room
                to mix one, and quietly truncating would drop audio silently.
        """
        if frames > self.max_block:
            raise ValueError('block of %d frames exceeds max_block %d'
                             % (frames, self.max_block))
        out = self._out[:frames]
        out.fill(0.0)
        for voice in self.voices:
            if voice.active:
                self._mix_voice(voice, frames, out)
        if self.master_gain != 1.0:
            np.multiply(out, self.master_gain, out=out)
        if self._muffle > 0.0:
            self._apply_muffle(out, frames)
        # Summed voices can exceed full scale; clipping here is honest about it
        # and keeps the device from wrapping the waveform round on conversion.
        np.clip(out, -1.0, 1.0, out=out)
        return out

    def _apply_muffle(self, out: np.ndarray, frames: int) -> None:
        """Blend ``out`` towards a low-passed copy of itself, in place.

        The filter is a cascade of two-tap averages -- ``y[n] = (x[n] +
        x[n-1]) / 2`` -- which is the cheapest thing that is genuinely a
        low-pass rather than merely quieter.  Each stage needs the sample that
        fell off the end of the previous block, which is what
        :attr:`_delayed` carries.
        """
        dry = self._dry[:frames]
        shifted = self._shifted[:frames]
        np.copyto(dry, out)
        for stage in range(MUFFLE_STAGES):
            delayed = self._delayed[stage]
            shifted[0] = delayed
            shifted[1:] = out[:frames - 1]
            np.copyto(delayed, out[frames - 1])
            np.add(out, shifted, out=out)
            np.multiply(out, 0.5, out=out)
        np.subtract(out, dry, out=out)
        np.multiply(out, self._muffle, out=out)
        np.add(out, dry, out=out)

    def _mix_voice(self, voice: Voice, frames: int, out: np.ndarray) -> None:
        """Add one voice's contribution to ``out``, advancing its cursor."""
        clip = voice.clip
        if clip is None:
            voice.release()
            return
        available = self._resample(voice, clip, frames)
        if available > 0:
            self._accumulate(voice, frames, available, out)
        if not voice.loop and voice.position >= clip.frames:
            voice.release()

    def _resample(self, voice: Voice, clip: Clip, frames: int) -> int:
        """Fill ``self._voice`` with the voice's next samples; return how many.

        Linear interpolation between neighbouring samples, which is what makes
        an arbitrary playback rate possible at all.  A voice that is not looping
        may run out part way through the block; the count returned says where,
        and the block past it is left silent.
        """
        samples = clip.samples
        length = samples.shape[0]
        index = self._index[:frames]
        np.multiply(self._offsets[:frames], voice.rate, out=index)
        index += voice.position
        end = voice.position + voice.rate * frames

        if voice.loop:
            np.mod(index, length, out=index)
            available = frames
            voice.position = math.fmod(end, length)
        else:
            available = min(frames, int(math.ceil((length - voice.position) / voice.rate)))
            voice.position = end
            if available <= 0:
                return 0
            index = index[:available]

        count = index.shape[0]
        lower = self._lower[:count]
        upper = self._upper[:count]
        fraction = self._fraction[:count]
        scratch = self._scratch[:count]
        target = self._voice[:count]

        np.copyto(lower, index, casting='unsafe')       # positive, so trunc == floor
        np.subtract(index, lower, out=index)
        np.copyto(fraction, index, casting='unsafe')
        np.add(lower, 1, out=upper)
        if voice.loop:
            np.mod(upper, length, out=upper)
        # `clip` holds the last sample past the end of a non-looping clip, where
        # the fraction is what is left of the final frame.
        np.take(samples, lower, out=target, mode='clip')
        np.take(samples, upper, out=scratch, mode='clip')
        np.subtract(scratch, target, out=scratch)
        np.multiply(scratch, fraction, out=scratch)
        np.add(target, scratch, out=target)
        return available

    def _accumulate(self, voice: Voice, frames: int, available: int,
                    out: np.ndarray) -> None:
        """Ramp both ears' gains across the block and add them into ``out``."""
        voice.gain_left = self._ramp_channel(
            voice.gain_left, voice.target_left, frames, available, out, 0)
        voice.gain_right = self._ramp_channel(
            voice.gain_right, voice.target_right, frames, available, out, 1)

    def _ramp_channel(self, current: float, target: float, frames: int,
                      available: int, out: np.ndarray, column: int) -> float:
        """Add one ear of this voice to ``out``; return the gain reached."""
        ramp = self._ramp[:frames]
        if current == target:
            if target == 0.0:
                return target                   # silent in this ear: nothing to add
            ramp.fill(target)
        else:
            np.multiply(self._steps[:frames], 1.0 / frames, out=ramp)
            np.multiply(ramp, target - current, out=ramp)
            np.add(ramp, current, out=ramp)
        scratch = self._scratch[:available]
        np.multiply(self._voice[:available], ramp[:available], out=scratch)
        out[:available, column] += scratch
        return target

    def blocks(self) -> Generator[Any, int, None]:
        """The pull generator a playback device drives.

        The device sends the number of frames it wants and receives a
        ``memoryview`` of the mixed block -- a view, not a copy, so no audio
        buffer is allocated per callback.

        A device asking for more frames than the mixer prepared gets silence
        rather than an exception: raising inside a device callback tears down
        playback on a thread nobody is watching, which is a worse failure than a
        gap.  The mismatch is logged once and only once, which is the single
        deliberate exception to this module's no-logging-on-the-audio-thread
        rule -- an unreported permanent silence would be worse still.
        """
        warned = False
        frames = yield memoryview(self._out[:0])
        while True:
            if frames > self.max_block:
                if not warned:
                    warned = True
                    log.warning(
                        'audio device asked for %d frames but the mixer is built '
                        'for %d; playing silence. Raise max_block to fix.',
                        frames, self.max_block)
                block = self._silence[:min(frames, self.max_block)]
            else:
                block = self.mix(frames)
            frames = yield memoryview(block)
