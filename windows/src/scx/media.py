"""Strict parser for unencrypted MP3 HLS VOD (no external player required)."""
import re
from urllib.parse import urljoin, urlparse


class PlaylistError(IOError):
    pass


def media_url(base, value):
    url = urljoin(base, value.strip())
    if urlparse(url).scheme != "https":
        raise PlaylistError("media URL must use HTTPS")
    return url


def parse_playlist(text, url):
    """Return (master_child_url, [(url, range_offset, range_length), ...]).

    MP3 HLS fragments can be concatenated losslessly. Encrypted, live and
    fMP4/TS playlists must NOT be saved under an .mp3 filename.
    """
    lines = [line.strip() for line in text.lstrip("\ufeff").splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise PlaylistError("invalid HLS playlist")
    variants, segments = [], []
    bandwidth = None
    pending_range = None
    previous_url, previous_end = None, 0
    for line in lines[1:]:
        if line.startswith("#EXT-X-KEY:") and not re.search(r"(?:^|,)METHOD=NONE(?:,|$)", line.split(":", 1)[1]):
            raise PlaylistError("encrypted media is not supported; no file was saved")
        if line.startswith("#EXT-X-MAP:"):
            raise PlaylistError("this HLS format is not MP3")
        if line.startswith("#EXT-X-STREAM-INF:"):
            match = re.search(r"(?:^|,)BANDWIDTH=(\d+)", line.split(":", 1)[1])
            bandwidth = int(match.group(1)) if match else 0
        elif line.startswith("#EXT-X-BYTERANGE:"):
            match = re.fullmatch(r"(\d+)(?:@(\d+))?", line.split(":", 1)[1])
            if not match or int(match.group(1)) <= 0:
                raise PlaylistError("invalid HLS byte range")
            pending_range = (int(match.group(1)), int(match.group(2)) if match.group(2) else None)
        elif not line.startswith("#"):
            target = media_url(url, line)
            if bandwidth is not None:
                variants.append((bandwidth, target))
                bandwidth = None
                continue
            offset, length = None, None
            if pending_range is not None:
                length, offset = pending_range
                if offset is None:
                    if previous_url != target:
                        raise PlaylistError("implicit byte range without previous resource")
                    offset = previous_end
                previous_end = offset + length
            else:
                previous_end = 0
            previous_url = target
            pending_range = None
            segments.append((target, offset, length))
            if len(segments) > 10000:
                raise PlaylistError("playlist is too large")
    if bandwidth is not None or pending_range is not None:
        raise PlaylistError("incomplete HLS playlist")
    if variants:
        if segments:
            raise PlaylistError("mixed master and media playlist")
        return max(variants)[1], []
    if not segments or "#EXT-X-ENDLIST" not in lines:
        raise PlaylistError("only complete, non-live HLS tracks can be downloaded")
    return None, segments


def audio_header(data, mp3_only=False):
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xff and data[1] & 0xe0 == 0xe0
                                     and data[1] & 6 != 0 and data[1] & 0x18 != 8):
        return True
    if mp3_only:
        return False
    return (data.startswith((b"RIFF", b"fLaC", b"OggS", b"FORM")) or
            len(data) >= 12 and data[4:8] == b"ftyp")
