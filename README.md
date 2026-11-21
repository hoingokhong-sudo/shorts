# autopost: chốt clip là tự đăng YouTube Shorts + TikTok + Instagram Reels

Chạy hoàn toàn miễn phí trên GitHub Actions. Mày chỉ cần đẩy clip lên repo, phần còn lại tool lo:
lấy tag trending ở Việt Nam, nhờ AI (Gemini free) viết tiêu đề/caption/hashtag, đăng đúng giờ vàng, tự xếp lịch 1 hoặc 2 clip/ngày theo độ dài hàng đợi.

## Cách dùng hằng ngày

```bash
# 1 clip: chuẩn hoá ffmpeg, tạo file tag, push -> đăng NGAY nếu hôm nay chưa hết quota
python tools/add_clip.py D:/render/tran1.mp4 --tags "#tft #dttc #doubleup" --note "hai đứa hop bàn lật kèo"

# nhiều clip: đăng theo thứ tự truyền vào, tool tự dãn lịch
python tools/add_clip.py a.mp4 b.mp4 c.mp4 d.mp4 --tags "#tft"
```

Hoặc thủ công: bỏ `ten-clip.mp4` (+ `ten-clip.txt` tuỳ chọn) vào thư mục `clips/` rồi `git push`.
File `.txt` cùng tên:

```
title: Cú lật kèo phút chót          (tuỳ chọn, không có thì AI đặt)
#tft #dttc #doubleup                 (tag của mày, luôn được ưu tiên giữ)
hai đứa hop sang bàn nhau cứu nhau   (ghi chú cho AI viết caption sát nội dung)
```

## Lịch đăng

| Tình huống | Hành vi |
|---|---|
| Vừa push clip, hôm nay chưa đăng, không phải giờ ngủ (00:30-06:30) | Đăng clip đầu hàng đợi ngay |
| Hàng đợi ≤ 7 clip | 1 clip/ngày lúc 20:00 |
| Hàng đợi > 7 clip | 2 clip/ngày lúc 12:00 và 20:00 |
| Giữa 2 bài | Cách nhau tối thiểu 4h, không bao giờ vượt quota ngày |
| Một nền tảng lỗi | Thử lại riêng nền tảng đó (tối đa 3 lần, cách 20 phút), không đăng đôi nền tảng đã xong |

Mọi số trong `config.yml` chỉnh được. Xem lịch dự kiến: `python -m autopost status`.

## Cài đặt

Làm theo `docs/SETUP.md` (khoảng 30-45 phút, một lần). Rồi:

```bash
pip install -r requirements.txt
python tools/setup_wizard.py        # lấy token YouTube/TikTok, kiểm tra IG, đẩy secret lên GitHub
python -m autopost check            # kiểm tra đăng nhập
```

Trên GitHub: tab Actions > autopost > Run workflow, tick `dry_run` để chạy thử không đăng.

Muốn clip lên tối ưu viral: đọc `docs/VIRAL.md` (chuẩn clip, setup tài khoản, nhịp đăng).

## Lệnh hữu ích

```bash
python -m autopost status                 # hàng đợi + lịch dự kiến
python -m autopost preview ten-clip       # xem trước tiêu đề, caption, tag AI sẽ tạo
python -m autopost run --dry-run --force  # giả lập đăng clip kế tiếp, không ghi gì
python -m autopost check                  # secret nào đã có, đăng nhập được chưa
python -m unittest discover -s tests      # chạy test
```

## Những điều phải biết

- **TikTok**: app chưa được TikTok audit thì không đăng công khai trực tiếp được (bài chỉ ở chế độ riêng tư và tài khoản phải để riêng tư lúc đăng). Vì vậy mặc định là `tiktok.mode: draft`: clip tự vào hộp thư TikTok, mày bấm thông báo, dán caption (tool gửi sẵn qua ntfy/Telegram/Discord), chọn nhạc trend, bấm Đăng. Muốn đổi: `direct` hoặc `manual` trong `config.yml`.
- **Token TikTok xoay vòng** mỗi lần refresh. Tool lưu bản mới vào `state/tokens.enc` (mã hoá bằng `TOKEN_KEY`). Đừng chạy lệnh nào gọi TikTok trên máy mày, nếu không token trên GitHub chết và phải chạy lại `setup_wizard.py --only tiktok`. `check` và `--dry-run` đã được viết để không đụng TikTok.
- **Repo public** nên clip nằm chờ lộ ra trước giờ đăng (mày đã chấp nhận). Sau khi đăng xong clip bị xoá khỏi repo (vẫn còn trong lịch sử git). Giữ mỗi clip < 95MB; dùng `tools/prep_clip.py`.
- GitHub tự tắt workflow theo lịch sau 60 ngày repo không có hoạt động. Mày push clip đều thì không sao.
- Instagram chỉ nhận hashtag tối đa 5 (từ 12/2025), tool tự cắt đúng giới hạn từng nền tảng.

## Cấu trúc

```
autopost/        lõi: lịch, caption AI, trending, 3 uploader, token mã hoá
tools/           setup_wizard.py, add_clip.py, prep_clip.py
clips/           hàng đợi clip
state/           state.json + tokens.enc (bot tự commit)
failed/          clip lỗi toàn bộ nền tảng (chuyển về clips/ để thử lại)
config.yml       cấu hình
docs/            SETUP, VIRAL, privacy/terms (dùng cho đơn đăng ký app TikTok)
tests/           62 test
```
