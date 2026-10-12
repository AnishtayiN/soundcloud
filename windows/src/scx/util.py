"""Small helpers shared by the whole Windows app."""
import os
import re
import sys
import time

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def app_dir():
    """Folder that contains the exe (frozen) or the source tree."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resource_path(*parts):
    """Path of a bundled resource (works from source and from the exe)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, *parts)
    return os.path.join(app_dir(), *parts)


def safe_filename(name, max_length=110):
    name = INVALID_CHARS.sub("_", (name or "").strip())
    name = name.replace("\n", " ").replace("\t", " ")
    while "  " in name:
        name = name.replace("  ", " ")
    # Windows refuses names ending with a dot or a space.
    name = name.rstrip(". ")
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}:
        name = "_" + name
    return name or "track"


def unique_path(folder, filename):
    """Never overwrites an existing file: adds (1), (2), ... instead."""
    target = os.path.join(folder, filename)
    if not os.path.exists(target):
        return target
    root, ext = os.path.splitext(filename)
    for i in range(1, 1000):
        candidate = os.path.join(folder, "%s (%d)%s" % (root, i, ext))
        if not os.path.exists(candidate):
            return candidate
    return os.path.join(folder, "%s-%d%s" % (root, int(time.time()), ext))


def human_size(num):
    if not num or num <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return "%.1f %s" % (num, unit)
        num /= 1024.0
    return "%.1f TB" % num


def human_count(num):
    try:
        num = int(num or 0)
    except (TypeError, ValueError):
        return ""
    if num <= 0:
        return ""
    if num < 1000:
        return str(num)
    if num < 1000000:
        return "%.1fK" % (num / 1000.0)
    if num < 1000000000:
        return "%.1fM" % (num / 1000000.0)
    return "%.1fB" % (num / 1000000000.0)


def format_duration(ms):
    try:
        ms = int(ms or 0)
    except (TypeError, ValueError):
        ms = 0
    seconds = max(0, ms // 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    return "%d:%02d" % (minutes, seconds)


def open_in_explorer(path):
    """Opens a folder (or selects a file) in the Windows explorer."""
    try:
        if os.path.isdir(path):
            os.startfile(path)  # noqa: B310 - fixed local path
        else:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    except Exception:
        try:
            import subprocess
            subprocess.Popen(["explorer", os.path.normpath(os.path.dirname(path))])
        except Exception:
            pass


def open_url(url):
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def cache_dir():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    path = os.path.join(base, "SoundCloudX", "audio-cache")
    os.makedirs(path, exist_ok=True)
    return path


def config_dir():
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or "."
    path = os.path.join(base, "SoundCloudX")
    os.makedirs(path, exist_ok=True)
    return path


def default_download_dir():
    for key in ("USERPROFILE",):
        home = os.environ.get(key)
        if home:
            music = os.path.join(home, "Music", "SoundCloudX")
            try:
                os.makedirs(music, exist_ok=True)
                return music
            except Exception:
                return home
    return os.path.join(os.path.expanduser("~"), "Music", "SoundCloudX")


def clear_folder(folder, keep=None):
    """Deletes the files of a folder, returns the freed byte count."""
    freed = 0
    keep = keep or set()
    if not os.path.isdir(folder):
        return 0
    for name in os.listdir(folder):
        if name in keep:
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path):
                freed += os.path.getsize(path)
                os.remove(path)
            elif os.path.isdir(path):
                freed += clear_folder(path)
                os.rmdir(path)
        except Exception:
            continue
    return freed
