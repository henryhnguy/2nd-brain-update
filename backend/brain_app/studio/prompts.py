"""Prompt builders (system, user) for every Studio step. All output is Vietnamese."""
from typing import Any, Dict, List

BASE_RULES = (
    "Bạn là trợ lý soạn tài liệu làm việc trong hệ thống Second Brain cá nhân. "
    "Viết bằng tiếng Việt rõ ràng, súc tích, dùng Markdown. "
    "Nguồn tham khảo được đánh số [n]; khi dùng thông tin từ nguồn nào, trích dẫn đúng số đó ngay sau ý (ví dụ: [2] hoặc [1][3]). "
    "TUYỆT ĐỐI không bịa số liệu, ngưỡng, tên tiêu chuẩn, mã biểu mẫu hay trích dẫn không có trong nguồn."
)


def _p(params: Dict[str, Any], key: str, default: str = "không nêu") -> str:
    v = params.get(key)
    return str(v).strip() if v not in (None, "") else default


def _kv(params: Dict[str, Any], labels: Dict[str, str]) -> str:
    return "\n".join(f"- {label}: {_p(params, k)}" for k, label in labels.items())


# ------------------------------------------------------------------ lesson
def lesson_outline(params, context: str):
    system = BASE_RULES + (
        " Nhiệm vụ: đề xuất DÀN Ý bài học. Chỉ trả về JSON dạng "
        '{"sections":[{"title":"...","brief":"..."}]}, từ 6 đến 10 mục, theo thứ tự: Mục tiêu học tập; '
        "Kiến thức nền (nếu cần); 2-4 mục Nội dung chính; Ví dụ / thực hành; Bài tập; Câu hỏi kiểm tra nhanh; Tóm tắt. "
        '"brief" là 1-2 câu nêu mục đó sẽ dạy gì.')
    user = (f"THÔNG TIN BÀI HỌC:\n{_kv(params, {'topic': 'Chủ đề', 'audience': 'Đối tượng', 'level': 'Trình độ', 'duration_min': 'Thời lượng (phút)', 'objectives': 'Mục tiêu mong muốn'})}\n\n"
            f"NGUỒN TRONG KHO (để dàn ý bám sát kiến thức thật):\n{context or '(không tìm thấy nguồn liên quan)'}")
    return system, user


def lesson_section(params, outline: List[Dict], section: Dict, context: str):
    system = BASE_RULES + (
        " Nhiệm vụ: viết NỘI DUNG cho đúng một mục của bài học, không lặp lại phần của mục khác, không viết tiêu đề mục (hệ thống tự thêm). "
        "Ưu tiên kiến thức trong nguồn và trích dẫn [n]. Nếu nguồn không đủ, bạn có thể bổ sung kiến thức chung nhưng "
        "phải đánh dấu rõ cụm '(kiến thức chung)' trong đoạn đó. Với mục Bài tập / Câu hỏi kiểm tra, kèm đáp án gợi ý. "
        "Độ dài vừa phải, phù hợp thời lượng bài học.")
    toc = "\n".join(f"{i + 1}. {o['title']}" for i, o in enumerate(outline))
    user = (f"BÀI HỌC:\n{_kv(params, {'topic': 'Chủ đề', 'audience': 'Đối tượng', 'level': 'Trình độ', 'duration_min': 'Thời lượng (phút)'})}\n\n"
            f"DÀN Ý CẢ BÀI:\n{toc}\n\nMỤC CẦN VIẾT: {section['title']}\nGợi ý: {section.get('brief', '')}\n\n"
            f"NGUỒN:\n{context or '(không có nguồn liên quan)'}")
    return system, user


# --------------------------------------------------------------------- sop
def sop_questions(params, context: str):
    system = BASE_RULES + (
        " Nhiệm vụ: trước khi viết SOP, hãy liệt kê những thông tin CÒN THIẾU mà người viết phải xác nhận, "
        "vì SOP sai còn tệ hơn không có SOP. Chỉ hỏi những gì thật sự cần và chưa có trong thông tin/nguồn "
        "(người chịu trách nhiệm, ngưỡng đạt/không đạt, tần suất, biểu mẫu, quy tắc xử lý lỗi, phê duyệt…). "
        'Chỉ trả về JSON dạng {"questions":[{"question":"...","why":"..."}]}, tối đa 8 câu, ngắn gọn.')
    user = (f"THÔNG TIN QUY TRÌNH:\n{_kv(params, {'process_name': 'Tên quy trình', 'purpose': 'Mục đích', 'department': 'Bộ phận', 'roles': 'Vai trò', 'standards': 'Tiêu chuẩn liên quan', 'notes': 'Ghi chú'})}\n\n"
            f"NGUỒN TRONG KHO:\n{context or '(không tìm thấy nguồn liên quan)'}")
    return system, user


