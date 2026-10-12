"""Offline checks executed INSIDE the shipped EXE, not by the build Python.

CI launches this with a PATH containing only Windows, from an empty directory.
A missing bundled module, font, CA bundle, Tcl library or audio DLL fails the
release. Reports deliberately contain no cookies or user settings.
"""
import contextlib
import io
import json
import os
import runpy
import ssl
import sys
import tempfile
import traceback
import wave
from datetime import datetime


def run(argv):
    report_path = None
    if "--report" in argv:
        index = argv.index("--report")
        if index + 1 >= len(argv):
            return 2
        report_path = os.path.abspath(argv[index + 1])
    if report_path is None:
        from .util import config_dir
        report_path = os.path.join(config_dir(), "self-test.json")

    report = {"time_utc": datetime.utcnow().isoformat() + "Z",
              "frozen": bool(getattr(sys, "frozen", False)), "checks": {}, "ok": False}
    output = io.StringIO()
    os.environ["SDL_AUDIODRIVER"] = "dummy"  # Test codec/DLLs, not runner hardware.
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            from . import util
            import email.utils
            import http.client
            import certifi
            import requests
            import customtkinter
            from PIL import Image, ImageTk
            import pygame
            from .player import Player
            from .version import __version__
            report["version"] = __version__
            report["checks"]["network_and_image_modules"] = True
            assert os.path.isfile(certifi.where()), "TLS CA bundle missing"
            ssl.create_default_context(cafile=certifi.where())
            requests.Session().close()
            report["checks"]["tls_ca_bundle"] = True
            for name in ("icon.png", "icon.ico"):
                assert os.path.isfile(util.resource_path("assets", name)), name + " missing"
            Image.open(util.resource_path("assets", "icon.png")).verify()
            report["checks"]["icons"] = True
            if getattr(sys, "frozen", False) and sys.platform == "win32":
                assert any(n.lower().startswith("python") and n.lower().endswith(".dll")
                           for n in os.listdir(sys._MEIPASS)), "embedded Python DLL missing"
                report["checks"]["embedded_python_dll"] = True

            # These tests construct the real themed window, render search rows
            # and image thumbnails, and open settings/download dialogs.
            tests = runpy.run_path(util.resource_path("selftest.py"), run_name="scx_bundle_tests")
            code = tests["main"](["--ui", "--require-ui"])
            assert code == 0, "bundled logic/UI tests failed"
            report["checks"]["logic_and_real_window"] = True

            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, "test.wav")
                with wave.open(path, "wb") as wav:
                    wav.setnchannels(2)
                    wav.setsampwidth(2)
                    wav.setframerate(44100)
                    wav.writeframes(b"\x00\x00\x00\x00" * 22050)
                player = Player()
                player.load(path)
                player.play()
                assert player.busy(), "SDL mixer did not start"
                player.pause()
                assert player.paused
                player.resume()
                player.set_volume(0.25)
                assert player.volume == 0.25
                player.stop()
                pygame.mixer.quit()
            report["checks"]["bundled_audio_runtime"] = True
            report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    report["output"] = output.getvalue()
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
    if sys.stdout is not None:
        sys.stdout.write(report["output"] + "\nReport: " + report_path + "\n")
    return 0 if report["ok"] else 1
