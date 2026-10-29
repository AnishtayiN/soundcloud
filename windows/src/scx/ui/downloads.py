
import os
import time
from tkinter import messagebox
import customtkinter as ctk
try:
    from PIL import Image
except ImportError:
    Image = None
from .. import util
from ..downloader import DownloadJob
from ..diagnostics import failed, safe_text
from .constants import BRAND, BG, CARD, CARD_ALT, TEXT, FONT

class DownloadsMixin(object):
    def download_current(self):
        if self.now_playing is not None:
            self.download_menu(self.now_playing)

    def start_download(self, track, original=False):
        if original and not self.api.logged_in:
            messagebox.showinfo(self.T("app_title"), self.T("original_needs_login"))
            return
        if any(job.track.id == track.id and job.state in ("queued", "running", "done")
               for job in self.download_jobs):
            self.set_status(self.T("download_duplicate"))
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
        from ..downloader import DownloadCancelled as _Cancelled
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
                                                  cancel_event=job.cancel_event,
                                                  verify_audio=True)
            job.path = path
            job.state = "done"
            job.done = os.path.getsize(path)
            job.total = job.done
            if self.store:
                self.store.add_download(os.path.basename(path), path, job.track.title,
                                        job.track.artist, url, job.done, track_id=job.track.id)
            self.ui_queue.put(("download", job))
            self.ui_queue.put(("status", self.T("downloaded", os.path.basename(path))))
            return path
        except _Cancelled:
            job.state = "cancelled"
            self.ui_queue.put(("download", job))
            return None
        except Exception as exc:
            failed("download track", exc)
            self._download_failed(job, self.T("incomplete_download") if "incomplete" in str(exc)
                                  else self.T("download_failed", self.T("error_generic")))
            return None

    def _update_download_row(self, job):
        self._refresh_downloads_window(force=True)

    def _download_failed(self, job, error):
        job.state = "failed"
        job.error = safe_text(error)
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
        label = ctk.CTkLabel(row, text=job.label, anchor=self.text_anchor, font=(FONT, 11), text_color=TEXT)
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

