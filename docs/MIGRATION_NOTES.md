# Migration Notes

> Breaking changes giữa các phiên bản. User có profile từ phiên bản cũ đọc file này để biết phải làm gì.

---

## v0.x → v1.0 (Batch A/B cleanup)

### Breaking changes

1. **Profile schema v1 → v2 (Batch B P0.3)**: Profile cũ có `pipeline` field (PipelineConfig serialization) **không còn được auto-migrate**. `ProfileManager.get()` raise `ValueError` khi gặp profile v1 — chương trình sẽ crash với message hướng dẫn re-learn.
2. **`--fast-learning` đổi semantic (Batch A P0.2)**: Trước là *"skip optimizer"*, giờ là *"skip ProseRichness validation trong learning phase"*. Optimizer đã bị xóa hoàn toàn.
3. **Field `optimizer_score` deprecated**: Profile cũ có field này → vô hại (TypedDict `total=False`), nhưng không còn được đọc/ghi.

### Cách migrate profile cũ

#### Option A — Bulk re-learn (recommended nếu có nhiều profile)

```bash
# Preview profile nào sẽ bị xóa (dry-run mặc định, an toàn):
python main.py --bulk-relearn

# Lọc subset bằng regex:
python main.py --bulk-relearn --pattern "fanfiction|royalroad"

# Sau khi review, thực hiện (cần typed confirmation):
python main.py --bulk-relearn --pattern "fanfiction|royalroad" --apply
# Prompt sẽ yêu cầu gõ chính xác: "delete 2 profiles"
```

**UX an toàn:**
- Mặc định là **dry-run** — chỉ liệt kê profile sẽ bị xóa, không touch file
- `--apply` kích hoạt thật, kèm typed confirmation prompt
- Pattern regex có thể greedy hơn user nghĩ — ví dụ `--pattern "net"` match cả `fanfiction.net` và `novelfire.net`. Luôn dry-run trước.

#### Option B — Per-site re-learn (1-2 site cụ thể)

Thêm vào `links.txt`:

```
!relearn fanfiction.net
!relearn royalroad.com
https://royalroad.com/fiction/xxx/chapter-1
```

`!relearn` chạy trước URL — profile bị xóa, sau đó URL trigger learning phase mới.

#### Option C — Nuke toàn bộ và re-learn từ đầu

```bash
rm data/site_profiles.json
python main.py links.txt
```

Cẩn thận: mất tất cả profile, kể cả profile v2 còn dùng được.

### Verify migration thành công

Sau re-learn, mở `data/site_profiles.json`. Profile mới phải có:

- `"profile_version": 2`
- **KHÔNG có** key `"pipeline"`
- **KHÔNG có** key `"optimizer_score"`

Nếu vẫn còn `"pipeline"` → migration chưa hoàn tất, chạy `--bulk-relearn --pattern <domain> --apply` lại.

### Symptoms của profile chưa migrate

Nếu thấy traceback dạng:

```
ValueError: Profile 'fanfiction.net' ở format v1 cũ (có 'pipeline' field).
Cần re-learn. Thêm '!relearn fanfiction.net' vào links.txt
hoặc chạy 'python main.py --bulk-relearn'.
```

→ Profile v1, làm theo Option A hoặc B ở trên.
