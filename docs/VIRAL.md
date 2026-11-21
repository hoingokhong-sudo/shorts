# Setup clip và tài khoản để nền tảng đẩy tối đa

Không ai bảo đảm được viral, kể cả tool này. Thứ mình làm được là loại bỏ các lý do khiến clip bị đẩy yếu, và nhắm đúng các tín hiệu mà 3 nền tảng nói là quan trọng nhất.

**Tín hiệu chính (theo thông tin công khai của từng nền tảng, chi tiết thuật toán thì không ai biết đủ):**
- Instagram Reels: thời gian xem/tỉ lệ xem hết, lượt thích trên lượt tiếp cận, lượt gửi qua DM trên lượt tiếp cận (Mosseri công bố 1/2025). Ưu tiên người sáng tạo gốc hơn người repost.
- YouTube Shorts: tỉ lệ "xem" so với "vuốt qua" (Viewed vs Swiped away), thời gian xem, mức hài lòng. Shorts tối đa 3 phút, vuông hoặc dọc.
- TikTok: tỉ lệ xem hết, xem lại, chia sẻ, lưu, bình luận. Hashtag/caption/âm thanh chỉ là tín hiệu phụ.

Cả ba cùng một ý: **giữ người xem ở lại ngay từ 3 giây đầu và làm họ muốn gửi cho bạn bè.** Tag chỉ giúp phân loại, không cứu được clip nhạt.

## A. Chuẩn clip (tool kiểm tra và cảnh báo từng điều)

| Hạng mục | Chuẩn | Vì sao |
|---|---|---|
| Khung | 1080x1920, dọc 9:16 | Ngang hoặc lệch tỉ lệ bị viền đen/thu nhỏ, `prep_clip.py --mode blur` xử lý clip ngang |
| Độ dài | 15-45s là vùng an toàn, tối đa 60s | Xem hết dễ hơn. Tool cảnh báo > 90s, > 180s thì YouTube không coi là Shorts |
| 3 giây đầu | Có hook: kết quả/cú cười/cú nổ ngay giây 0, không logo, không intro | Quyết định vuốt qua hay ở lại |
| Chữ trên hình | Phụ đề tiếng Việt đốt sẵn (nhiều người xem tắt tiếng) | Giữ chân người xem |
| Vùng an toàn | Chừa ~15% đáy và ~10% mép phải/trên khỏi chữ quan trọng | Nút, caption, tên kênh của app che mất |
| Kết | Cắt ngay khi payoff xong, không đuôi chết. Cảnh cuối nối được về cảnh đầu | Xem lại là tín hiệu rất mạnh |
| Âm thanh | Tiếng gốc rõ, -14 LUFS (prep_clip tự chuẩn hoá) | Âm quá nhỏ bị vuốt qua |
| Nhạc | Đừng gắn nhạc có bản quyền vào file. Nhạc trend thêm trong app TikTok (mode draft) | Content ID làm mute/giới hạn Shorts, và API không gắn được nhạc thư viện |
| Watermark | Không có logo/watermark app khác | Instagram giảm phân phối nội dung repost |
| Bản gốc | Mỗi clip một ý, đúng nội dung của kênh | Cả 3 nền tảng đều ưu tiên nội dung gốc |

Với stream highlight: hook = khoảnh khắc đỉnh nhất (cú 3 sao muộn, nổ hũ, tiếng hét/cười), đặt ở giây 0, rồi mới đi ngược lại diễn biến nếu cần.

## B. Tiêu đề, caption, hashtag

- Tag của mày luôn đứng trước, AI chỉ thêm 2 tag trending **có liên quan**. Instagram giới hạn cứng 5 hashtag. Tool lấy 5 làm trần cho TikTok và 3 cho YouTube (YouTube chỉ hiển thị 3 tag đầu phía trên tiêu đề).
- Đừng dùng #fyp #viral #xuhuong: không giúp phân loại nội dung.
- Caption: câu 1 là hook có từ khoá chính (TikTok và YouTube đều có tìm kiếm), câu cuối là câu hỏi mở để kéo bình luận. AI đã được dặn đúng như vậy.
- Viết `.txt` cho từng clip vài chữ ghi chú (ai làm gì, vì sao hay): AI viết sát hơn nhiều so với chỉ có tên file.
- Muốn đổi giọng văn: `ai.extra_instructions` trong `config.yml` (ví dụ "giọng bựa, gen Z, không dùng emoji").

## C. Setup tài khoản

**Chung cho cả 3**
- Cùng tên hiển thị, cùng handle (nếu còn trống), cùng avatar, cùng một câu bio nói rõ kênh làm gì và bao lâu ra clip. Người xem từ nền tảng này sang nền tảng khác nhận ra ngay.
- Một ngách duy nhất. Hệ thống đề xuất học "tài khoản này dành cho ai" từ nội dung đăng liên tục.
- Đăng đều quan trọng hơn đăng nhiều. 1 clip/ngày đều 30 ngày tốt hơn 10 clip một ngày rồi nghỉ.

**YouTube**
- Studio > Cài đặt > Mặc định tải lên: ngôn ngữ video Tiếng Việt, danh mục theo `youtube.category_id`.
- Mô tả kênh và từ khoá kênh chứa ngách. Quốc gia: Việt Nam.
- Nếu clip có hình/giọng do AI tạo thì đặt `youtube.ai_generated: true` (YouTube yêu cầu khai báo nội dung tổng hợp).

**TikTok (tài khoản cũ lâu không dùng)**
- Hoàn thiện hồ sơ (avatar, bio, link), để tài khoản **Cá nhân/Creator** (Business thường bị hạn chế thư viện nhạc trend).
- Vài ngày trước khi đăng, mỗi ngày xem 20-30 phút video đúng ngách, xem hết thay vì lướt nhanh, thích/lưu vài cái. Việc này chỉnh trang For You của chính mày. Mình không có nguồn chính thức nói nó tăng phân phối video của mày, nên đừng kỳ vọng phép màu và đừng follow/like hàng loạt (dễ bị coi là spam).
- Dùng `tiktok.mode: draft` để còn gắn nhạc trend và tự chỉnh trong app.

**Instagram (tạo mới)**
- Chuyển Professional (Creator), để công khai, username khớp 2 nền tảng kia.
- Điền bio, avatar, link trước khi chạy tool. Tài khoản trống nhìn như spam, người xem không bấm theo dõi.

## D. Nhịp đăng

- Mặc định 12:00 và 20:00 giờ Việt Nam (khung xem nhiều của người Việt), 1 clip/ngày chỉ đăng 20:00. Mình chọn theo thói quen chung, chưa có số liệu kênh của mày. **Sau 2 tuần**, mở Insights/Analytics từng nền tảng, xem giờ người theo dõi online nhiều nhất rồi sửa `slots_*` trong `config.yml`.
- Chốt clip lúc nào thì đăng ngay lúc đó (nếu chưa hết quota ngày). Muốn ép về giờ vàng: `schedule.post_immediately: false`.

## E. Việc chỉ người làm được mà đáng làm nhất

1. Trả lời bình luận trong giờ đầu sau khi đăng (tool gửi thông báo khi đăng xong để mày biết lúc nào).
2. TikTok draft: chọn nhạc đang trend rồi mới Đăng.
3. Sau 48h xem Analytics: tỉ lệ xem/vuốt qua (YouTube), retention và sends (Instagram), tỉ lệ xem hết (TikTok). Giữ kiểu hook thắng, bỏ kiểu thua. Đây là vòng lặp tạo ra khác biệt, không phải tag.
