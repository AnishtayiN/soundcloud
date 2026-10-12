"""The whole desktop UI (customtkinter / tkinter)."""
from __future__ import annotations

import io
import os
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox

import customtkinter as ctk

from PIL import Image, ImageTk

from . import util
from .api import GENRES, SoundCloud
from .downloader import DownloadCancelled, Downloader, DownloadJob
from .player import NullPlayer, PlaybackError, Player
from .strings import translate

BRAND = "#FF5500"
BRAND_DARK = "#CC3F00"
BG = "#0E0E12"
CARD = "#1A1A21"
CARD_ALT = "#22222B"
TEXT = "#F2F2F5"
DIM = "#9A9AA5"

FONT = "Segoe UI"
PAGE_SIZE = 30
MAX_ROWS = 200


class App(ctk.CTk):
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
            print("audio disabled:", self.player_error)
        self.downloader = Downloader(self.api.session)

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
        self._page_token = 0
        self._closing = False
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
            self.set_status("⚠ audio: " + self.player_error)

        if auto_load:
            self.after(600, self.load_trending)

    # =======================================================================
    #  strings
    # =======================================================================
    def T(self, key, *args):
        return translate(self.lang, key, *args)

    def _set_icon(self):
        try:
            icon = util.resource_path("assets", "icon.ico")
            if os.path.isfile(icon):
                self.iconbitmap(icon)
                return
        except Exception:
            pass
        try:
            png = util.resource_path("assets", "icon.png")
            if os.path.isfile(png) and Image is not None:
                image = Image.open(png)
                self._window_icon = ImageTk.PhotoImage(image.resize((32, 32)))
                self.iconphoto(True, self._window_icon)
        except Exception:
            pass

    # =======================================================================
    #  layout
    # =======================================================================
    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=54)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        self.logo = ctk.CTkLabel(header, text="☁", font=(FONT, 24, "bold"), text_color=BRAND)
        self.logo.pack(side="left", padx=(14, 6))

        self.app_label = ctk.CTkLabel(header, text=self.T("app_title"),
                                      font=(FONT, 16, "bold"), text_color=TEXT)
        self.app_label.pack(side="left")

        self.settings_button = ctk.CTkButton(header, text="⚙ " + self.T("settings"), width=110,
                                             height=32, fg_color=CARD_ALT, hover_color="#2E2E38",
                                             font=(FONT, 12), command=self.open_settings)
        self.settings_button.pack(side="right", padx=10)

        self.login_button = ctk.CTkButton(header, text=self.T("login"), width=120, height=32,
                                          fg_color=CARD_ALT, hover_color="#2E2E38",
                                          font=(FONT, 12), command=self.open_login)
        self.login_button.pack(side="right", padx=(0, 6))

        self.account_label = ctk.CTkLabel(header, text=self.T("logged_out"),
                                          font=(FONT, 11), text_color=DIM)
        self.account_label.pack(side="right", padx=10)

        # ------------------------------------------------------------ search
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 6))

        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(bar, textvariable=self.search_var,
                                         placeholder_text=self.T("search_hint"),
                                         height=38, fg_color=CARD_ALT, border_width=0,
                                         font=(FONT, 13))
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda event: self.do_search())

        self.search_button = ctk.CTkButton(bar, text=self.T("search"), width=90, height=38,
                                           fg_color=BRAND, hover_color=BRAND_DARK,
                                           font=(FONT, 13, "bold"), command=self.do_search)
        self.search_button.pack(side="left", padx=(8, 0))

        self.genre_var = tk.StringVar(value=self._genre_label())
        self.genre_menu = ctk.CTkOptionMenu(bar, values=[label for _, label in GENRES],
                                            variable=self.genre_var, width=170, height=38,
                                            fg_color=CARD_ALT, button_color=CARD_ALT,
                                            button_hover_color="#2E2E38", font=(FONT, 12),
                                            command=lambda value: self.on_genre(value))
        self.genre_menu.pack(side="left", padx=(8, 0))

        self.trending_button = ctk.CTkButton(bar, text=self.T("trending"), width=90, height=38,
                                             fg_color=CARD_ALT, hover_color="#2E2E38",
                                             font=(FONT, 12), command=self.load_trending)
        self.trending_button.pack(side="left", padx=(6, 0))

        self.favorites_button = ctk.CTkButton(bar, text=self.T("favorites"), width=100, height=38,
                                              fg_color=CARD_ALT, hover_color="#2E2E38",
                                              font=(FONT, 12), command=self.show_favorites)
        self.favorites_button.pack(side="left", padx=(6, 0))

        self.downloads_button = ctk.CTkButton(bar, text=self.T("downloads"), width=100, height=38,
                                              fg_color=CARD_ALT, hover_color="#2E2E38",
                                              font=(FONT, 12), command=self.open_downloads)
        self.downloads_button.pack(side="left", padx=(6, 0))

    def _build_list(self):
        self.list_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.list_scroll.grid_columnconfigure(0, weight=1)
        self.rows_frame = ctk.CTkFrame(self.list_scroll, fg_color="transparent")
        self.rows_frame.pack(fill="x", expand=True)
        self.footer_frame = ctk.CTkFrame(self.list_scroll, fg_color="transparent")
        self.footer_frame.pack(fill="x", pady=8)
        self._rows = []

    def _build_player(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=104)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.cover_label = ctk.CTkLabel(bar, text="", width=58, height=58,
                                        fg_color=CARD_ALT, corner_radius=8)
        self.cover_label.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=8)

        text_col = ctk.CTkFrame(bar, fg_color="transparent", width=250)
        text_col.grid(row=0, column=1, rowspan=2, sticky="w")
        self.now_title = ctk.CTkLabel(text_col, text="—", anchor="w", width=240,
                                      font=(FONT, 13, "bold"), text_color=TEXT)
        self.now_title.pack(fill="x")
        self.now_sub = ctk.CTkLabel(text_col, text="", anchor="w", width=240,
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
        except Exception:
            pass

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

    def _build_status(self):
        bar = ctk.CTkFrame(self, fg_color=CARD_ALT, corner_radius=0, height=30)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status_label = ctk.CTkLabel(bar, text="", anchor="w", font=(FONT, 11),
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
        self.search_entry.configure(placeholder_text=self.T("search_hint"))
        self.now_sub.configure(text=self.now_sub.cget("text"))

    # =======================================================================
    #  helpers
    # =======================================================================
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
            except Exception:
                pass
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
        if self.store:
            self.store.set("genre", slug)
        self.load_trending()

    def run_bg(self, work, on_done=None, on_error=None):
        def runner():
            if self._closing:
                return
            try:
                result = work()
            except Exception as exc:
                if on_error:
                    self.ui_queue.put(("call", on_error, str(exc)))
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
                print("callback error:", exc)
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
        except Exception:
            pass
        self.after(400, self._tick)

    # =======================================================================
    #  searching / lists
    # =======================================================================
    def do_search(self):
        query = self.search_var.get().strip()
        if not query:
            return
        self.query = query
        self.mode = "search"
        self.offset = 0
        self.load_page(append=False)

    def load_trending(self):
        self.mode = "charts"
        self.query = ""
        self.offset = 0
        self.load_page(append=False)

    def load_more(self):
        self.offset += PAGE_SIZE
        self.load_page(append=True)

    def load_page(self, append=False):
        if self.busy and append:
            return
        self._page_token += 1
        token = self._page_token
        self.busy = True
        self.set_status(self.T("searching"))
        self.show_progress(True, indeterminate=True)
        mode = self.mode
        query = self.query
        offset = self.offset
        genre = self._genre_slug()

        def work():
            if mode == "search":
                return self.api.search(query, PAGE_SIZE, offset)
            return self.api.charts(genre, PAGE_SIZE, offset)

        def done(tracks):
            if token != self._page_token or self._closing:
                return
            self.busy = False
            self.show_progress(False)
            self._render_tracks(tracks, append)

        def failed(error):
            if token != self._page_token or self._closing:
                return
            self.busy = False
            self.show_progress(False)
            self.set_status(self.T("api_error") if "client_id" in error
                            else self.T("network_error"))
            print("load error:", error)

        self.run_bg(work, done, failed)

    def _clear_rows(self):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        self._rows = []
        self.cover_labels = {}
        self.tracks = []

    def _render_tracks(self, tracks, append):
        if not append:
            self._clear_rows()
        existing = set(track.id for track in self.tracks)
        for track in tracks or []:
            if track.id in existing or len(self.tracks) >= MAX_ROWS:
                continue
            existing.add(track.id)
            index = len(self.tracks)
            self.tracks.append(track)
            self._rows.append(self._make_row(self.rows_frame, track, index))
        self.has_more = len(tracks or []) >= PAGE_SIZE and len(self.tracks) < MAX_ROWS

        for child in self.footer_frame.winfo_children():
            child.destroy()
        if not self.tracks:
            ctk.CTkLabel(self.footer_frame, text=self.T("no_results"), font=(FONT, 13),
                         text_color=DIM).pack(pady=30)
        elif self.has_more:
            ctk.CTkButton(self.footer_frame, text=self.T("load_more") + " ⬇", height=34,
                          fg_color=CARD_ALT, hover_color="#2E2E38", font=(FONT, 12),
                          command=self.load_more).pack(fill="x", padx=8, pady=6)

        if self.tracks:
            label = self.query if self.mode == "search" else self._genre_label()
            self.set_status(self.T("results", len(self.tracks), label))
        else:
            self.set_status(self.T("no_results"))

    def _make_row(self, parent, track, index):
        row = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8)
        row.pack(fill="x", pady=3, padx=2)

        cover = ctk.CTkLabel(row, text="", width=46, height=46, fg_color=CARD_ALT,
                             corner_radius=6)
        cover.pack(side="left", padx=(8, 10), pady=7)

        column = ctk.CTkFrame(row, fg_color="transparent")
        column.pack(side="left", fill="both", expand=True)
        title = ctk.CTkLabel(column, text=track.title, anchor="w", justify="left",
                             font=(FONT, 13, "bold"), text_color=TEXT)
        title.pack(fill="x")
        subtitle = ctk.CTkLabel(column, text=track.subtitle, anchor="w", justify="left",
                                font=(FONT, 11), text_color=DIM)
        subtitle.pack(fill="x")

        favorite = ctk.CTkButton(row, text="★", width=32, height=30,
                                 fg_color=CARD_ALT, hover_color="#2E2E38", font=(FONT, 13),
                                 text_color=BRAND if self.store and self.store.is_favorite(track.id)
                                 else DIM,
                                 command=None)
        favorite.configure(command=lambda t=track, b=favorite: self.toggle_favorite(t, b))
        favorite.pack(side="right", padx=(4, 8))
        download = ctk.CTkButton(row, text="⬇", width=32, height=30,
                                 fg_color=CARD_ALT, hover_color="#2E2E38", font=(FONT, 13),
                                 command=lambda t=track: self.download_menu(t))
        download.pack(side="right", padx=4)

        for widget in (row, cover, column, title, subtitle):
            widget.bind("<Button-1>", lambda event, i=index: self.play_index(i))
            widget.bind("<Button-3>", lambda event, t=track: self.track_menu(event, t))
        self._load_cover(track.thumb_url, cover)
        return row

    def _load_cover(self, url, label, size=(46, 46)):
        if not url:
            return
        cached = self.image_cache.get(url)
        if cached is not None:
            label.configure(image=cached)
            return
        self.cover_labels.setdefault(url, []).append(label)

        def work():
            response = self.api.session.get(url, timeout=20)
            response.raise_for_status()
            return response.content

        def done(data):
            self.ui_queue.put(("cover", url, data))

        self.run_bg(work, done, lambda error: None)

    def _apply_cover(self, url, data):
        if Image is None or not data:
            return
        try:
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            return
        for size in ((46, 46), (58, 58)):
            key = "%s@%d" % (url, size[0])
            if key not in self.image_cache:
                self.image_cache[key] = ctk.CTkImage(image, size=size)
        image46 = self.image_cache.get("%s@46" % url)
        image58 = self.image_cache.get("%s@58" % url)
        for label in self.cover_labels.pop(url, []):
            try:
                label.configure(image=image58 if label is self.cover_label else image46)
            except Exception:
                pass
        if self.now_playing is not None and url == self.now_playing.cover_url and image58:
            try:
                self.cover_label.configure(image=image58)
            except Exception:
                pass
        self.image_cache[url] = image46

    # =======================================================================
    #  playback
    # =======================================================================
    def play_index(self, index, tracks=None):
        tracks = tracks if tracks is not None else self.tracks
        if index < 0 or index >= len(tracks):
            return
        self.queue_tracks = list(tracks)
        self.queue_index = index
        self.play_track(tracks[index])

    def play_track(self, track):
        if not track.streamable:
            self.set_status(self.T("no_results"))
        self.play_token += 1
        token = self.play_token
        self.play_cancel.set()
        self.play_cancel = threading.Event()
        cancel = self.play_cancel
        self.set_status(self.T("loading_track", track.title))
        self.show_progress(True, indeterminate=True)

        def work():
            folder = util.cache_dir()
            path = os.path.join(folder, "scx-%s.mp3" % track.id)
            if not os.path.isfile(path) or os.path.getsize(path) < 4096:
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
                self.downloader.fetch_to(url, path, on_progress=progress, cancel_event=cancel)
            return path

        def done(path):
            self.ui_queue.put(("play_ready", token, path, track))

        def failed(error):
            self.ui_queue.put(("play_failed", token, error))

        self.run_bg(work, done, failed)

    def _on_play_ready(self, token, path, track):
        if token != self.play_token:
            return
        self.show_progress(False)
        try:
            self.player.load(path, 0)
            self.player.play()
        except PlaybackError as exc:
            self.set_status(str(exc))
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
            self.set_status("⚠ " + self.T("api_error"))
        else:
            self.set_status("⚠ " + error)
        print("playback error:", error)

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
        except Exception:
            pass
        if self.store:
            self.store.set("volume", volume)

    # =======================================================================
    #  favorites
    # =======================================================================
    def toggle_favorite(self, track, button=None):
        if not self.store:
            return
        added = self.store.toggle_favorite(track)
        self.set_status(self.T("add_favorite") if added else self.T("remove_favorite"))
        if self.now_playing is not None and track.id == self.now_playing.id:
            self.fav_button.configure(text_color=BRAND if added else DIM)
        if button is not None:
            try:
                if button.winfo_exists():
                    button.configure(text_color=BRAND if added else DIM)
            except Exception:
                pass
        if self.mode == "favorites":
            self.show_favorites()

    def toggle_favorite_current(self):
        if self.now_playing is not None:
            self.toggle_favorite(self.now_playing)

    def show_favorites(self):
        self._page_token += 1
        self.busy = False
        self.show_progress(False)
        self.mode = "favorites"
        self.has_more = False
        self._clear_rows()
        for child in self.footer_frame.winfo_children():
            child.destroy()
        tracks = self.store.favorite_tracks() if self.store else []
        self.tracks = tracks
        for index, track in enumerate(tracks):
            self._rows.append(self._make_row(self.rows_frame, track, index))
        if not tracks:
            ctk.CTkLabel(self.footer_frame, text=self.T("no_favorites"), font=(FONT, 13),
                         text_color=DIM).pack(pady=30)
        self.set_status(self.T("no_favorites") if not tracks
                        else self.T("results", len(tracks), self.T("favorites")))

    # =======================================================================
    #  menus
    # =======================================================================
    def track_menu(self, event, track):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=self.T("play_now"),
                         command=lambda: self.play_track(track))
        menu.add_command(label=self.T("play_next"), command=lambda: self.enqueue(track, True))
        menu.add_command(label=self.T("queue_add"), command=lambda: self.enqueue(track, False))
        menu.add_separator()
        menu.add_command(label=self.T("download_128"),
                         command=lambda: self.start_download(track, False))
        menu.add_command(label=self.T("download_original"),
                         command=lambda: self.start_download(track, True))
        menu.add_separator()
        favorite_label = self.T("remove_favorite") if self.store and self.store.is_favorite(track.id) \
            else self.T("add_favorite")
        menu.add_command(label=favorite_label, command=lambda: self.toggle_favorite(track))
        menu.add_command(label=self.T("copy_link"), command=lambda: self.copy_link(track))
        menu.add_command(label=self.T("open_browser"),
                         command=lambda: util.open_url(track.permalink_url))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def download_menu(self, track):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=self.T("download_128"),
                         command=lambda: self.start_download(track, False))
        menu.add_command(label=self.T("download_original"),
                         command=lambda: self.start_download(track, True))
        menu.add_separator()
        menu.add_command(label=self.T("open_folder"),
                         command=lambda: util.open_in_explorer(
                             self.store.get("download_dir") if self.store else "."))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def enqueue(self, track, next_position):
        if not self.queue_tracks:
            self.play_track(track)
            return
        if next_position:
            self.queue_tracks.insert(self.queue_index + 1, track)
        else:
            self.queue_tracks.append(track)
        self.set_status(self.T("queue_label", len(self.queue_tracks)))

    def copy_link(self, track):
        if not track.permalink_url:
            return
        self.clipboard_clear()
        self.clipboard_append(track.permalink_url)
        self.set_status(self.T("copied"))

    # =======================================================================
    #  downloads
    # =======================================================================
    def download_current(self):
        if self.now_playing is not None:
            self.download_menu(self.now_playing)

    def start_download(self, track, original=False):
        if original and not self.api.logged_in:
            messagebox.showinfo(self.T("app_title"), self.T("original_needs_login"))
            return
        folder = self.store.get("download_dir") if self.store else util.default_download_dir()
        job = DownloadJob(track, url=None, folder=folder,
                          filename=track.filename(".mp3"), original=original)
        job.state = "running"
        self.download_jobs.insert(0, job)
        self.open_downloads()
        self.set_status(self.T("downloading", track.title, 0))
        self.run_bg(lambda: self._run_download(job), None,
                    lambda error: self._download_failed(job, error))

    def _run_download(self, job):
        from .downloader import DownloadCancelled as _Cancelled
        try:
            url = self.api.download_url(job.track, job.original)
            extension = self.api.extension_for(url, job.original)
            job.filename = job.track.filename(extension)
            last = [0.0]

            def progress(done_bytes, total, speed):
                job.done = done_bytes
                job.total = total
                job.speed = speed
                now = time.time()
                if now - last[0] > 0.3:
                    last[0] = now
                    self.ui_queue.put(("download", job))
            path = self.downloader.download_track(url, job.folder, job.filename,
                                                  on_progress=progress,
                                                  cancel_event=job.cancel_event, original=job.original)
            job.filename = os.path.basename(path)
            job.path = path
            job.state = "done"
            job.done = os.path.getsize(path)
            job.total = job.done
            if self.store:
                self.store.add_download(os.path.basename(path), path, job.track.title,
                                        job.track.artist, url, job.done)
            self.ui_queue.put(("download", job))
            self.ui_queue.put(("status", self.T("downloaded", os.path.basename(path))))
            return path
        except _Cancelled:
            job.state = "cancelled"
            self.ui_queue.put(("download", job))
            return None
        except Exception as exc:
            self._download_failed(job, str(exc))
            return None

    def _download_failed(self, job, error):
        job.state = "failed"
        job.error = error
        self.ui_queue.put(("download", job))
        self.ui_queue.put(("status", self.T("download_failed", error)))

    def open_downloads(self):
        if self._downloads_window is not None and self._downloads_window.winfo_exists():
            self._downloads_window.lift()
            self._refresh_downloads_window(force=True)
            return
        window = ctk.CTkToplevel(self)
        window.title(self.T("downloads"))
        window.geometry("720x420")
        window.configure(fg_color=BG)
        window.transient(self)
        self._downloads_window = window
        self._download_rows = {}

        header = ctk.CTkFrame(window, fg_color=CARD, corner_radius=0, height=44)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="⬇ " + self.T("downloads"), font=(FONT, 14, "bold"),
                     text_color=TEXT).pack(side="left", padx=12)
        ctk.CTkButton(header, text=self.T("open_folder"), width=110, height=30,
                      fg_color=CARD_ALT, font=(FONT, 11),
                      command=lambda: util.open_in_explorer(
                          self.store.get("download_dir") if self.store else ".")).pack(
            side="right", padx=10)

        self._downloads_scroll = ctk.CTkScrollableFrame(window, fg_color="transparent")
        self._downloads_scroll.pack(fill="both", expand=True, padx=6, pady=6)
        self._refresh_downloads_window(force=True)

    def _refresh_downloads_window(self, force=False):
        window = self._downloads_window
        if window is None or not window.winfo_exists():
            return
        if not force and time.time() - self._last_download_ui < 0.3:
            return
        self._last_download_ui = time.time()
        for job in self.download_jobs[:60]:
            key = id(job)
            row = self._download_rows.get(key)
            if row is None:
                row = self._make_download_row(job)
                self._download_rows[key] = row
            progress, label = row
            progress.set(job.progress if job.state != "done" else 1.0)
            if job.state == "done":
                text = "✔ " + os.path.basename(job.path or job.filename)
            elif job.state == "failed":
                text = "✖ " + job.label + " — " + str(job.error)
            elif job.state == "cancelled":
                text = "⏹ " + job.label
            else:
                text = "%s   %s / %s   %s/s" % (job.label, util.human_size(job.done),
                                                util.human_size(job.total) or "?",
                                                util.human_size(job.speed))
            label.configure(text=text)

    def _make_download_row(self, job):
        row = ctk.CTkFrame(self._downloads_scroll, fg_color=CARD, corner_radius=8)
        row.pack(fill="x", pady=3, padx=2)
        label = ctk.CTkLabel(row, text=job.label, anchor="w", font=(FONT, 11), text_color=TEXT)
        label.pack(fill="x", padx=10, pady=(6, 0))
        progress = ctk.CTkProgressBar(row, height=8, progress_color=BRAND)
        progress.set(0)
        progress.pack(fill="x", padx=10, pady=(4, 8))
        buttons = ctk.CTkFrame(row, fg_color="transparent")
        buttons.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkButton(buttons, text=self.T("open_folder"), width=100, height=26,
                      fg_color=CARD_ALT, font=(FONT, 10),
                      command=lambda j=job: util.open_in_explorer(j.path or j.folder)).pack(
            side="left")
        ctk.CTkButton(buttons, text="✖", width=34, height=26, fg_color=CARD_ALT,
                      font=(FONT, 11),
                      command=lambda j=job: self._cancel_download(j)).pack(side="left", padx=6)
        return progress, label

    def _cancel_download(self, job):
        if job.state in ("queued", "running"):
            job.cancel()
            self.set_status("⏹ " + job.label)

    # =======================================================================
    #  windows: settings / login / about
    # =======================================================================
    def open_settings(self):
        window = ctk.CTkToplevel(self)
        window.title(self.T("settings"))
        window.geometry("620x460")
        window.configure(fg_color=BG)
        window.transient(self)

        def section(title):
            frame = ctk.CTkFrame(window, fg_color=CARD, corner_radius=10)
            frame.pack(fill="x", padx=14, pady=8)
            ctk.CTkLabel(frame, text=title, font=(FONT, 13, "bold"),
                         text_color=TEXT).pack(anchor="w", padx=12, pady=(10, 4))
            return frame

        # ---- download folder
        folder_frame = section(self.T("download_folder"))
        folder_row = ctk.CTkFrame(folder_frame, fg_color="transparent")
        folder_row.pack(fill="x", padx=12, pady=(0, 12))
        folder_var = tk.StringVar(value=self.store.get("download_dir") if self.store else "")
        entry = ctk.CTkEntry(folder_row, textvariable=folder_var, height=32,
                             fg_color=CARD_ALT, border_width=0, font=(FONT, 11))
        entry.pack(side="left", fill="x", expand=True)

        def choose_folder():
            chosen = filedialog.askdirectory(initialdir=folder_var.get() or os.path.expanduser("~"))
            if chosen:
                folder_var.set(chosen)
                if self.store:
                    self.store.set("download_dir", chosen)

        ctk.CTkButton(folder_row, text=self.T("browse"), width=90, height=32,
                      fg_color=CARD_ALT, font=(FONT, 11),
                      command=choose_folder).pack(side="left", padx=(8, 0))

        # ---- cache
        cache_frame = section(self.T("cache"))
        cache_row = ctk.CTkFrame(cache_frame, fg_color="transparent")
        cache_row.pack(fill="x", padx=12, pady=(0, 12))
        size = 0
        try:
            for name in os.listdir(util.cache_dir()):
                path = os.path.join(util.cache_dir(), name)
                if os.path.isfile(path):
                    size += os.path.getsize(path)
        except Exception:
            pass
        cache_label = ctk.CTkLabel(cache_row, text=util.human_size(size) or "0 MB",
                                   font=(FONT, 11), text_color=DIM)
        cache_label.pack(side="left")

        def clear_cache():
            freed = util.clear_folder(util.cache_dir())
            cache_label.configure(text=util.human_size(0) or "0 MB")
            self.set_status(self.T("cache_cleared", util.human_size(freed) or "0 MB"))

        ctk.CTkButton(cache_row, text=self.T("cache_clear"), width=120, height=32,
                      fg_color=CARD_ALT, font=(FONT, 11),
                      command=clear_cache).pack(side="right")

        # ---- language + api
        misc_frame = section(self.T("language"))
        misc_row = ctk.CTkFrame(misc_frame, fg_color="transparent")
        misc_row.pack(fill="x", padx=12, pady=(0, 12))
        language_var = tk.StringVar(value="فارسی" if self.lang == "fa" else "English")

        def change_language(value):
            if self.store:
                self.store.set("language", "fa" if value == "فارسی" else "en")
            self.lang = "fa" if value == "فارسی" else "en"
            self.apply_language()

        ctk.CTkOptionMenu(misc_row, values=["فارسی", "English"], variable=language_var,
                          width=140, height=32, fg_color=CARD_ALT, button_color=CARD_ALT,
                          command=change_language).pack(side="left")

        def refresh_api():
            self.api.forget_client_id()
            self.set_status(self.T("api_refreshed"))

        ctk.CTkButton(misc_row, text=self.T("api_refresh"), width=150, height=32,
                      fg_color=CARD_ALT, font=(FONT, 11),
                      command=refresh_api).pack(side="right")

        # ---- about
        about_frame = section(self.T("about"))
        ctk.CTkLabel(about_frame, text=self.T("about_text", self.version()),
                     justify="left", anchor="w", font=(FONT, 11), text_color=DIM,
                     wraplength=560).pack(anchor="w", padx=12, pady=(0, 12))
        ctk.CTkButton(window, text=self.T("close"), width=110, height=34, fg_color=CARD_ALT,
                      font=(FONT, 12), command=window.destroy).pack(pady=10)

    @staticmethod
    def version():
        from .version import __version__
        return __version__

    def open_login(self):
        if self.api.logged_in:
            self.api.set_cookie_header("")
            self.apply_language()
            self.set_status(self.T("logout"))
            return
        window = ctk.CTkToplevel(self)
        window.title(self.T("login_title"))
        window.geometry("640x400")
        window.configure(fg_color=BG)
        window.transient(self)

        ctk.CTkLabel(window, text="🔐 " + self.T("login_title"), font=(FONT, 15, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=16, pady=(14, 6))
        for key in ("login_step1", "login_step2", "login_step3"):
            ctk.CTkLabel(window, text=self.T(key), justify="left", anchor="w",
                         wraplength=590, font=(FONT, 11), text_color=DIM).pack(
                anchor="w", padx=16, pady=2)

        ctk.CTkButton(window, text=self.T("login_open"), height=34, fg_color=BRAND,
                      hover_color=BRAND_DARK, font=(FONT, 12),
                      command=lambda: util.open_url("https://soundcloud.com/signin")).pack(
            anchor="w", padx=16, pady=(10, 6))

        cookie_var = tk.StringVar(value=self.api.cookie_header)
        entry = ctk.CTkEntry(window, textvariable=cookie_var, height=70, fg_color=CARD_ALT,
                             border_width=0, font=(FONT, 10))
        entry.pack(fill="x", padx=16, pady=6)

        def save_cookie():
            value = cookie_var.get().strip()
            if not value:
                return
            self.api.set_cookie_header(value)
            self.apply_language()
            self.set_status(self.T("login_saved"))
            window.destroy()

        def import_file():
            path = filedialog.askopenfilename(
                title=self.T("login_import"),
                filetypes=[("cookies.txt", "*.txt"), ("all files", "*.*")])
            if not path:
                return
            try:
                cookie = self.api.import_cookies_file(path)
                cookie_var.set(cookie)
                self.apply_language()
                self.set_status(self.T("login_saved"))
                window.destroy()
            except Exception as exc:
                messagebox.showerror(self.T("login_title"), str(exc))

        buttons = ctk.CTkFrame(window, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=(6, 12))
        ctk.CTkButton(buttons, text=self.T("save"), width=110, height=34, fg_color=BRAND,
                      hover_color=BRAND_DARK, font=(FONT, 12), command=save_cookie).pack(
            side="left")
        ctk.CTkButton(buttons, text=self.T("login_import"), width=170, height=34,
                      fg_color=CARD_ALT, font=(FONT, 12), command=import_file).pack(
            side="left", padx=10)

    def open_about(self):
        messagebox.showinfo(self.T("app_title"), self.T("about_text", self.version()))

    # =======================================================================
    #  shutdown
    # =======================================================================
    def on_close(self):
        self._closing = True
        self._page_token += 1
        self.api.close()
        try:
            if self.store:
                self.store.save()
        except Exception:
            pass
        self.play_cancel.set()
        for job in self.download_jobs:
            if job.state in ("queued", "running"):
                job.cancel()
        try:
            self.player.stop()
        except Exception:
            pass
        self.executor.shutdown(wait=False)
        for callback in self.tk.splitlist(self.tk.call("after", "info")):
            self.after_cancel(callback)
        self.destroy()


def main():
    from .api import SoundCloud
    from .store import Store
    from .version import __version__

    store = Store()
    api = SoundCloud(store)
    app = App(api, store)
    app.mainloop()
