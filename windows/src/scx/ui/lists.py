
import io
import tkinter as tk
import customtkinter as ctk
try:
    from PIL import Image
except ImportError:
    Image = None
from ..api import GENRES
from ..diagnostics import failed
from .constants import BRAND, BRAND_DARK, CARD, CARD_ALT, TEXT, DIM, FONT, PAGE_SIZE, MAX_ROWS

class ListsMixin(object):
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
        self.search_entry.configure(justify=self.text_justify)
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
        if self.busy:
            return
        self.offset += PAGE_SIZE
        self.load_page(append=True)

    def load_page(self, append=False):
        with self._load_lock:
            if self._closing or (self.busy and append):
                return
            self.busy = True
            self.list_generation += 1
            generation = self.list_generation
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
            if generation != self.list_generation or self._closing:
                return
            self.busy = False
            self.show_progress(False)
            self._render_tracks(tracks, append)

        def on_error(error):
            if generation != self.list_generation or self._closing:
                return
            self.busy = False
            self.show_progress(False)
            self.set_status(self.T("api_error") if "client_id" in error
                            else self.T("network_error"))

        self.run_bg(work, done, on_error)

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
        title = ctk.CTkLabel(column, text=track.title, anchor=self.text_anchor, justify=self.text_justify,
                             font=(FONT, 13, "bold"), text_color=TEXT)
        title.pack(fill="x")
        subtitle = ctk.CTkLabel(column, text=track.subtitle, anchor=self.text_anchor, justify=self.text_justify,
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

        self.run_bg(work, done, lambda error: failed("load cover", RuntimeError(error)))

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

