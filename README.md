# QUAN GIA — Quản lý tiền trọ, lưu dữ liệu bền vững và gửi email tự động

Giao diện Streamlit với bảng màu xanh rừng, xanh ngọc, sage và vàng champagne. Dữ liệu thật được lưu trong Supabase PostgreSQL; hóa đơn PDF được gửi riêng cho email của từng người thuê. GitHub Actions chạy tác vụ gửi định kỳ hằng ngày.

> Đây là ứng dụng quản trị. Trước khi nhập thông tin thật, hãy cấu hình Supabase và mật khẩu quản trị. Không commit secret/key lên GitHub.

## Kiến trúc

- **GitHub**: lưu mã nguồn, workflow gửi email theo lịch.
- **Streamlit Community Cloud**: chạy giao diện web.
- **Supabase PostgreSQL**: lưu hồ sơ phòng/người thuê, cấu hình tháng, hóa đơn và nhật ký email. SQLite cục bộ không được dùng làm kho chính vì filesystem trên Streamlit Community Cloud không bảo đảm tồn tại lâu dài.
- **SMTP (ví dụ Gmail)**: gửi email với PDF đính kèm.
- **GitHub Actions**: chạy `auto_email.py` lúc 09:17 giờ Việt Nam hằng ngày (workflow cron là UTC). Lịch chạy có thể bị trễ khi GitHub quá tải; có thể chạy thử/thủ công qua tab Actions.

## A. Cài đặt database Supabase (một lần)

1. Mở https://supabase.com/ và tạo một project.
2. Vào **SQL Editor → New query**.
3. Mở `supabase_schema.sql` trong repository, sao chép toàn bộ SQL, dán vào SQL Editor rồi nhấn **Run**.
4. Vào **Project Settings / API Keys** hoặc mục tương đương, lấy **Project URL** và khóa máy chủ có quyền service-role/secret. Khóa này có quyền cao, chỉ dùng ở backend và Secrets — tuyệt đối không đưa vào code phía trình duyệt hoặc GitHub repository.
5. Bảng `rooms`, `monthly_settings`, `monthly_bills`, `email_logs` được tạo bằng SQL. Row Level Security đã bật, không tạo policy công khai; app server sử dụng khóa máy chủ.

## B. Tải code lên GitHub bằng trình duyệt

1. Tải ZIP dự án và giải nén trên máy.
2. Vào https://github.com/ → **New repository**. Đặt tên ví dụ `quan-ly-tien-tro`; để private nếu có thể.
3. Trong repo, chọn **Add file → Upload files**, tải tất cả file/thư mục bên trong ZIP lên (nhớ cả `.github/workflows/send-rent-email.yml` và `.streamlit/config.toml`). Nếu giao diện upload không hiển thị file/thư mục bắt đầu bằng dấu chấm, tạo thủ công đường dẫn bằng **Add file → Create new file**, nhập tên như `.github/workflows/send-rent-email.yml` và dán nội dung file.
4. Commit changes. Không upload file `secrets.toml`, `.env`, database cá nhân hoặc thông tin thật của người thuê.

## C. Deploy app trên Streamlit

