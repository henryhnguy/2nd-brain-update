"""Document kinds offered by Studio: form fields (rendered generically by the UI) and fixed templates."""
from typing import Any, Dict, List

KINDS: Dict[str, Dict[str, Any]] = {
    "lesson": {
        "label": "Bài học",
        "icon": "graduation",
        "description": "Soạn bài học có mục tiêu, nội dung, ví dụ, bài tập và câu hỏi kiểm tra, bám theo kiến thức trong kho.",
        "steps": ["Đầu vào", "Dàn ý", "Viết bài", "Rà soát & xuất"],
        "title_from": "topic",
        "fields": [
            {"key": "topic", "label": "Chủ đề bài học", "type": "text", "required": True,
             "placeholder": "VD: Kiểm tra độ bám dính keo bonding đế giày"},
            {"key": "audience", "label": "Đối tượng học", "type": "text", "placeholder": "VD: QA mới vào nghề"},
            {"key": "level", "label": "Trình độ", "type": "select", "options": ["Cơ bản", "Trung cấp", "Nâng cao"]},
            {"key": "duration_min", "label": "Thời lượng (phút)", "type": "number", "placeholder": "45"},
            {"key": "objectives", "label": "Mục tiêu mong muốn (tùy chọn)", "type": "textarea",
             "placeholder": "Học viên sau bài học cần làm được gì?"},
        ],
    },
    "sop": {
        "label": "Quy trình SOP",
        "icon": "clipboard",
        "description": "Viết SOP theo mẫu chuẩn. AI hỏi lại thông tin còn thiếu, không bịa số liệu, rà soát và lưu phiên bản.",
        "steps": ["Đầu vào", "Câu hỏi bổ sung", "Dàn ý", "Viết SOP", "Rà soát & phiên bản"],
        "title_from": "process_name",
        "fields": [
            {"key": "process_name", "label": "Tên quy trình", "type": "text", "required": True,
             "placeholder": "VD: Kiểm tra chất lượng đế giày trước khi đóng hàng"},
            {"key": "purpose", "label": "Mục đích", "type": "textarea"},
            {"key": "department", "label": "Bộ phận áp dụng", "type": "text"},
            {"key": "roles", "label": "Các vai trò tham gia", "type": "textarea",
             "placeholder": "VD: QA, Tổ trưởng chuyền, Quản lý chất lượng"},
            {"key": "standards", "label": "Tiêu chuẩn / quy định liên quan", "type": "text",
             "placeholder": "VD: AQL 2.5, tiêu chuẩn của khách hàng…"},
            {"key": "notes", "label": "Ghi chú thêm", "type": "textarea"},
        ],
    },
    "synthesis": {
        "label": "Tài liệu tổng hợp",
        "icon": "layers",
        "description": "Tổng hợp nhiều nguồn trong kho thành một tài liệu dài, mỗi ý có trích dẫn [n] và có kiểm tra nguồn.",
        "steps": ["Đầu vào", "Chọn nguồn & dàn ý", "Viết tài liệu", "Kiểm tra nguồn & xuất"],
        "title_from": "topic",
        "fields": [
            {"key": "topic", "label": "Chủ đề cần tổng hợp", "type": "text", "required": True,
             "placeholder": "VD: Các lỗi thường gặp ở đế cupsole và cách phòng ngừa"},
            {"key": "goal", "label": "Mục tiêu tài liệu", "type": "select",
             "options": ["Tổng quan", "So sánh", "Báo cáo", "Hướng dẫn"]},
            {"key": "audience", "label": "Người đọc", "type": "text"},
            {"key": "length", "label": "Độ dài", "type": "select", "options": ["Ngắn", "Vừa", "Dài"]},
        ],
    },
}

SOP_TEMPLATE: List[Dict[str, str]] = [
    {"title": "Mục đích", "brief": "Vì sao có quy trình này, kết quả mong muốn."},
    {"title": "Phạm vi áp dụng", "brief": "Áp dụng cho ai, sản phẩm/công đoạn nào, khi nào; trường hợp loại trừ."},
    {"title": "Định nghĩa và viết tắt", "brief": "Các thuật ngữ, từ viết tắt dùng trong quy trình."},
    {"title": "Trách nhiệm", "brief": "Bảng vai trò – trách nhiệm (Vai trò | Trách nhiệm chính)."},
    {"title": "Tài liệu và biểu mẫu tham chiếu", "brief": "Tiêu chuẩn, hướng dẫn, biểu mẫu liên quan (chỉ những gì có căn cứ)."},
    {"title": "Quy trình thực hiện", "brief": "BẢNG các bước: Bước | Hoạt động | Người thực hiện | Tiêu chí đạt / Biểu mẫu."},
    {"title": "Tiêu chí chấp nhận và kiểm soát", "brief": "Ngưỡng đạt/không đạt, tần suất kiểm tra, cách ghi nhận."},
    {"title": "Xử lý sự cố và lỗi thường gặp", "brief": "Tình huống bất thường, cách xử lý, ai quyết định, khi nào báo cáo."},
    {"title": "Hồ sơ lưu trữ", "brief": "Hồ sơ nào được lưu, ai lưu, lưu bao lâu, ở đâu (chỉ khi có thông tin)."},
]
SOP_PROCEDURE_TITLE = "Quy trình thực hiện"
