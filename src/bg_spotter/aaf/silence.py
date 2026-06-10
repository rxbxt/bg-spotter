"""Generate a silent PCM WAV in memory for use as AAF embedded essence."""

import io
import struct
import wave


def generate_silent_wav(
    num_frames: int,
    sample_rate: int = 48000,
    channels: int = 2,
    bit_depth: int = 24,
) -> bytes:
    """Return the bytes of a silent WAV file with *num_frames* audio frames.

    Python's wave module writes any sample width including 3 bytes (24-bit).
    No audio data is allocated beyond the header — the frame buffer is zeroed.
    """
    buf = io.BytesIO()
    sample_width = bit_depth // 8  # bytes per sample per channel

    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        # Write silence in chunks to avoid one gigantic allocation for features
        chunk = 8192
        silence_chunk = bytes(chunk * channels * sample_width)
        remaining = num_frames
        while remaining > 0:
            n = min(chunk, remaining)
            if n == chunk:
                wf.writeframes(silence_chunk)
            else:
                wf.writeframes(bytes(n * channels * sample_width))
            remaining -= n

    return buf.getvalue()
