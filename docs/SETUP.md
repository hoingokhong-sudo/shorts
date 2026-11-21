# Cài đặt một lần

Thứ tự nên làm: GitHub, Gemini, YouTube, Instagram, TikTok. TikTok làm cuối vì phải chờ duyệt app, trong lúc chờ YouTube và IG đã chạy được.
Tên nút/menu của Google, Meta, TikTok đổi khá thường xuyên, nếu lệch thì tìm mục tương đương.

## 1. GitHub

1. Tạo repo **public** (ví dụ `shorts`). Đẩy thư mục này lên nhánh `main`.
2. Settings > Pages > Source: Deploy from a branch > `main` / `/ (root)`. (Hoặc để `setup_wizard.py --repo user/shorts` làm giúp nếu đã cài `gh`.)
   Instagram cần URL công khai của clip, GitHub Pages cho URL đúng loại `video/mp4`.
3. Settings > Actions > General > Workflow permissions: Read and write.

## 2. Gemini (AI viết caption, miễn phí)

Lấy key tại https://aistudio.google.com/apikey (không cần thẻ). Free tier có giới hạn request/ngày, 1-2 clip/ngày dùng chưa tới một phần nhỏ. Không có key thì tool vẫn chạy bằng luật cơ bản.

## 3. YouTube

1. https://console.cloud.google.com > tạo project > APIs & Services > Library > bật **YouTube Data API v3**.
2. OAuth consent screen: User type External. Thêm scope `youtube.upload` và `youtube.readonly`. Thêm Gmail của mày vào Test users.
3. **Bấm Publish app (In production).** Bắt buộc: để chế độ Testing thì refresh token chết sau 7 ngày. App chưa xác minh vẫn dùng được cho chính mày, chỉ hiện cảnh báo "chưa xác minh" khi đăng nhập (Nâng cao > Tiếp tục).
4. Credentials > Create credentials > OAuth client ID > **Desktop app** > tải JSON, đặt tên `client_secret.json` ở thư mục gốc repo (đã nằm trong `.gitignore`).
5. `python tools/setup_wizard.py --only youtube`, chọn đúng kênh trong trình duyệt.

Ghi chú: tài liệu Google đang tự mâu thuẫn về việc project chưa audit có bị khoá video ở chế độ riêng tư hay không. Lịch sử thay đổi API ghi ngày 2/11/2026 là đã bỏ giới hạn này. Nếu video vẫn bị khoá, tool phát hiện và báo cho mày vào YouTube Studio chuyển sang Công khai.
Hạn mức upload mặc định 100 video/ngày/project, dư thừa cho 1-2 clip/ngày.

## 4. Instagram

1. Chuyển tài khoản IG sang **Professional** (Creator hoặc Business): Cài đặt > Loại tài khoản và công cụ. Để tài khoản ở chế độ công khai. Không cần Facebook Page.
2. https://developers.facebook.com > Create app > use case "Manage messaging & content on Instagram" > Instagram > **API setup with Instagram login**.
3. Add account > chọn tài khoản của mày > **Generate token**, copy token. Nếu báo thiếu vai trò: App roles > Roles > Instagram Testers > mời username, rồi chấp nhận lời mời trong app IG (Cài đặt > Ứng dụng và trang web > Lời mời tester).
4. Cần quyền `instagram_business_basic` và `instagram_business_content_publish`. Tài khoản của chính mày dùng Standard Access nên không cần App Review.
5. `python tools/setup_wizard.py --only instagram` rồi dán token. Token sống 60 ngày, tool tự refresh sau mỗi 30 ngày.

## 5. TikTok

1. https://developers.tiktok.com > Manage apps > Connect an app. Điền tên, icon, mô tả (nói thật: công cụ cá nhân đăng clip của chính mình).
2. Terms of Service URL và Privacy Policy URL: dùng 2 trang có sẵn trong repo, sau khi bật Pages:
   `https://USER.github.io/REPO/docs/terms.html` và `https://USER.github.io/REPO/docs/privacy.html`.
3. Add products: **Login Kit** (Redirect URI thêm đúng `http://localhost:3455/callback/`) và **Content Posting API**.
   Scope `video.upload` cho mode `draft`. Muốn mode `direct` thì bật thêm Direct Post và scope `video.publish`.
4. Submit app review (cần video demo: quay màn hình chạy tool và clip hiện trong hộp thư TikTok). TikTok duyệt thủ công và có thể từ chối app dùng cá nhân; mình không biết trước kết quả. Nếu bị từ chối: đặt `tiktok.mode: manual`, tool vẫn đăng 2 nền tảng kia và gửi caption + link tải clip để mày up tay phần TikTok.
5. Khi app được duyệt: `python tools/setup_wizard.py --only tiktok`.

Về hạn chế của app chưa audit: bài đăng trực tiếp chỉ ở chế độ riêng tư và tài khoản phải để riêng tư lúc đăng (theo tài liệu TikTok). Mỗi lần muốn công khai phải chuyển tài khoản sang công khai rồi đổi từng bài sang "Mọi người". Quá vướng cho việc đăng đều đặn, nên mặc định là `draft`.

## 6. Thông báo (khuyên làm)

Cài app **ntfy**, subscribe một topic bí mật (chuỗi ngẫu nhiên dài), đặt secret `NTFY_TOPIC`. Tool báo khi đăng xong, khi lỗi, và gửi caption để dán cho TikTok. Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) hoặc Discord (`DISCORD_WEBHOOK`) cũng được.

## 7. Secret lên GitHub

`python tools/setup_wizard.py --repo user/shorts` làm hết các bước trên và tự `gh secret set`. Làm tay thì vào Settings > Secrets and variables > Actions, thêm các secret có trong `.env.local`:
`TOKEN_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN, TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN, IG_ACCESS_TOKEN, GEMINI_API_KEY, NTFY_TOPIC`.

## 8. Thử

```bash
python -m autopost check
python tools/add_clip.py clip-thu.mp4 --tags "#tft" --no-push
python -m autopost preview 01-clip-thu
```

Trên GitHub: Actions > autopost > Run workflow, tick `dry_run`. Ổn thì chạy thật với clip thật.
