# SoundCloud X — Windows build

<div dir="ltr">

Desktop twin of the Android app: SoundCloud search, streaming and downloads.
Written with **Python 3.8 + customtkinter + pygame**, packaged into a single
`SoundCloudX.exe` by PyInstaller (runs on Windows 7 – 11, no Python needed).

</div>

## اجرای نسخه‌ی سورس (برای توسعه‌دهنده)

```bash
cd windows
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python src\main.py
```

## ساخت فایل exe

```bash
cd windows
pyinstaller --noconfirm --clean SoundCloudX.spec
# خروجی: windows/dist/SoundCloudX.exe
```

## تست‌ها

```bash
python selftest.py          # ۴۱ بررسی منطق (بدون اینترنت)
python selftest.py --ui     # بالا آوردن پنجره و رندر لیست با API قلابی
```

## چیزهایی که شاید لازم شود بدانی

* **کجا تنظیمات ذخیره می‌شود؟** `%APPDATA%\SoundCloudX\settings.json`
* **کش پخش؟** `%LOCALAPPDATA%\SoundCloudX\audio-cache` (پخش دوم به بعد آنی است)
* **دانلود؟** پیش‌فرض `%USERPROFILE%\Music\SoundCloudX` (از تنظیمات قابل تغییر است)
* **ورود برای فایل اصلی:** از منوی تنظیمات/ورود، `cookies.txt` را بده یا هدر Cookie
  (که `oauth_token` دارد) را بچسبان. این برای آهنگ‌های خصوصی هم لازم است.
* **بدون کارت صدا:** برنامه بالا می‌آید و در نوار وضعیت هشدار می‌دهد؛ دانلودها کار می‌کنند.
