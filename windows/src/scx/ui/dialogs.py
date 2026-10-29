
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
try:
    from PIL import Image
except ImportError:
    Image = None
from .. import util
from ..diagnostics import failed
from ..credentials import CredentialError
from .constants import BRAND, BRAND_DARK, BG, CARD_ALT, TEXT, DIM, FONT

class DialogsMixin(object):
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

    def open_login(self):
        if self.api.logged_in:
            try:
                self.api.set_cookie_header("")
            except CredentialError as error:
                failed("clear credentials", error)
                self.set_status(self.T("credential_error"))
                return
            self.apply_language()
            self.set_status(self.T("logout"))
            return
        window = ctk.CTkToplevel(self)
        window.title(self.T("login_title"))
        window.geometry("640x400")
        window.configure(fg_color=BG)
        window.transient(self)

        ctk.CTkLabel(window, text="🔐 " + self.T("login_title"), font=(FONT, 15, "bold"),
                     text_color=TEXT).pack(anchor=self.text_anchor, padx=16, pady=(14, 6))
        for key in ("login_step1", "login_step2", "login_step3"):
            ctk.CTkLabel(window, text=self.T(key), justify=self.text_justify, anchor=self.text_anchor,
                         wraplength=590, font=(FONT, 11), text_color=DIM).pack(
                anchor=self.text_anchor, padx=16, pady=2)

        ctk.CTkButton(window, text=self.T("login_open"), height=34, fg_color=BRAND,
                      hover_color=BRAND_DARK, font=(FONT, 12),
                      command=lambda: util.open_url("https://soundcloud.com/signin")).pack(
            anchor=self.text_anchor, padx=16, pady=(10, 6))

        cookie_var = tk.StringVar()
        entry = ctk.CTkEntry(window, textvariable=cookie_var, height=70, fg_color=CARD_ALT,
                             border_width=0, font=(FONT, 10))
        entry.pack(fill="x", padx=16, pady=6)

        def save_cookie():
            value = cookie_var.get().strip()
            if not value:
                return
            try:
                self.api.set_cookie_header(value)
                cookie_var.set("")
                self.apply_language()
                self.set_status(self.T("login_saved"))
                window.destroy()
            except CredentialError as error:
                failed("save credentials", error)
                self.set_status(self.T("credential_error"))

        def import_file():
            path = filedialog.askopenfilename(
                title=self.T("login_import"),
                filetypes=[("cookies.txt", "*.txt"), ("all files", "*.*")])
            if not path:
                return
            try:
                self.api.import_cookies_file(path)
                cookie_var.set("")
                self.apply_language()
                self.set_status(self.T("login_saved"))
                window.destroy()
            except Exception as exc:
                failed("import credentials", exc)
                messagebox.showerror(self.T("login_title"), self.T("credential_error"))

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

