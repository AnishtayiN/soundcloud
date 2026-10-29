"""Audio playback built on pygame.mixer (works on Windows 7 - 11)."""
from __future__ import annotations

import os
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import pygame
except Exception as exc:  # pragma: no cover - only when the build is broken
    pygame = None
    _PYGAME_ERROR = exc
else:
    _PYGAME_ERROR = None

try:
    import mutagen
except Exception:  # pragma: no cover
    mutagen = None


class PlaybackError(Exception):
    pass


class Player(object):
    """Very small wrapper: one track at a time, pause / resume / seek."""

    def __init__(self):
        if pygame is None:
            raise PlaybackError("pygame is not available: %s" % _PYGAME_ERROR)
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
            pygame.mixer.music.set_volume(0.8)
        except Exception as exc:
            raise PlaybackError("cannot open the audio device: %s" % exc)
        self._path = None
        self._duration_ms = 0
        self._base_ms = 0
        self._wall_start = 0.0
        self._playing = False
        self._paused = False
        self._volume = 0.8

    # ------------------------------------------------------------------ info --
    @property
    def path(self):
        return self._path

    @property
    def playing(self):
        return self._playing and not self._paused

    @property
    def paused(self):
        return self._paused

    @property
    def volume(self):
        return self._volume

    @property
    def duration_ms(self):
        return self._duration_ms

    def position_ms(self):
        if self._path is None:
            return 0
        if self._playing and not self._paused:
            position = self._base_ms + int((time.time() - self._wall_start) * 1000)
        else:
            position = self._base_ms
        if self._duration_ms:
            position = min(position, self._duration_ms)
        return max(0, position)

    def busy(self):
        if pygame is None or self._path is None:
            return False
        try:
            return bool(pygame.mixer.music.get_busy())
        except Exception:
            return False

    # ------------------------------------------------------------- controls --
    def load(self, path, start_ms=0):
        if not path or not os.path.isfile(path):
            raise PlaybackError("file not found: %s" % path)
        try:
            pygame.mixer.music.load(path)
        except Exception as exc:
            raise PlaybackError("cannot play this file: %s" % exc)
        self._path = path
        self._duration_ms = self.measure_duration(path)
        self._base_ms = max(0, int(start_ms or 0))
        self._paused = False
        self._playing = False

    def play(self, start_ms=None):
        if self._path is None:
            raise PlaybackError("nothing loaded")
        if start_ms is not None:
            self.seek(start_ms)
        try:
            pygame.mixer.music.play(start=0.0 if not self._base_ms else self._base_ms / 1000.0)
        except TypeError:
            # very old pygame without the start keyword
            pygame.mixer.music.play()
        self._wall_start = time.time()
        self._playing = True
        self._paused = False

    def pause(self):
        if pygame is not None and self._playing and not self._paused:
            position = self.position_ms()
            try:
                pygame.mixer.music.pause()
            except Exception:
                return
            self._base_ms = position
            self._paused = True

    def resume(self):
        if pygame is not None and self._playing and self._paused:
            try:
                pygame.mixer.music.unpause()
            except Exception:
                return
            self._wall_start = time.time()
            self._paused = False

    def stop(self):
        if pygame is not None:
            try:
                pygame.mixer.music.stop()
                # SDL_mixer keeps the source file open until unload on Windows.
                # Releasing it also makes cache eviction and test cleanup reliable.
                pygame.mixer.music.unload()
            except Exception:
                pass
        self._playing = False
        self._paused = False
        self._base_ms = 0
        self._path = None
        self._duration_ms = 0

    def seek(self, position_ms):
        """Best effort seek; falls back to restarting the file."""
        if self._path is None:
            return
        position_ms = max(0, int(position_ms or 0))
        if self._duration_ms:
            position_ms = min(position_ms, max(0, self._duration_ms - 500))
        self._base_ms = position_ms
        if not self._playing:
            return
        try:
            pygame.mixer.music.play(start=position_ms / 1000.0)
            self._wall_start = time.time()
            self._paused = False
        except Exception:
            # Unsupported format for seeking -> restart from the beginning.
            try:
                pygame.mixer.music.play()
                self._base_ms = 0
                self._wall_start = time.time()
                self._paused = False
            except Exception:
                pass

    def set_volume(self, volume):
        self._volume = max(0.0, min(1.0, float(volume or 0)))
        if pygame is not None:
            try:
                pygame.mixer.music.set_volume(self._volume)
            except Exception:
                pass

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def measure_duration(path):
        if mutagen is None:
            return 0
        try:
            info = mutagen.File(path)
            if info is not None and info.info is not None:
                return int(info.info.length * 1000)
        except Exception:
            pass
        return 0

    @staticmethod
    def format(ms):
        seconds = max(0, int(ms or 0) // 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return "%d:%02d:%02d" % (hours, minutes, seconds)
        return "%d:%02d" % (minutes, seconds)


class NullPlayer(object):
    """Stand-in used when no audio device can be opened (RDP, headless, ...).

    The UI keeps working, it just cannot make a sound - and it says so.
    """

    def __init__(self, reason="no audio device"):
        self.reason = reason
        self._path = None

    @property
    def path(self):
        return self._path

    @property
    def playing(self):
        return False

    @property
    def paused(self):
        return False

    @property
    def duration_ms(self):
        return 0

    @property
    def volume(self):
        return 0.0

    def position_ms(self):
        return 0

    def busy(self):
        return False

    def load(self, path, start_ms=0):
        self._path = path

    def play(self, start_ms=None):
        raise PlaybackError("audio is not available: %s" % self.reason)

    def pause(self):
        pass

    def resume(self):
        pass

    def stop(self):
        self._path = None

    def seek(self, position_ms):
        pass

    def set_volume(self, volume):
        pass

    format = staticmethod(Player.format)
    measure_duration = staticmethod(Player.measure_duration)
