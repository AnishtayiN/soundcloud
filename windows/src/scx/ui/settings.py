
import os
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
try:
    from PIL import Image
except ImportError:
    Image = None
from .. import util
from ..diagnostics import failed
from .constants import BG, CARD, CARD_ALT, TEXT, DIM, FONT

class SettingsMixin(object):
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
                         text_color=TEXT).pack(anchor=self.text_anchor, padx=12, pady=(10, 4))
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
                self.persist("download_dir", chosen)

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
        except OSError as error:
            failed("measure cache", error)
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
            if not self.persist("language", "fa" if value == "فارسی" else "en"):
                language_var.set("فارسی" if self.lang == "fa" else "English")
                return
            self.lang = "fa" if value == "فارسی" else "en"
            self.apply_language()
            self._render_tracks(list(self.tracks), False)

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
                     justify=self.text_justify, anchor=self.text_anchor, font=(FONT, 11), text_color=DIM,
                     wraplength=560).pack(anchor=self.text_anchor, padx=12, pady=(0, 12))
        ctk.CTkButton(window, text=self.T("close"), width=110, height=34, fg_color=CARD_ALT,
                      font=(FONT, 12), command=window.destroy).pack(pady=10)

    @staticmethod
    def version():
        from ..version import __version__
        return __version__

