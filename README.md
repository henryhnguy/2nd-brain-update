# 🧠 Second Brain AI — Bộ não thứ hai cá nhân

Ứng dụng quản lý tri thức cá nhân chạy **trên máy của bạn**: ghi chú theo PARA, kho tài liệu, tìm kiếm lai (ngữ nghĩa + từ khóa), trợ lý AI trả lời có trích dẫn nguồn, và **Studio** để soạn Bài học, SOP, Tài liệu tổng hợp từ chính kho kiến thức đó.

## Tính năng

- **Ghi chú Markdown** theo PARA (Projects, Areas, Resources, Archives), thẻ, ghim, xem trước.
- **Kho tài liệu:** tải PDF, Markdown, TXT, CSV, JSON; tự trích xuất, chia đoạn và lập chỉ mục.
- **Tìm kiếm lai:** kết hợp embedding (ngữ nghĩa) và SQLite FTS5 (từ khóa, không phân biệt dấu) bằng Reciprocal Rank Fusion. Từ khóa vẫn chạy khi embedding lỗi.
- **Chat RAG:** hỏi đáp trên kho của bạn, có trích dẫn nguồn và điểm khớp; câu hỏi nối tiếp được hiểu theo ngữ cảnh.
- **Hai cách tạo embedding:** Google Gemini (API) hoặc model đa ngôn ngữ chạy trên máy (`fastembed`). Đổi cách thì app tự index lại ở nền.
- **Danh sách model chat lấy trực tuyến** từ Gemini và OpenRouter.
- **Studio:**
  - *Bài học:* dàn ý → viết từng mục → bài tập và câu hỏi kiểm tra.
  - *SOP:* AI hỏi thông tin còn thiếu, không bịa số liệu (chỗ thiếu ghi `⚠️ [CẦN BỔ SUNG: …]`), rà soát, phiên bản 1.0/1.1/2.0, lịch sử sửa đổi.
  - *Tài liệu tổng hợp:* tóm tắt từng nguồn, gom chủ đề, mỗi ý có trích dẫn `[n]`, kiểm tra nguồn tự động.

## Cài đặt và chạy (Windows, PowerShell)

Cần **Python 3.10 trở lên** (kiểm tra bằng `python --version`). Chạy các lệnh từ thư mục gốc của dự án:

```powershell
python -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\backend\.venv\Scripts\python.exe run.py
```

Sau đó mở **http://localhost:8000** (app thường tự mở trình duyệt). Lần sau chỉ cần chạy `start.bat` hoặc lệnh `run.py` ở trên. Không cần "activate" môi trường ảo.

Tùy chọn, nếu muốn embedding chạy trên máy (không cần API key, lần đầu tải 0,2–2,2 GB):

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-local.txt
```

## Cấu hình lần đầu

1. Mở **Cài đặt** (góc dưới bên trái) → **Google Gemini** (hoặc OpenRouter): nhập API key, chọn model, Lưu.
2. Tab **Embedding:** chọn phương án rồi bấm **Lưu & kiểm tra**.
3. Thử **Tìm kiếm**, **Chat**, rồi **Studio**.

## Kiểm thử

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
cd backend
..\backend\.venv\Scripts\python.exe -m pytest -q
```

Test không cần API key hay Internet (các dịch vụ ngoài được giả lập) và dùng cơ sở dữ liệu tạm, không đụng dữ liệu của bạn.

## Phát triển giao diện

Giao diện đã build sẵn trong `frontend/dist` (được commit để chạy mà không cần Node.js). Khi sửa mã giao diện:

```powershell
cd frontend
npm install
npm run dev      # http://localhost:5173, tự chuyển /api sang backend :8000
npm run build    # build lại frontend/dist, nhớ commit thư mục này
```

## Cấu trúc

```
backend/
  brain_app/
    main.py            # FastAPI, phục vụ API và frontend/dist
    database.py        # SQLite: notes, documents, chunks (+FTS5), chat, studio
    rag/               # chunker, embeddings, vector_store (lai), reindex, llm, model_catalog, rag_service
    routers/           # notes, documents, chat, search, settings, studio
    studio/            # store, engine, prompts, quality, jobs
  tests/               # kiểm thử tự động
  data/                # CƠ SỞ DỮ LIỆU CỦA BẠN (không commit)
frontend/              # React + Vite + Tailwind
run.py, start.bat      # chạy nhanh trên Windows
```

## Bảo mật

- API key được lưu **dạng văn bản thô** trong `backend/data/*.db`. File này đã được loại khỏi git; **không chia sẻ nó**.
- App **chưa có đăng nhập**. Chỉ chạy trên máy cá nhân (mặc định `127.0.0.1`). Nếu đặt biến `PORT`, `run.py` sẽ mở ra mạng (`0.0.0.0`); hãy đặt kèm `HOST=127.0.0.1` nếu không muốn vậy: `$env:HOST="127.0.0.1"; $env:PORT=8010`.
- AI có thể sai. Đọc các cảnh báo kiểm tra nguồn và rà soát trước khi dùng tài liệu, đặc biệt với SOP.