def sop_section(params, outline: List[Dict], section: Dict, questions: List[Dict], context: str):
    system = BASE_RULES + (
        " Nhiệm vụ: viết NỘI DUNG cho đúng một mục của SOP (không viết tiêu đề mục). SOP phải chính xác và thực thi được. "
        "Thứ tự ưu tiên thông tin: (1) câu trả lời người dùng cung cấp, (2) nguồn trong kho [n], (3) không có gì khác. "
        "Nếu thiếu thông tin để viết một chi tiết (người thực hiện, ngưỡng, tần suất, mã biểu mẫu...), "
        "KHÔNG đoán: ghi đúng cú pháp '⚠️ [CẦN BỔ SUNG: nội dung còn thiếu]'. "
        "Câu mệnh lệnh ngắn, mỗi bước một hành động. Với mục 'Quy trình thực hiện' bắt buộc dùng bảng Markdown "
        "có cột: Bước | Hoạt động | Người thực hiện | Tiêu chí đạt / Biểu mẫu. Với mục 'Trách nhiệm' dùng bảng Vai trò | Trách nhiệm.")
    qa = "\n".join(f"- {q['question']} → {q['answer'].strip()}" for q in questions if (q.get("answer") or "").strip()) or "(chưa có)"
    toc = "\n".join(f"{i + 1}. {o['title']}" for i, o in enumerate(outline))
    user = (f"THÔNG TIN QUY TRÌNH:\n{_kv(params, {'process_name': 'Tên quy trình', 'purpose': 'Mục đích', 'department': 'Bộ phận', 'roles': 'Vai trò', 'standards': 'Tiêu chuẩn liên quan', 'notes': 'Ghi chú'})}\n\n"
            f"NGƯỜI DÙNG ĐÃ XÁC NHẬN:\n{qa}\n\nCẤU TRÚC SOP:\n{toc}\n\n"
            f"MỤC CẦN VIẾT: {section['title']}\nYêu cầu: {section.get('brief', '')}\n\nNGUỒN:\n{context or '(không có nguồn liên quan)'}")
    return system, user


def sop_review(params, markdown: str):
    system = (
        "Bạn là chuyên gia kiểm soát chất lượng tài liệu, rà soát một bản SOP nháp. Tìm: bước mơ hồ hoặc không thực thi được; "
        "thiếu người chịu trách nhiệm; thiếu tiêu chí đạt/không đạt hoặc tần suất; mâu thuẫn giữa các mục; chi tiết trông như bịa "
        "(không có căn cứ trong tài liệu). Chỉ trả về JSON dạng "
        '{"findings":[{"severity":"high|medium|low","section":"...","issue":"...","suggestion":"..."}]}, tối đa 12 phát hiện, '
        "quan trọng nhất trước. Không khen ngợi, không lặp lại các chỗ đã ghi '[CẦN BỔ SUNG'.")
    return system, f"SOP: {_p(params, 'process_name')}\n\n{markdown}"


# --------------------------------------------------------------- synthesis
def source_summary(topic: str, title: str, text: str):
    system = (
        "Tóm tắt một nguồn tài liệu để phục vụ việc viết tài liệu tổng hợp về một chủ đề. "
        "Chỉ nêu 3-6 ý chính/dữ kiện QUAN TRỌNG liên quan đến chủ đề, dạng gạch đầu dòng ngắn, giữ nguyên số liệu và thuật ngữ. "
        "Không thêm thông tin ngoài nguồn.")
    return system, f"CHỦ ĐỀ: {topic}\n\nNGUỒN: {title}\n\n{text}"


def synthesis_outline(params, numbered_summaries: str):
    system = BASE_RULES + (
        " Nhiệm vụ: lập DÀN Ý tài liệu tổng hợp bằng cách gom các nguồn theo chủ đề. Chỉ trả về JSON dạng "
        '{"sections":[{"title":"...","brief":"...","sources":[1,2]}]}, 4 đến 8 mục, mỗi mục liệt kê số các nguồn sẽ dùng. '
        "Mở đầu bằng tổng quan, kết thúc bằng kết luận/khuyến nghị nếu phù hợp. Mỗi nguồn nên được dùng ít nhất một lần.")
    user = (f"YÊU CẦU:\n{_kv(params, {'topic': 'Chủ đề', 'goal': 'Mục tiêu tài liệu', 'audience': 'Người đọc', 'length': 'Độ dài'})}\n\n"
            f"TÓM TẮT CÁC NGUỒN:\n{numbered_summaries}")
    return system, user


def synthesis_section(params, outline: List[Dict], section: Dict, context: str):
    system = BASE_RULES + (
        " Nhiệm vụ: viết NỘI DUNG cho đúng một mục của tài liệu tổng hợp (không viết tiêu đề mục). "
        "MỌI nhận định, dữ kiện và số liệu phải kèm trích dẫn [n] theo đúng số nguồn được cho. "
        "Khi các nguồn mâu thuẫn, nêu rõ sự khác biệt và trích dẫn cả hai. Nếu nguồn không đủ để nói điều gì đó, "
        "hãy nói là chưa có thông tin trong kho thay vì suy đoán.")
    toc = "\n".join(f"{i + 1}. {o['title']}" for i, o in enumerate(outline))
    length = {"ngắn": "khoảng 120-200 từ", "vừa": "khoảng 200-350 từ", "dài": "khoảng 350-600 từ"}.get(
        _p(params, "length", "vừa").lower(), "khoảng 200-350 từ")
    user = (f"YÊU CẦU:\n{_kv(params, {'topic': 'Chủ đề', 'goal': 'Mục tiêu tài liệu', 'audience': 'Người đọc'})}\n\n"
            f"DÀN Ý CẢ TÀI LIỆU:\n{toc}\n\nMỤC CẦN VIẾT: {section['title']} ({length})\nGợi ý: {section.get('brief', '')}\n\n"
            f"NGUỒN:\n{context}")
    return system, user
