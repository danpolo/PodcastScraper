"""Frame-accurate MP3 slicing, standard library only.

The benchmark scores a time window, not a whole episode, and every provider has
an upload limit that full episodes exceed — RunPod's file path mode caps around
5-10 MB and OpenAI's transcription endpoint at 25 MB, against ~32 MB episodes.
Cutting the window first sidesteps all of that and makes a benchmark run cost
cents instead of dollars.

ffmpeg would be the obvious tool, but it is not installed here and pulling it in
would need root. MP3 is a self-framing format, so walking the frame headers and
copying a byte range is enough — no decoding, no re-encoding, no dependency.
"""

# MPEG version -> layer -> bitrate table index. Only the fields needed to
# compute frame length and duration are decoded.
_BITRATES_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_BITRATES_V2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_SAMPLE_RATES = {
    3: [44100, 48000, 32000],  # MPEG-1
    2: [22050, 24000, 16000],  # MPEG-2
    0: [11025, 12000, 8000],   # MPEG-2.5
}
_SAMPLES_PER_FRAME = {3: 1152, 2: 576, 0: 576}


def _id3_size(data: bytes) -> int:
    """Byte offset of the first audio frame, skipping any ID3v2 tag."""
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    # Syncsafe integer: 7 bits per byte.
    size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    return 10 + size


def _parse_frame(data: bytes, index: int):
    """(frame_length, duration_seconds) for the frame at ``index``, or None."""
    if index + 4 > len(data):
        return None
    if data[index] != 0xFF or (data[index + 1] & 0xE0) != 0xE0:
        return None

    version = (data[index + 1] >> 3) & 0x03
    layer = (data[index + 1] >> 1) & 0x03
    bitrate_index = (data[index + 2] >> 4) & 0x0F
    sample_index = (data[index + 2] >> 2) & 0x03
    padding = (data[index + 2] >> 1) & 0x01

    if version == 1 or layer != 1:  # reserved version, or not Layer III
        return None
    if bitrate_index in (0, 15) or sample_index == 3:
        return None

    table = _BITRATES_V1_L3 if version == 3 else _BITRATES_V2_L3
    bitrate = table[bitrate_index] * 1000
    sample_rate = _SAMPLE_RATES[version][sample_index]
    samples = _SAMPLES_PER_FRAME[version]

    length = int(samples / 8 * bitrate / sample_rate) + padding
    if length <= 4:
        return None
    return length, samples / sample_rate


def slice_mp3(source, dest, start_seconds: float, end_seconds: float):
    """Copy the frames covering [start, end) from ``source`` into ``dest``.

    Boundaries land on frame edges (~26 ms at 44.1 kHz), which is far finer than
    the benchmark windows care about. Returns the actual (start, end) covered so
    scoring can use true bounds rather than the requested ones.
    """
    data = source.read_bytes() if hasattr(source, "read_bytes") else open(source, "rb").read()

    index = _id3_size(data)
    elapsed = 0.0
    first_offset = None
    actual_start = 0.0

    while index < len(data):
        frame = _parse_frame(data, index)
        if frame is None:
            # Resync: scan forward for the next plausible header.
            index += 1
            continue
        length, duration = frame

        if first_offset is None and elapsed >= start_seconds:
            first_offset = index
            actual_start = elapsed
        if first_offset is not None and elapsed >= end_seconds:
            break

        elapsed += duration
        index += length

    if first_offset is None:
        raise ValueError(
            f"start={start_seconds}s is beyond the end of the audio ({elapsed:.1f}s)"
        )

    payload = data[first_offset:index]
    dest = dest if hasattr(dest, "write_bytes") else None or dest
    with open(dest, "wb") as handle:
        handle.write(payload)
    return actual_start, elapsed


def duration_seconds(source) -> float:
    """Total playing time, by summing frame durations."""
    data = source.read_bytes() if hasattr(source, "read_bytes") else open(source, "rb").read()
    index = _id3_size(data)
    total = 0.0
    while index < len(data):
        frame = _parse_frame(data, index)
        if frame is None:
            index += 1
            continue
        length, frame_duration = frame
        total += frame_duration
        index += length
    return total
