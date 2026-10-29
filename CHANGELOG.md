# تغییرات

## اصلاحات اطمینان‌پذیری و امنیت — 2026-10-29

| مورد | فایل‌های اصلی | نتیجه |
|---|---|---|
| P0 دکمه‌های هدست/بلوتوث | `AndroidManifest.xml`, `PlayerService.java`, `receiver/MediaBtnReceiver.java` | ثبت receiver خصوصی با فیلتر MEDIA_BUTTON و هدف صریح MediaSession |
| P0 انقضای client_id | `ScApi.java`, `windows/src/scx/api.py` | پاک‌سازی مشروط کش، بررسی همه‌ی کاندیدهای HTML/JS، یک تلاش دوباره پس از 401/403؛ شبکه خارج از قفل کش |
| P0 حفاظت نشست | `Prefs.java`, `LoginActivity.java`, `AppDialogs.java`, `credentials.py`, `store.py` | Android EncryptedSharedPreferences و Windows DPAPI؛ مهاجرت و پاک‌سازی plaintext؛ خروج کامل از نشست |
| P0 کش پخش ویندوز | `media_cache.py`, `ui/playback.py` | رد آهنگ غیرقابل پخش، کلید ID/نوع/پسوند، اعتبارسنجی و حذف خرابی، سقف پیش‌فرض 500MB |
| P0 کاور اندروید | `Art.java`, `TrackAdapter.java` | LRU با بودجه‌ی واقعی 8MB،decode نمونه‌دار، فایل موقت یکتا و حذف دانلود ناقص |
| P0 خطای تمرکز صوت | `PlayerService.java`, `values*/strings.xml` | رد audio focus وارد STATE_ERROR می‌شود و پیام فارسی قابل فهم دارد |
| P0 دانلود کامل | `Downloader.java`, `DownloadCompletionReceiver.java`, `downloader.py` | staging و انتشار پس از موفقیت، MIME واقعی، تشخیص تکراری، roaming پیش‌فرض خاموش؛ بررسی طول و ادامه با Range در ویندوز |
| P0 تنظیمات اتمیک | `store.py` | فایل موقت هم‌پوشه + `os.replace`، `.bak` سالم و بازیابی خودکار، ثبت خطای خواندن/نوشتن |
| P0 receiver و RTL | `AndroidManifest.xml`, `MainActivity.java`, `PlayerBar.java`, `LocaleHelper.java`, layouts/styles | receiver خصوصی API33+، `supportsRtl`، فارسی پیش‌فرض و جهت متن راست‌به‌چپ |
| P0 پاسخ دیرهنگام | `SearchController.java`, `ui/lists.py` | شماره‌ی نسل برای نتیجه و خطا؛ پاسخ قدیمی نمی‌تواند لیست/وضعیت جدید را بازنویسی کند |
| P1 تفکیک ماژول‌ها | `MainActivity.java`, `SearchController.java`, `PlayerBar.java`, `AppDialogs.java`, `DownloadCoordinator.java`, `windows/src/scx/ui/` | تفکیک فهرست، پخش، دیالوگ و تنظیمات بدون تغییر نام برنامه یا طراحی کلی |
| P1 لاگ ایمن | `ScLog.java`, `diagnostics.py`, API/UI/service modules | ثبت عملیات و آدرس پاک‌شده به‌جای catch خاموش؛ بدون کوکی یا توکن |
| P1 متادیتای علاقه‌مندی | `Track.java`, `TrackTest.java` | حفظ `track_authorization` و `download_url` در رفت‌وبرگشت JSON |
| P1 تست و CI | `selftest.py`, `tools/check_android.py`, `ReliabilityTest.java`, `smoke.py`, `.github/workflows/build-release.yml`, `tools/ci_android_smoke.sh` | تست رگرسیون، APK/EXE، نصب و تست دودی API24/34/36 |

متن‌های اصلی فارسی و انگلیسی حفظ شده‌اند. `values-fa` برای جلوگیری از تغییر متن فارسی با تغییر زبان دستگاه اضافه شده است.

### محدودیت شناخته‌شده
pygame در ویندوز HLS پخش نمی‌کند. این تغییر، ذخیره‌ی پلی‌لیست با پسوند صوتی و نمایش وضعیت بارگذاری بی‌پایان را اصلاح می‌کند، اما پشتیبانی پخش HLS اضافه نمی‌کند؛ خطای مربوطه به فارسی اعلام می‌شود.
