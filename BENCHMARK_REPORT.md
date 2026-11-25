# Benchmark & Observability Report — Day 14

**Họ tên:** Tran Anh Tu (MSSV 2023604610)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11. Mục 2–3: Python 3.13, chạy trực tiếp `python app.py` (Bước 1). Mục 4–5: Docker Desktop 29.0.1, stack `production/` (2 agent + Nginx + Prometheus + Grafana + Jaeger + Locust).

> Số liệu mục 2–3 lấy từ `reports/*.json`; mục 4 từ `benchmark-results/chaos_results.json` + `chaos_log.txt` (script poll Prometheus API mỗi 5 s) và ảnh trong `screenshots/`; mục 5 từ `benchmark-results/scale_*_stats.csv`. Trên máy, cổng 8080/3000 đã bị chiếm nên Nginx chạy ở 8081 và Grafana ở 3001 (`NGINX_PORT`, `GRAFANA_PORT`).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Latency cơ bản ~200 ms; p95 nên ≤ 2.5× để người dùng không thấy chậm |
| Error rate `/ask` | < 2 % | Mock LLM có 1 % lỗi upstream; 2 % cho phép dao động mà vẫn bắt được sự cố thật |
| Accuracy trên golden dataset | ≥ 100 % (gate CI) | Dataset nhỏ (23 câu), mọi regression đều phải chặn |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`, 300 request)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.16 | 198.3 | 248.7 | 1704.8 | 1.00 % | PASS |
| 10 | 37.2 | 195.6 | 471.3 | 1692.5 | 1.00 % | PASS |
| 50 | 46.94 | 578.3 | 2017.0 | 2369.9 | 2.33 % | FAIL |
| 100 | 29.77 | 1851.1 | 7128.5 | 7588.6 | 2.00 % | FAIL |

**Nhận xét:** RPS tăng gần tuyến tính từ c=1 → c=10 (4.2 → 37.2), rồi chững ở c=50 (46.9) và **giảm** ở c=100 (29.8). Quá ~c=50 hệ thống bão hoà (một process, một event loop), request xếp hàng nên p95 tăng vọt (7.1 s), RPS không tăng nữa. Lưu ý: ở c=1 và c=10 p95 đạt SLO nhưng p99 ~1.7 s do request "slow" (3 %).

### 2.2 Tail latency (concurrency 20)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 277.0 | 545.0 | 642.8 |
| 0.03 (mặc định) | 284.6 | 509.1 | 1748.0 |
| 0.1 | 407.5 | 1720.7 | 1968.1 |

**Nhận xét:** p99 nhạy nhất với request chậm (642 → 1748 ms khi từ 0 lên 0.03), trong khi avg gần như không đổi (277 → 285 ms). Average che giấu tail latency nên SLO phải đặt theo p95/p99. Chú ý: run `slow_0` có p95 545 ms (FAIL SLO) dù không có request chậm — do đo ở concurrency 20 với jitter và chỉ 300 mẫu, nên chênh lệch p95 giữa các lần chạy là nhiễu.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`, 23 câu)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 56.5 | 109.1 | 115.4 |
| Tổng cost (USD) | 0.000396 | 0.000762 | 0.000806 |
| Cost / câu đúng (USD) | 0.00039615 | 0.00003627 | 0.00003504 |
| Quality gate | FAIL | PASS (≥ 80 %) | PASS (≥ 100 %, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Thêm entry JWT / API key vào `KNOWLEDGE_BASE` (`develop/utils/mock_llm.py`) |
| scaling-03 | cpu, memory, custom metrics | Thêm entry Kubernetes HPA vào `KNOWLEDGE_BASE` |

Không sửa `golden_dataset.jsonl`.

**Trade-off v1 vs v2:** v2 tốn nhiều token hơn (~2×) và có thêm bước retrieval (p95 eval 1545 ms ở lần chạy đầu do một request slow ngẫu nhiên, 221 ms ở lần sau), nhưng accuracy từ 4 % lên 100 %. "Cost / câu đúng" của v2 rẻ hơn v1 ~11 lần (0.000035 vs 0.000396 USD) — v1 rẻ mỗi câu nhưng gần như toàn câu sai.

**Dùng exit code làm quality gate CI:** `run_eval.py` trả exit code ≠ 0 khi accuracy < `--min-accuracy` hoặc có regression so với `--baseline`. Job CI chạy `python eval/run_eval.py --min-accuracy 1.0 --baseline reports/eval_v2.json`; job fail thì branch protection chặn merge.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi có tải Locust 30 user — [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png): 16.1 req/s, error rate 1.04 %, p95 294 ms, in-flight 5, 2 instance up.
- [x] Trace chậm trong Jaeger — [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png) (chi tiết ở 4.3).
- [x] Trace lỗi trong Jaeger — [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png): trace `fae78d10c2fe8dfe0be791d6a81277bd`, `POST /ask` 503 trong 121 ms; span `chat mock-llm-small` (78.2 ms) và `agent.run` có status ERROR + event `exception`, attribute `error.type = upstream_unavailable`. Log tương ứng:
  ```json
  {"ts": "2026-11-25T10:47:59.788719+00:00", "level": "INFO", "service": "observable-agent", "instance": "1aa4a5f10c0c", "event": "llm_error", "trace_id": "fae78d10c2fe8dfe0be791d6a81277bd", "span_id": "d89cbb521b9ada40", "request_id": "166ad9180438", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
  ```
- [x] Trang Alerts của Prometheus với **2 alert firing** (`AgentHighErrorRate` + `AgentHighLatencyP95`, chạy `MOCK_ERROR_RATE=0.2` và `MOCK_SLOW_RATE=0.3` cùng lúc) — [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png).
- Ảnh dashboard trong lúc từng thí nghiệm: `screenshots/grafana-exp-{A-error,B-slow,C-cost,D-down,E-v1}.png`.

**Exercise 7.4 — trả lời** (số từ Prometheus, cửa sổ 5 phút, tải nền 30 user, 12:58 UTC):
1. p95 = **293 ms**, avg = **229 ms**, p50 = 174 ms, nhưng p99 = **1813 ms**. avg và p95 gần nhau, còn p99 cách xa gấp ~8 lần: ~3 % request "slow" của mock LLM nằm hết ở đuôi. avg che mất chúng, nên SLO phải đặt theo percentile.
2. Có chia gần đều: 8.7 và 9.8 req/s cho 2 instance (panel "Requests/s theo instance" hai đường gần trùng nhau). Nginx dùng round-robin; chênh lệch nhỏ do request chậm giữ kết nối lâu hơn.
3. Input tokens/s (1357) > output tokens/s (722) vì agent v2 nhét đoạn tài liệu retrieval vào prompt, nên prompt dài hơn câu trả lời.
4. `curl http://localhost:8081/metrics` → **404** (Nginx). `nginx.conf` chặn `/metrics` từ bên ngoài; chỉ Prometheus trong mạng Docker scrape trực tiếp `agent:8000/metrics`. Metrics lộ thông tin nội bộ (tên route, model, cost) và có thể bị dùng để gây tải.

`promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

### 4.2 Thí nghiệm "phá hệ thống"

Locust 30 user chạy suốt. Mỗi thí nghiệm: script đổi biến (`docker compose up -d agent`), poll `/api/v1/alerts` mỗi 5 s, ghi thời điểm `pending` và `firing`, rồi trả cấu hình về mặc định và chờ alert hết.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | pending 34 s → **firing 95 s** | Error rate (0.7 % → 19.5 %), Requests/s theo status (503 tăng), LLM calls error |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | pending 29 s → **firing 149 s** | Latency p50/p95/p99: p95 293 ms → 1.91 s, p50 gần như không đổi |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | pending 23 s → **firing 143 s** | Cost burn rate: ~$1.9/giờ → **$15.8/giờ** (~8× trong cửa sổ 5 m, đang tiếp tục tăng); LLM latency p95 tăng; p95 /ask 293 → 711 ms |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` | pending 15 s → **firing 45 s** | Instances up 2 → 1; Requests/s theo instance mất 1 đường |
| E | `AGENT_VERSION=v1` | Không có | — | Tokens/s 2054 → 1076 (giảm ~48 %), Retrieval hit ratio không còn dữ liệu, bảng "Phiên bản đang chạy" đổi sang v1; p95 giảm 291 → 199 ms |

**Phân tích:**
- Thời gian tới firing ≈ thời gian để `rate(...[1m])` (hoặc `[5m]`) phản ánh thay đổi + `for` của rule: A (`for: 1m`) ~95 s, B và C (`for: 2m`) ~145 s, D (`for: 30s`) 45 s. `pending` đến sớm (15–34 s) — đó là lúc điều kiện đã đúng nhưng chưa đủ lâu.
- **Phát hiện ở C:** ở tải nền 30 user với model small, cost burn đã **~$1.9–2.3/giờ**, ngay sát ngưỡng $2/giờ của `LLMCostBurnRateHigh`. Vì vậy sau khi trả về model small, alert vẫn firing (log: "alerts still active: LLMCostBurnRateHigh firing" lúc 19:52 và 19:58) và chỉ hết khi tải giảm. Ngưỡng này đang quá sát mức bình thường → dễ alert fatigue. Nên đặt ngưỡng theo baseline thực tế (ví dụ 2× mức trung bình tuần) hoặc dùng ngân sách theo ngày thay vì một con số cố định.
- **D:** error rate trên dashboard của agent vẫn ~0.9 % (xanh) dù 1 instance bị pause, vì request bị treo ở Nginx (504 thấy trong log Locust: `HTTPError('504 Server Error: Gateway Time-out for url: /ask')`) không bao giờ tới agent nên không được agent đếm. Cần giám sát ở tầng LB hoặc synthetic check từ bên ngoài.
- Ở B, p95/p99 tăng mạnh còn p50 gần như không đổi — đúng hành vi tail latency.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Metric hạ tầng chỉ đo "nhanh và không lỗi", còn v1 trả lời sai nhưng vẫn 200 và còn nhanh hơn. Cách phát hiện:
1. **Eval làm quality gate trong CI/CD**: chạy `run_eval.py --baseline` trước khi deploy; v1 chỉ 4.3 % accuracy nên bị chặn ngay (exit code ≠ 0), không lên được production.
2. **Metric chất lượng proxy + alert**: retrieval hit ratio (rơi về 0 khi đổi sang v1), tokens/câu, độ dài câu trả lời, alert khi lệch mạnh so với baseline; thêm alert trên `agent_info{version}` khi version đổi bất thường.
3. **Online eval**: định kỳ chạy golden dataset vào production (synthetic probe), lấy mẫu câu trả lời thật cho LLM-as-judge / con người chấm, và thu feedback người dùng (thumbs up/down).

### 4.3 Debug bằng trace

Trace chậm nhất trong 1 giờ (Jaeger → `observable-agent`, `minDuration=1s`, sắp xếp theo thời gian):

- `trace_id`: `a9af90fe637953c0601b41aa2af2279d`
- Tổng thời gian: **1864.6 ms** (`POST /ask`, status 200)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` — 1682.2 ms, ~90 %** tổng thời gian (`agent.run` 1762.1 ms; `agent.retrieve_context` chỉ 79.2 ms). Chậm ở LLM upstream, không ở code agent. Attribute `gen_ai.usage.input_tokens=37`, `output_tokens=24` — ít token, nên chậm không phải do prompt dài mà do request "slow" của LLM.
- Dòng log tương ứng (`docker compose logs agent | grep a9af90fe637953c0601b41aa2af2279d`):

```json
{"ts": "2026-11-25T10:45:02.280112+00:00", "level": "INFO", "service": "observable-agent", "instance": "1aa4a5f10c0c", "event": "llm_call", "trace_id": "a9af90fe637953c0601b41aa2af2279d", "span_id": "ac857c765a31ff44", "request_id": "1624322ab61e", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 37, "output_tokens": 24, "cost_usd": 2e-05, "llm_ms": 1682.3}
{"ts": "2026-11-25T10:45:02.280981+00:00", "level": "INFO", "service": "observable-agent", "instance": "1aa4a5f10c0c", "event": "http_request", "trace_id": "a9af90fe637953c0601b41aa2af2279d", "span_id": "ac857c765a31ff44", "request_id": "1624322ab61e", "method": "POST", "route": "/ask", "status": 200, "ms": 1863.2}
```

`llm_ms` trong log (1682.3) khớp span `chat` trong Jaeger (1682.2 ms) và `ms` (1863.2) khớp span gốc — log, trace và metric nối với nhau qua `trace_id`.

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu lấy từ `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (dòng Aggregated).

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 64.66 | 200 | 500 | 1700 | 77 / 7666 (1.0 %) |
| 3 | 62.70 | 200 | 600 | 2000 | 105 / 7434 (1.4 %) |

**Giải thích kết quả:** Scale từ 1 lên 3 instance **không cải thiện** RPS hay p95 (62.7 vs 64.7 RPS). Với 100 user Locust có thời gian chờ giữa các request, tải sinh ra bị giới hạn bởi số user và wait time, không phải bởi năng lực của một agent (một agent async vẫn còn dư tải ở 65 RPS). Vì vậy nút thắt không nằm ở agent; thêm instance chỉ có ích khi 1 instance đã bão hoà. Failures ~1 % khớp `MOCK_ERROR_RATE=0.01`; p99 ~1.7–2 s do `MOCK_SLOW_RATE` 3 %. Chạy một lần mỗi cấu hình nên chênh lệch nhỏ giữa 1 và 3 instance là nhiễu.

---

## 6. Kết luận

1. Trung bình che giấu tail latency; SLO phải theo p95/p99 (p99 tăng 2.7× khi slow rate 0 → 0.03 trong khi avg gần như không đổi).
2. Throughput có điểm bão hoà: tăng concurrency quá ~50 chỉ làm latency tệ hơn, RPS không tăng.
3. Đo chất lượng bằng golden dataset + exit code biến "đúng/sai" thành quality gate tự động; "cost / câu đúng" công bằng hơn "cost / câu".
4. Alert chỉ thấy những gì metric thấy: lỗi ở Nginx (D) và lỗi chất lượng (E) không làm dashboard đỏ. Ngưỡng alert phải đặt theo baseline đo thật — ngưỡng cost $2/giờ đang nằm ngay trên mức tải bình thường nên alert không tự hết.
