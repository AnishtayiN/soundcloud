# SoundCloud X — Windows

## کاربران: نصب پایتون لازم نیست

از [Releases](https://github.com/AnishtayiN/soundcloud/releases) یکی از این فایل‌ها را بگیرید:

* **`SoundCloudX-Setup-<version>-x64.exe`**: نصب‌کنندهٔ کامل آفلاین با میان‌بر، ابزار تست داخلی و حذف‌کننده. دسترسی administrator لازم ندارد.
* **`SoundCloudX.exe`**: نسخهٔ مستقل تک‌فایلی و پرتابل.

`Source code.zip` و `src/main.py` فایل اجرایی آماده نیستند. EXE، پایتون، Tcl/Tk، تم‌ها/فونت‌ها، Pillow/ImageTk، گواهی‌های TLS و pygame/SDL را داخل خود دارد؛ نصب‌کننده هرگز Python/pip نصب یا دانلود نمی‌کند. اینترنت فقط برای ساندکلاد نیاز است. برنامه ۶۴بیتی است؛ CI روی Windows Server 2022 اجرا می‌شود. سازگاری قدیمی رانتایم با Windows 7 SP1/8.x حفظ شده ولی روی آنها تست نشده است.

## در صورت خطا

از Start Menu → SoundCloud X → **Run offline diagnostics** استفاده کنید، یا با خود EXE:

```powershell
.\SoundCloudX.exe --self-test
```

این دستور مفسر جداگانه نمی‌خواهد. نتیجه در `%APPDATA%\SoundCloudX\self-test.json` و گزارش شروع در `%LOCALAPPDATA%\SoundCloudX\logs\startup.log` است. اگر Tcl نتواند بارگذاری شود، پیام خطا با API بومی ویندوز نمایش داده می‌شود. گزارش تست فاقد کوکی/تنظیمات حساب است؛ فایل `settings.json` یا `cookies.txt` را ارسال نکنید.

## فقط برای توسعه‌دهندگان

**این بخش برای استفاده از برنامه نیست.** Python 3.8 x64 و Tk روی ماشین ساخت ویندوز لازم‌اند. ساخت در لینوکس، EXE ویندوز نمی‌دهد.

```powershell
cd windows
py -3.8 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python selftest.py --ui --require-ui
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean SoundCloudX.spec
# خروجی: dist\SoundCloudX.exe
```

Inno Setup 6 برای نصب‌کننده:

```powershell
& 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' /DAppVersion=1.0.1 installer.iss
# خروجی: dist\SoundCloudX-Setup-1.0.1-x64.exe
```

`SoundCloudX.spec` با hooks، فایل‌های ضروری را جمع‌آوری می‌کند. `email`، `http`، `PIL.ImageTk`، دادهٔ تم و فونت را حذف نکنید. اندازهٔ کمتر معیار کامل بودن خروجی نیست.

CI بعد از ساخت، `tools/test_windows.ps1` را روی **EXE نهایی** با PATH محدود به Windows/System32، متغیرهای Python/Tcl پاک‌شده و پوشه/پروفایل خالی اجرا می‌کند. منطق و UI واقعی، بارگذاری تصویر/تم، TLS CA، DLL پایتونِ داخلی و پخش WAV با SDL dummy بررسی می‌شوند. سپس اجرای عادی و خروج سالم بررسی می‌شود. همین تست روی نسخهٔ نصب‌شده نیز تکرار می‌شود. شکست، انتشار را متوقف می‌کند. تست صوت، codec/DLL را بررسی می‌کند نه کارت صدای واقعی؛ تست‌ها اتصال زندهٔ ساندکلاد نیستند.

## داده‌ها

* تنظیمات/علاقه‌مندی: `%APPDATA%\SoundCloudX\settings.json`
* کش: `%LOCALAPPDATA%\SoundCloudX\audio-cache`
* دانلود پیش‌فرض: `%USERPROFILE%\Music\SoundCloudX` (قابل تغییر)
* ورود: کوکی SoundCloud از مرورگر یا `cookies.txt`، شامل خطوط HttpOnly. کوکی به درخواست‌های API خود ساندکلاد محدود است و به CDN تصاویر/صوت ارسال نمی‌شود.
* فایل اصلی فقط وقتی ناشر اجازه داده و حساب دسترسی دارد؛ در صورت شکست، MP3 به جای فایل اصلی ذخیره نمی‌شود.
