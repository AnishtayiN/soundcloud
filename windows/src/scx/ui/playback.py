
import time
import threading
import customtkinter as ctk
try:
    from PIL import Image
except ImportError:
    Image = None
from ..downloader import DownloadCancelled
from ..player import PlaybackError, Player
from ..diagnostics import failed
from .constants import BRAND, BRAND_DARK, CARD, CARD_ALT, TEXT, DIM, FONT

class PlaybackMixin(object):
    def _build_player(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=104)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.cover_label = ctk.CTkLabel(bar, text="", width=58, height=58,
                                        fg_color=CARD_ALT, corner_radius=8)
        self.cover_label.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=8)

        text_col = ctk.CTkFrame(bar, fg_color="transparent", width=250)
        text_col.grid(row=0, column=1, rowspan=2, sticky="w")
        self.now_title = ctk.CTkLabel(text_col, text="—", anchor=self.text_anchor, width=240,
                                      font=(FONT, 13, "bold"), text_color=TEXT)
        self.now_title.pack(fill="x")
        self.now_sub = ctk.CTkLabel(text_col, text="", anchor=self.text_anchor, width=240,
                                    font=(FONT, 11), text_color=DIM)
        self.now_sub.pack(fill="x")

        controls = ctk.CTkFrame(bar, fg_color="transparent")
        controls.grid(row=0, column=2, rowspan=2, padx=10)
        self.prev_button = ctk.CTkButton(controls, text="⏮", width=42, height=38,
                                         fg_color=CARD_ALT, hover_color="#2E2E38",
                                         font=(FONT, 15), command=self.previous_track)
        self.prev_button.pack(side="left", padx=3)
        self.play_button = ctk.CTkButton(controls, text="▶", width=52, height=38,
                                         fg_color=BRAND, hover_color=BRAND_DARK,
                                         font=(FONT, 16), command=self.toggle_play)
        self.play_button.pack(side="left", padx=3)
        self.next_button = ctk.CTkButton(controls, text="⏭", width=42, height=38,
                                         fg_color=CARD_ALT, hover_color="#2E2E38",
                                         font=(FONT, 15), command=self.next_track)
        self.next_button.pack(side="left", padx=3)

        # seek row
        seek_row = ctk.CTkFrame(bar, fg_color="transparent")
        seek_row.grid(row=0, column=3, sticky="ew", padx=(10, 10))
        bar.grid_columnconfigure(3, weight=1)
        self.time_label = ctk.CTkLabel(seek_row, text="0:00 / 0:00", width=105,
                                       font=(FONT, 11), text_color=DIM)
        self.time_label.pack(side="left")
        self.seek_slider = ctk.CTkSlider(seek_row, from_=0, to=1000, height=16,
                                         progress_color=BRAND, button_color=BRAND,
                                         button_hover_color=BRAND_DARK,
                                         command=self._on_seek_drag)
        self.seek_slider.set(0)
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=8)
        self.seek_slider.bind("<ButtonPress-1>", lambda event: self._begin_seek())
        self.seek_slider.bind("<ButtonRelease-1>", lambda event: self._end_seek())

        # volume row
        volume_row = ctk.CTkFrame(bar, fg_color="transparent")
        volume_row.grid(row=1, column=3, sticky="ew", padx=(10, 10), pady=(2, 6))
        self.volume_label = ctk.CTkLabel(volume_row, text=self.T("volume"), width=45,
                                         font=(FONT, 11), text_color=DIM)
        self.volume_label.pack(side="left")
        self.volume_slider = ctk.CTkSlider(volume_row, from_=0, to=100, height=14,
                                           progress_color=BRAND, button_color=BRAND,
                                           button_hover_color=BRAND_DARK,
                                           command=self._on_volume)
        self.volume_slider.set(float(self.store.get("volume", 0.8) or 0.8) * 100
                              if self.store else 80)
        self.volume_slider.pack(side="left", fill="x", expand=True, padx=8)
        try:
            self.player.set_volume(float(self.volume_slider.get()) / 100.0)
        except Exception as error:
            failed("update UI widget", error)

        actions = ctk.CTkFrame(bar, fg_color="transparent")
        actions.grid(row=0, column=4, rowspan=2, padx=(4, 12))
        self.fav_button = ctk.CTkButton(actions, text="★", width=40, height=38,
                                        fg_color=CARD_ALT, hover_color="#2E2E38",
                                        font=(FONT, 15), command=self.toggle_favorite_current)
        self.fav_button.pack(side="left", padx=3)
        self.download_button = ctk.CTkButton(actions, text="⬇", width=40, height=38,
                                             fg_color=CARD_ALT, hover_color="#2E2E38",
                                             font=(FONT, 15), command=self.download_current)
        self.download_button.pack(side="left", padx=3)

    def play_index(self, index, tracks=None):
        tracks = tracks if tracks is not None else self.tracks
        if index < 0 or index >= len(tracks):
            return
        self.queue_tracks = list(tracks)
        self.queue_index = index
        self.play_track(tracks[index])

    def play_track(self, track):
        if not track.streamable:
            self.set_status(self.T("not_streamable"))
            return
        self.play_token += 1
        token = self.play_token
        self.play_cancel.set()
        self.play_cancel = threading.Event()
        cancel = self.play_cancel
        self.set_status(self.T("loading_track", track.title))
        self.show_progress(True, indeterminate=True)

        def work():
            url = self.api.stream_url(track)
            last = [0.0]

            def progress(done_bytes, total, speed):
                if cancel.is_set():
                    raise DownloadCancelled()
                now = time.time()
                if total and now - last[0] > 0.4:
                    last[0] = now
                    percent = int(done_bytes * 100 / max(1, total))
                    self.ui_queue.put(("status", self.T("downloading", track.title, percent)))
            return self.media_cache.get_or_fetch(track, url, progress, cancel)

        def done(path):
            self.ui_queue.put(("play_ready", token, path, track))

        def failed(error):
            self.ui_queue.put(("play_failed", token, error))

        self.run_bg(work, done, failed)

    def _on_play_ready(self, token, path, track):
        if token != self.play_token:
            return
        self.show_progress(False)
        if self.media_cache.stream_type(path) == "hls":
            self.media_cache.discard(path)
            self.set_status(self.T("hls_unsupported"))
            return
        try:
            self.player.load(path, 0)
            self.player.play()
        except PlaybackError as exc:
            failed("load cached audio", exc)
            self.media_cache.discard(path)
            self.set_status(self.T("invalid_cache"))
            return
        self.now_playing = track
        self._play_started_at = time.time()
        self.now_title.configure(text=track.title)
        self.now_sub.configure(text=track.subtitle)
        self.play_button.configure(text="⏸")
        self.seek_slider.set(0)
        self.cover_label.configure(image=None)
        self._load_cover(track.cover_url, self.cover_label, size=(58, 58))
        self.fav_button.configure(
            text_color=BRAND if self.store and self.store.is_favorite(track.id) else DIM)
        self.set_status(self.T("playing", track.title))

    def _on_play_failed(self, token, error):
        if token != self.play_token:
            return
        self.show_progress(False)
        if "not streamable" in error or "not be streamed" in error:
            self.set_status("⚠ " + self.T("not_streamable"))
        elif "cache" in error.lower() or "incomplete" in error.lower():
            self.set_status("⚠ " + self.T("invalid_cache"))
        else:
            self.set_status("⚠ " + self.T("network_error"))

    def toggle_play(self):
        if self.now_playing is None:
            if self.tracks:
                self.play_index(0)
            return
        if self.player.playing:
            self.player.pause()
            self.play_button.configure(text="▶")
        elif self.player.paused:
            self.player.resume()
            self.play_button.configure(text="⏸")

    def next_track(self, auto=False):
        if not self.queue_tracks:
            return
        if self.queue_index + 1 < len(self.queue_tracks):
            self.play_index(self.queue_index + 1, self.queue_tracks)
        else:
            self.player.stop()
            self.now_playing = None
            self.play_button.configure(text="▶")
            self.set_status(self.T("idle"))

    def previous_track(self):
        if not self.queue_tracks:
            return
        if self.player.position_ms() > 4000:
            self.player.seek(0)
            return
        if self.queue_index > 0:
            self.play_index(self.queue_index - 1, self.queue_tracks)

    def _begin_seek(self):
        self.seeking = True

    def _on_seek_drag(self, value):
        if self.seeking and self.player.duration_ms:
            position = int(value) / 1000.0 * self.player.duration_ms
            self.time_label.configure(text="%s / %s" % (Player.format(position),
                                                        Player.format(self.player.duration_ms)))

    def _end_seek(self):
        if self.seeking and self.player.duration_ms:
            position = int(self.seek_slider.get()) / 1000.0 * self.player.duration_ms
            self.player.seek(position)
            self._play_started_at = time.time()
        self.seeking = False

    def _on_volume(self, value):
        volume = max(0.0, min(1.0, float(value) / 100.0))
        try:
            self.player.set_volume(volume)
        except Exception as error:
            failed("update UI widget", error)
        self.persist("volume", volume)

