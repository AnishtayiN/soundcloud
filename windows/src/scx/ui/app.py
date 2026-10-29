
import os
import time
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox
import customtkinter as ctk
try:
    from PIL import Image
except ImportError:
    Image = None
from .. import util
from ..api import GENRES, SoundCloud
from ..strings import translate
from ..downloader import Downloader
from ..player import NullPlayer, PlaybackError, Player
from ..diagnostics import failed, safe_text
from .constants import BRAND, BG, CARD_ALT, DIM, FONT
from .lists import ListsMixin
from .playback import PlaybackMixin
from .downloads import DownloadsMixin
from .dialogs import DialogsMixin
from .settings import SettingsMixin

class App(ListsMixin, PlaybackMixin, DownloadsMixin, DialogsMixin, SettingsMixin, ctk.CTk):
    """Main window."""

    def __init__(self, api=None, store=None, auto_load=True):
        super().__init__()
        self.store = store
        self.lang = self.store.get("language", "fa") if self.store else "fa"
        self.api = api or SoundCloud(self.store)
        self.player_error = ""
        try:
            self.player = Player()
        except PlaybackError as exc:
            # No sound card (remote desktop, broken drivers, ...): stay usable.
            self.player_error = str(exc)
            self.player = NullPlayer(self.player_error)
            failed("open audio device", exc)
        self.downloader = Downloader(self.api.session)
        from ..media_cache import MediaCache
        self.media_cache = MediaCache(util.cache_dir(), self.downloader,
                                      self.store.get("cache_limit_mb", 500) if self.store else 500)

        self.executor = ThreadPoolExecutor(max_workers=4)
        self.ui_queue = queue.Queue()
        self.image_cache = {}
        self.cover_labels = {}
        self.tracks = []
        self.queue_tracks = []
        self.queue_index = -1
        self.now_playing = None
        self.download_jobs = []
        self.seeking = False
        self.play_token = 0
        self.play_cancel = threading.Event()
        self.offset = 0
        self.has_more = False
        self.mode = "charts"
        self.query = ""
        self.busy = False
        self.list_generation = 0
        self._closing = False
        self._load_lock = threading.Lock()
        self._play_started_at = 0.0
        self._last_download_ui = 0.0
        self._downloads_window = None
        self._download_rows = {}

        ctk.set_appearance_mode("dark")
        self.title(self.T("app_title"))
        self.geometry("1060x720")
        self.minsize(900, 600)
        self.configure(fg_color=BG)
        self._set_icon()

        self._build_header()
        self._build_list()
        self._build_player()
        self._build_status()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<space>", lambda event: self.toggle_play())
        self.bind("<Control-f>", lambda event: self.search_entry.focus_set())

        self.apply_language()
        self.after(70, self._drain)
        self.after(300, self._tick)
        self.set_status(self.T("idle") + "   •   " + self.T("right_click_hint"))
        if self.player_error:
            self.set_status("⚠ " + self.T("audio_unavailable"))
        if self.store and self.store.recovered_backup:
            self.set_status(self.T("settings_recovered"))
        elif self.store and self.store.load_error:
            self.set_status(self.T("settings_error"))

        if auto_load:
            self.after(600, self.load_trending)

    # =======================================================================
    #  strings
    # =======================================================================
    @property
    def text_anchor(self):
        return "e" if self.lang == "fa" else "w"

    @property
    def text_justify(self):
        return "right" if self.lang == "fa" else "left"

    def T(self, key, *args):
        return translate(self.lang, key, *args)

    def _set_icon(self):
        try:
            icon = util.resource_path("assets", "icon.ico")
            if os.path.isfile(icon):
                self.iconbitmap(icon)
                return
        except Exception as error:
            failed("complete UI operation", error)
        try:
            png = util.resource_path("assets", "icon.png")
            if os.path.isfile(png) and Image is not None:
                image = Image.open(png)
                self.iconphoto(True, ctk.CTkImage(image, size=(32, 32))._light_image)
        except Exception as error:
            failed("complete UI operation", error)

    # =======================================================================
    #  layout
    # =======================================================================
    def _build_status(self):
        bar = ctk.CTkFrame(self, fg_color=CARD_ALT, corner_radius=0, height=30)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status_label = ctk.CTkLabel(bar, text="", anchor=self.text_anchor, font=(FONT, 11),
                                         text_color=DIM)
        self.status_label.pack(side="left", padx=12)
        self.progress = ctk.CTkProgressBar(bar, width=150, height=8, progress_color=BRAND)
        self.progress.set(0)
        self.progress.pack(side="right", padx=12)
        self.progress.pack_forget()

    # =======================================================================
    #  language
    # =======================================================================
    def apply_language(self):
        self.title(self.T("app_title"))
        self.search_button.configure(text=self.T("search"))
        self.trending_button.configure(text=self.T("trending"))
        self.favorites_button.configure(text=self.T("favorites"))
        self.downloads_button.configure(text=self.T("downloads"))
        self.settings_button.configure(text="⚙ " + self.T("settings"))
        self.login_button.configure(text=self.T("logout") if self.api.logged_in else self.T("login"))
        self.account_label.configure(text=self.T("logged_in") if self.api.logged_in
                                     else self.T("logged_out"))
        self.volume_label.configure(text=self.T("volume"))
        self.status_label.configure(anchor=self.text_anchor)
        self.now_title.configure(anchor=self.text_anchor)
        self.now_sub.configure(anchor=self.text_anchor)
        self.search_entry.configure(placeholder_text=self.T("search_hint"), justify=self.text_justify)
        self.now_sub.configure(text=self.now_sub.cget("text"))

    # =======================================================================
    #  helpers
    # =======================================================================
    def persist(self, key, value):
        if not self.store:
            return True
        try:
            self.store.set(key, value)
            return True
        except Exception as error:
            failed("save setting " + key, error)
            self.set_status(self.T("settings_error"))
            return False

    def set_status(self, text):
        self.status_label.configure(text=text)

    def show_progress(self, show, indeterminate=False):
        if show:
            self.progress.pack(side="right", padx=12)
            if indeterminate:
                self.progress.configure(mode="indeterminate")
                self.progress.start()
            else:
                self.progress.configure(mode="determinate")
        else:
            try:
                self.progress.stop()
            except Exception as error:
                failed("stop progress indicator", error)
            self.progress.pack_forget()

    def _genre_slug(self):
        wanted = (self.store.get("genre", "all-music") if self.store else "all-music")
        for slug, _label in GENRES:
            if slug == wanted:
                return slug
        return "all-music"

    def _genre_label(self):
        slug = self._genre_slug()
        for item_slug, label in GENRES:
            if item_slug == slug:
                return label
        return GENRES[0][1]

    def _slug_for_label(self, label):
        for slug, item_label in GENRES:
            if item_label == label:
                return slug
        return "all-music"

    def on_genre(self, label):
        slug = self._slug_for_label(label)
        if self.persist("genre", slug):
            self.load_trending()

    def run_bg(self, work, on_done=None, on_error=None):
        def runner():
            try:
                result = work()
            except Exception as exc:
                failed("background operation", exc)
                if on_error:
                    self.ui_queue.put(("call", on_error, safe_text(exc)))
                else:
                    self.ui_queue.put(("status", self.T("error_generic")))
                return
            if on_done:
                self.ui_queue.put(("call", on_done, result))
        self.executor.submit(runner)

    def _drain(self):
        try:
            while True:
                message = self.ui_queue.get_nowait()
                self._handle_message(message)
        except queue.Empty:
            pass
        if not self._closing:
            self.after(70, self._drain)

    def _handle_message(self, message):
        kind = message[0]
        if kind == "status":
            self.set_status(message[1])
        elif kind == "call":
            callback = message[1]
            try:
                callback(*message[2:])
            except Exception as exc:
                failed("UI callback", exc)
        elif kind == "tracks":
            self._render_tracks(message[1], message[2])
        elif kind == "cover":
            self._apply_cover(message[1], message[2])
        elif kind == "play_ready":
            self._on_play_ready(message[1], message[2], message[3])
        elif kind == "play_failed":
            self._on_play_failed(message[1], message[2])
        elif kind == "download":
            self._update_download_row(message[1])
        elif kind == "toast":
            messagebox.showinfo(self.T("app_title"), message[1])

    def _tick(self):
        # progress of the current track
        try:
            if self.now_playing is not None and not self.seeking:
                position = self.player.position_ms()
                duration = self.player.duration_ms or (self.now_playing.duration or 0)
                if duration:
                    self.seek_slider.set(min(1000, int(position * 1000 / duration)))
                self.time_label.configure(text="%s / %s" % (Player.format(position),
                                                            Player.format(duration)))
            if self.now_playing is not None and self.player.playing:
                if time.time() - self._play_started_at > 1.0:
                    finished = False
                    if self.player.duration_ms:
                        if self.player.position_ms() >= self.player.duration_ms - 400:
                            finished = True
                    if finished or not self.player.busy():
                        self.next_track(auto=True)
            self._refresh_downloads_window()
        except Exception as error:
            failed("player tick", error)
        if not self._closing:
            self.after(400, self._tick)


    def on_close(self):
        self._closing = True
        self.list_generation += 1
        self.play_token += 1
        try:
            if self.store:
                self.store.save()
        except Exception as error:
            failed("save settings on close", error)
        self.play_cancel.set()
        for job in self.download_jobs:
            if job.state in ("queued", "running"):
                job.cancel()
        try:
            self.player.stop()
        except Exception as error:
            failed("stop player on close", error)
        self.executor.shutdown(wait=False)
        self.destroy()


def main():
    from ..api import SoundCloud
    from ..store import Store

    store = Store()
    api = SoundCloud(store)
    app = App(api, store)
    app.mainloop()