1. Mở https://share.streamlit.io/ và đăng nhập với GitHub.
2. Chọn **Create app / Deploy an app**, chọn repo `quan-ly-tien-tro`, branch `main`, main file `app.py`.
3. Nhấn Deploy. Streamlit sẽ tạo một URL dạng `https://....streamlit.app`.
4. Mở **App settings → Secrets**, dán mẫu dưới đây rồi thay placeholder bằng giá trị thật. Secrets này dùng cho app UI và gửi email thủ công:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "YOUR-SERVER-SIDE-KEY"
ADMIN_PIN = "tao-mot-mat-khau-quan-tri-dai-rieng"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USE_SSL = false
SMTP_USERNAME = "your-sending-address@gmail.com"
SMTP_PASSWORD = "YOUR-GOOGLE-APP-PASSWORD"
SMTP_FROM_EMAIL = "your-sending-address@gmail.com"
SMTP_FROM_NAME = "QUAN GIA - Quan ly tien tro"
```

5. Save/Update Secrets và reboot/redeploy app. Đăng nhập bằng `ADMIN_PIN`.
6. Vào **Phòng & người thuê** để thêm phòng và liên hệ. Vào **Hóa đơn & điện nước** để nhập công tơ, kiểm tra tiền, chốt hóa đơn. Chỉ bật **Cho phép email tự động** khi đã xác minh email và số liệu.

## D. Cấu hình SMTP (Gmail ví dụ)

1. Dùng địa chỉ gửi email riêng cho chủ trọ.
2. Nếu dùng Gmail, bật xác minh 2 bước và tạo **App Password** nếu tài khoản đủ điều kiện. Điền App Password vào `SMTP_PASSWORD`, không dùng mật khẩu đăng nhập thông thường khi Google yêu cầu App Password.
3. Thử gửi PDF đến chính email của bạn trước khi gửi cho người thuê.
4. Cấu hình Gmail có thể thay đổi theo loại tài khoản/Workspace; nếu SMTP bị chặn, sử dụng SMTP/provider phù hợp với email bạn sở hữu.

## E. Bật gửi email tự động bằng GitHub Actions

Đây là phần giúp email tự chạy theo lịch khi bạn không mở web Streamlit. GitHub Actions dùng cùng Supabase, đọc hóa đơn đã chốt và ghi nhật ký gửi vào cùng database.

1. Mở repo GitHub → **Settings → Secrets and variables → Actions → New repository secret**.
2. Tạo lần lượt các secrets sau (giá trị giống thông tin tương ứng trong Streamlit Secrets):
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SMTP_HOST`
   - `SMTP_PORT`
   - `SMTP_USE_SSL`
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD`
   - `SMTP_FROM_EMAIL`
   - `SMTP_FROM_NAME`
   - (tùy chọn) `AUTO_EMAIL_ONLY_UNPAID` = `true` để chỉ gửi các hóa đơn chưa thanh toán; mặc định gửi mọi hóa đơn tự động đủ điều kiện, kể cả đã thanh toán.
3. Mở tab **Actions** trong GitHub. Nếu GitHub yêu cầu, chọn **I understand my workflows, go ahead and enable them**.
4. Chọn workflow **Gui hoa don tien tro tu dong** → **Run workflow**. Giữ `dry_run=true` để chỉ xem danh sách người nhận, số tiền sẽ gửi (không gửi email thật).
5. Khi đã kiểm tra dữ liệu, chạy lại workflow thủ công với `dry_run=false` để gửi thật. Sau đó workflow tự chạy hằng ngày lúc 02:17 UTC (09:17 giờ Việt Nam).
6. Email tự động chỉ gửi nếu: hóa đơn đã chốt; tùy chọn gửi tự động bật; email người thuê hợp lệ; đến ngày gửi; hóa đơn chưa gửi thành công trước đó. Email lỗi được ghi log và thử lại ở lượt chạy kế tiếp. Hóa đơn tương lai, thiếu email và (nếu cấu hình) đã thanh toán sẽ được bỏ qua.

**Chống gửi trùng:** lịch sử thành công được kiểm tra theo năm/tháng/phòng trước mỗi lượt gửi. Không bấm gửi lại thủ công nếu đã gửi thành công, trừ khi chủ trọ thực sự muốn gửi bản thay thế. Tránh chạy hai lần đồng thời từ giao diện và workflow cho cùng một hóa đơn.

## F. Cách sử dụng theo tháng

1. Chọn tháng/năm ở thanh bên.
2. Vào **Tổng quan** để cài giá điện, nước, phí khác và ngày bắt đầu gửi.
3. Vào **Phòng & người thuê** để quản lý hồ sơ gốc, email và giá thuê.
4. Vào **Hóa đơn & điện nước** để nhập chỉ số. Khi tạo hóa đơn tháng mới, chỉ số cũ được kế thừa từ chỉ số mới của tháng trước nếu có.
5. Đối chiếu tổng tiền → chọn trạng thái thanh toán → đánh dấu **Chốt hóa đơn** → bật **Cho phép email tự động** → Lưu hóa đơn.
6. Tại **Gửi email**, có thể gửi PDF cho một người hay gửi các hóa đơn đã chốt chưa gửi. Lịch tự động chạy độc lập qua GitHub Actions.
7. Tại **Lịch sử & dữ liệu**, tải CSV, ZIP PDF và nhật ký email.

## Ghi chú bảo mật/vận hành

- Mật khẩu quản trị là lớp khóa giao diện đơn giản, không phải hệ thống multi-user/role enterprise. Dùng mật khẩu dài, giữ URL app ở chế độ không công khai nếu phù hợp, không chia sẻ PIN.
- Khóa Supabase máy chủ có quyền rất cao: chỉ lưu trong Streamlit Secrets và GitHub Actions Secrets. Nếu khóa bị lộ, rotate ngay.
- Supabase giữ dữ liệu lâu dài hơn file SQLite trên Streamlit Cloud; vẫn nên thực hiện backup định kỳ từ dashboard Supabase.
- GitHub Actions cron không phải hệ thống gửi thư có cam kết thời điểm chính xác tuyệt đối. Workflow có thể trễ do tải nền tảng. Tab Actions hiển thị kết quả và log. Với repo công khai, GitHub có thể tự tắt workflow theo lịch nếu repo không có hoạt động trong 60 ngày; kiểm tra tab Actions định kỳ và bật lại khi cần.
- Không đưa dữ liệu thật của người thuê vào GitHub; chỉ database Supabase chứa dữ liệu thực.
