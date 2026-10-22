# Web quản lý tiền trọ — GitHub + Streamlit

Ứng dụng giao diện web dùng Streamlit, SQLite, ReportLab và SMTP. Có quản lý tiền phòng/điện/nước, thông tin người thuê, trạng thái thanh toán, xuất CSV/PDF và gửi hóa đơn email riêng từng phòng.

## Xem trước giao diện

Tệp `demo_preview.png` là hình mockup minh họa giao diện và số liệu giả lập. Khi triển khai app, dữ liệu thật ban đầu sẽ không có người thuê nào được thêm tự động; hãy nhập lại từ trang web.

## Cấu trúc dự án

- `app.py`: giao diện quản lý và gửi email thủ công.
- `email_utils.py`: kết nối SMTP, đọc thông tin từ `.env` (local) hoặc `st.secrets` (Streamlit Cloud).
- `auto_email.py`: tác vụ gửi hóa đơn theo lịch, chạy ở máy chủ/tác vụ riêng có quyền truy cập cùng database.
- `requirements.txt`: thư viện Python.
- `packages.txt`: font DejaVu để PDF hỗ trợ tiếng Việt trên Linux.
- `.streamlit/config.toml`: giao diện màu xanh.
- `.env.example`: mẫu thiết lập local.
- `streamlit_secrets.example.toml`: mẫu định dạng secrets cho Streamlit Cloud; không có mật khẩu thật.

## A. Triển khai web thử nghiệm bằng GitHub + Streamlit Community Cloud

### 1. Tạo repository GitHub

1. Đăng nhập `https://github.com`.
2. Bấm **New repository**; đặt tên ví dụ `quan-ly-tien-tro`.
3. Chọn Public để triển khai dễ nhất, hoặc Private nếu tài khoản/cấu hình Streamlit cho phép triển khai repo riêng.
4. Tạo repository.

### 2. Tải source lên GitHub bằng trình duyệt

1. Giải nén tệp ZIP của dự án trên máy.
2. Mở repository GitHub → **Add file → Upload files**.
3. Tải lên `app.py`, `email_utils.py`, `auto_email.py`, `requirements.txt`, `packages.txt`, `.gitignore`, `README.md`, `.env.example` và `streamlit_secrets.example.toml`.
4. Thư mục `.streamlit` chứa `config.toml`: dùng **Add file → Create new file**, nhập đường dẫn `.streamlit/config.toml`, sau đó sao chép nội dung từ file gốc vào.
5. Bấm **Commit changes**.

**Không tải lên** `.env`, `secrets.toml`, hoặc `quan_ly_tien_tro.sqlite3`. Đó có thể là mật khẩu và dữ liệu riêng tư.

### 3. Triển khai ứng dụng

1. Mở `https://share.streamlit.io` và đăng nhập bằng GitHub.
2. Chọn **Create app** (hoặc **New app**).
3. Chọn repository vừa tạo, branch `main`, file chính `app.py`.
4. Chọn **Deploy**. Khi triển khai xong, Streamlit tạo URL có dạng `https://ten-app.streamlit.app`.
5. Mỗi lần cập nhật code đã commit lên GitHub, Streamlit Cloud sẽ nhận thay đổi và triển khai lại app.

Tài liệu chính thức: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

## B. Cấu hình email trên Streamlit Cloud

1. Vào trang quản lý app trên Streamlit Community Cloud.
2. Mở **App settings → Secrets**.
3. Sao chép nội dung mẫu dưới đây, thay bằng thông tin tài khoản gửi thật, rồi Save:

```toml
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USE_SSL = false
SMTP_USERNAME = "your-email@gmail.com"
SMTP_PASSWORD = "your-google-app-password"
SMTP_FROM_EMAIL = "your-email@gmail.com"
SMTP_FROM_NAME = "Quan ly tien phong tro"
```

Với Gmail, hãy dùng Google App Password nếu tài khoản đáp ứng điều kiện của Google; không dùng mật khẩu Gmail thông thường. Không commit mật khẩu, secrets hoặc file database lên GitHub.

Sau khi lưu secrets, khởi động lại ứng dụng nếu cần. Trong app, chọn phòng có email và bấm gửi thử vào email của chính bạn trước. Kiểm tra đúng người nhận, số tiền và PDF trước khi gửi hàng loạt.

## C. Chạy local trên Windows

```powershell
py -m pip install -r requirements.txt
Copy-Item .env.example .env
py -m streamlit run app.py
```

Sửa `.env` bằng Notepad và nhập SMTP nếu muốn gửi email từ máy. Web thường mở tại `http://localhost:8501`.

## D. Quan trọng: dữ liệu và gửi tự động trên Streamlit Cloud

- Streamlit Community Cloud **không bảo đảm dữ liệu file cục bộ được lưu bền vững**. SQLite phù hợp cho bản demo/kiểm tra giao diện; không nên dùng bản triển khai này để lưu sổ tiền trọ thật lâu dài nếu chưa có sao lưu/di chuyển database. Tài liệu Streamlit khuyến nghị dùng kho dữ liệu ngoài khi cần lưu bền vững.
- Nút gửi email thủ công trong giao diện có thể dùng sau khi cấu hình SMTP.
- `auto_email.py` không tự chạy chỉ vì bạn triển khai app lên Streamlit Cloud. Lịch gửi định kỳ cần một máy chủ/tác vụ theo lịch riêng và phải dùng chung một database bền vững với ứng dụng. GitHub Actions cũng không tự nhìn thấy database SQLite ở trong container Streamlit.
- Để sử dụng thật 24/7, khuyến nghị chuyển database sang PostgreSQL/Supabase (hoặc DB dịch vụ tương đương), cấu hình sao lưu và chạy tác vụ gửi lịch trên một môi trường có quyền đọc đúng database đó. Cần hoàn thành bước chuyển database trước khi bật gửi tự động cho dữ liệu thật.

Tài liệu chính thức về lưu trữ: https://docs.streamlit.io/develop/concepts/connections/connecting-to-data

## E. Thử tính năng

1. Chọn tháng/năm và cấu hình giá điện, giá nước, phí khác và số phòng.
2. Chọn phòng; nhập giá phòng, thông tin người ở, email, điện/nước cũ và mới.
3. Chọn trạng thái thanh toán, ghi chú nếu cần và bấm lưu.
4. Kiểm tra bảng tổng hợp, xuất CSV/PDF từng phòng hoặc PDF dạng ZIP.
5. Cấu hình SMTP rồi gửi thử một phòng trước. Lịch sử gửi hiển thị trong app.

## An toàn dữ liệu

- Không đưa mật khẩu SMTP hoặc dữ liệu người thuê lên repository công khai.
- Không có chức năng đăng nhập/phân quyền trong phiên bản demo này; không chia sẻ công khai với dữ liệu người thuê thật.
- Tải bản sao lưu định kỳ. Trước khi dùng thật, cần bổ sung đăng nhập/quyền truy cập, database bền vững và tác vụ gửi định kỳ độc lập.
