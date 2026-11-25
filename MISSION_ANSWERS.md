# Day 14 Lab — Mission Answers

**Họ tên:** Tran Anh Tu · **MSSV:** 2023604610 · **Ngày làm:** 2026-11-25
**Môi trường:** Windows 11 + Docker Desktop 29.0.1, Python 3.13 (host) / 3.11 (container)

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`
1. Hardcode secret: `OPENAI_API_KEY = "sk-..."`, `DATABASE_URL` có mật khẩu (dòng 17–18) — push lên GitHub là lộ.
2. Config cứng, không đọc từ env: `DEBUG = True`, `MAX_TOKENS = 500` (dòng 21–22).
3. Dùng `print` thay logging, và còn in ra secret: `print(f"[DEBUG] Using key: ...")` (dòng 34).
4. Không có `/health` — platform không biết khi nào cần restart.
5. Port cứng 8000 và `host="localhost"` (dòng 49–52) — Railway/Render cấp `PORT` qua env, và bind localhost thì bên ngoài container không truy cập được.
6. `reload=True` trong production; không có xử lý SIGTERM (không graceful shutdown); input `question` nhận qua query string thay vì body JSON.

### Exercise 1.3: Bảng so sánh
| Feature | Develop | Production | Vì sao quan trọng |
|---|---|---|---|
| Config | hardcode | đọc từ env (`config.py`) | cùng một image chạy dev/staging/prod, không lộ secret |
| Logging | `print` | JSON có cấu trúc | tìm kiếm, lọc, gắn request_id/trace_id |
| Health check | không có | `/health` (+ `/ready`) | platform restart khi chết, LB chỉ route khi sẵn sàng |
| Shutdown | tắt đột ngột | lifespan / SIGTERM | không cắt ngang request đang xử lý |
| Port/host | 8000 / localhost | `PORT` env / 0.0.0.0 | tương thích platform |

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`
1. **Base image:** `python:3.11` (bản đầy đủ, có cả compiler và tool build, nên nặng).
2. **Working directory:** `/app`.
3. **Vì sao COPY `requirements.txt` trước:** Docker cache theo từng layer. Copy riêng `requirements.txt` rồi `pip install` thì khi chỉ sửa code, layer cài thư viện vẫn lấy từ cache, build lại mất vài giây thay vì cài lại toàn bộ dependency.
4. **CMD vs ENTRYPOINT:** `ENTRYPOINT` là chương trình cố định của container; `CMD` là lệnh/tham số mặc định, bị ghi đè khi `docker run image <lệnh khác>`. Khi dùng cả hai, `CMD` thành tham số truyền cho `ENTRYPOINT`. Dùng dạng exec (`["python", "app.py"]`) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.3: Multi-stage và kích thước image (đo bằng `docker images`)
- Stage 1 (`builder`): cài `gcc`, `libpq-dev` và `pip install --user` các thư viện.
- Stage 2 (`runtime`): từ `python:3.11-slim` sạch, chỉ copy thư mục `.local` đã cài từ builder + code, chạy bằng user non-root, có `HEALTHCHECK`.
- Image nhỏ hơn vì compiler, header, cache apt/pip nằm lại ở stage builder và không vào image cuối.

| Image | Kích thước |
|---|---|
| Develop (`python:3.11` single-stage) | **1.67 GB** |
| Production (multi-stage, slim) | **240 MB** |
| Chênh lệch | giảm **~85.6 %** |
| Agent Part 6 (multi-stage, `python:3.11-slim`, non-root) | **56 MB** (số do `check_production_ready.py` đo) |

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)
```
client ──:80/:443──▶ nginx ──▶ agent (uvicorn :8000, 2 worker)
                                 │
                 mạng nội bộ "internal" (bridge)
                     ┌───────────┴───────────┐
                     ▼                       ▼
              redis :6379             qdrant :6333
          (session, cache, LRU)       (vector DB)
```
- 4 service: `nginx` (cổng vào duy nhất, publish 80/443), `agent`, `redis`, `qdrant`. Chỉ nginx có `ports`; agent/redis/qdrant chỉ nằm trong mạng `internal`.
- Giao tiếp qua DNS nội bộ của Docker theo tên service: agent gọi `redis://redis:6379/0` và `http://qdrant:6333` (qua biến môi trường), nginx proxy tới `agent:8000`.
- `depends_on: condition: service_healthy`: agent chỉ start khi Redis và Qdrant đã healthy; mỗi service có healthcheck riêng; dữ liệu Redis/Qdrant giữ trong named volume.
- Ghi chú: stack này cần file `.env.local` và cổng 80/443 trên máy; tôi trả lời bằng cách đọc file. Phần chạy thật nhiều container sau LB tôi làm ở Part 5 (Nginx + 3 agent + Redis) và Part 7.

## Part 3: Cloud Deployment
- **Exercise 3.1 — Railway (nền tảng chính):** https://agent-production-130c7cda.up.railway.app — agent Part 6 + Redis plugin, deploy bằng Railway CLI (`railway up`, builder Dockerfile). 4 lệnh tự kiểm CP6: `/health` 200, `/ready` 200, `/ask` không key 401, có key 200; request thứ 11 → 429. Chi tiết và output trong `DEPLOYMENT.md`, ảnh `screenshots/running.png`, `screenshots/test.png`.
- **So sánh `railway.toml` và `render.yaml` (Part 6):** Railway chỉ cấu hình build/deploy cho một service đã tạo trên dashboard: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`, restart policy; biến môi trường đặt trên dashboard/CLI. Render dùng Blueprint: một file khai báo cả service (`type: web`, `runtime: docker`, `healthCheckPath`) và **danh sách env var** — secret không ghi giá trị mà dùng `generateValue: true` (Render tự sinh `AGENT_API_KEY`) hoặc `sync: false` (`REDIS_URL` nhập tay trên dashboard). Vì vậy Render là "infrastructure as code" đầy đủ hơn, Railway gọn hơn nhưng phụ thuộc cấu hình trên dashboard. Cả hai đều cấp `PORT` qua env nên app phải đọc `PORT`.
- **Exercise 3.3 (Cloud Run):** `cloudbuild.yaml` là pipeline CI/CD 4 bước: (1) chạy test bằng `pytest`; (2) build Docker image, gắn tag `$COMMIT_SHA` và `latest`, dùng image cũ làm cache; (3) push image lên Container Registry; (4) `gcloud run deploy` image theo commit SHA lên Cloud Run. `service.yaml` mô tả service: autoscale 1–10 instance, 1 CPU / 512Mi, liveness probe `/health`, startup probe `/ready`, secret lấy từ Secret Manager.

## Part 4: API Security

### Exercise 4.1–4.3: Đọc code `04-api-gateway`
- API key được kiểm trong dependency `verify_api_key` (đọc header `X-API-Key` qua `APIKeyHeader`). Thiếu key → 401, sai key → 403 (bản develop). Rotate key: key đọc từ env `AGENT_API_KEY`, nên đổi biến trên platform rồi redeploy/restart; muốn không downtime thì cho phép tạm 2 key (cũ + mới) trong thời gian chuyển.
- JWT (`production/auth.py`): `POST /token` với username/password → server ký token (HS256) chứa `sub`, `role`, `exp`; client gửi `Authorization: Bearer <token>`; server xác minh chữ ký và hạn mà không cần tra DB.
- Rate limiter: **sliding window log** — mỗi user một `deque` timestamp, bỏ các timestamp ngoài cửa sổ 60 s, đủ `max_requests` thì 429 kèm `Retry-After`. User 10 req/phút, admin 100 req/phút (chọn limiter theo `role`, không bypass hoàn toàn).

### Output thật — agent Part 6 chạy bằng `docker compose` (agent + Redis), `RATE_LIMIT_PER_MINUTE=10`
```text
--- /health                → {"status":"ok","environment":"production"} [200]
--- /ready                 → {"status":"ready"} [200]
--- POST /ask, không key   → {"detail":"Invalid or missing API key"} [401]
--- POST /ask, sai key     → {"detail":"Invalid or missing API key"} [401]
--- POST /ask, body sai    → {"error":"validation_error","detail":[{"field":"body.question","message":"Field required"}]} [422]
--- req 1..10 (đúng key)   → HTTP/1.1 200 OK
    {"question":"What is Docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","cost_usd":1.125e-05}
--- req 11                 → HTTP/1.1 429 Too Many Requests
    retry-after: 60
    {"detail":"Rate limit exceeded. Try again later."}
--- req 12                 → HTTP/1.1 429 Too Many Requests
--- DAILY_BUDGET_USD=0.000001 → HTTP/1.1 402 Payment Required
    {"detail":"Daily LLM budget exceeded."}
```
Ngoài ra có 24 test tự động (`06-lab-complete/tests/test_app.py`, fakeredis) — `python -m pytest` → 24 passed.

### Exercise 4.4: Cost guard
Mỗi request: `check_budget()` đọc tổng chi phí ngày từ Redis (`cost:daily:YYYY-MM-DD`) trước khi gọi LLM, ≥ ngân sách thì 402; sau khi gọi, `record_cost()` cộng `input/1000×giá_in + output/1000×giá_out` bằng `INCRBYFLOAT` và đặt TTL 48h. State ở Redis nên nhiều instance dùng chung ngân sách (thấy trong Redis: key `cost:daily:2026-11-25 = 0.0001125` sau 10 request). Rate limit bảo vệ tốc độ, cost guard bảo vệ tiền — cần cả hai vì vài request đắt vẫn đốt ngân sách dù không vượt rate limit.

## Part 5: Scaling & Reliability

### Exercise 5.1 — Health / readiness (agent Part 6, đo thật)
- Tắt Redis (`docker compose stop redis`): `/health` → `200 {"status":"ok"}`, `/ready` → `503 {"detail":"Redis is not reachable"}`. Liveness không phụ thuộc Redis để platform không restart vô ích; readiness báo LB ngừng route.

### Exercise 5.2 — Graceful shutdown
- `docker compose stop agent`: exit code **0** sau **2.3 s** (< 10 s grace, không bị SIGKILL). Log: `Waiting for child process` → `Application shutdown complete` → `Stopping parent process [1]` — uvicorn là PID 1 (CMD dạng exec), nhận SIGTERM, chờ request đang chạy xong rồi mới thoát.
- `check_production_ready.py` trên Linux: "SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0".

### Exercise 5.3 — Stateless
- Rate limit và cost đều trong Redis (key `ratelimit:<api-key>`, `cost:daily:<ngày>`). Kiểm chứng: sau khi bị 429, `docker compose restart agent` rồi gọi lại vẫn **429** — state không mất khi process khởi động lại.

### Exercise 5.4–5.5 — Load balancing + `test_stateless.py` (`05-scaling-reliability/production`, `--scale agent=3`)
Cổng 8080 trên máy đã bị chiếm nên tôi publish Nginx ra 8082 bằng file override (không sửa file trong repo).
```text
Request 1: [instance-802af1]   Q: What is Docker?
Request 2: [instance-3f7f67]   Q: Why do we need containers?
Request 3: [instance-aa57dc]   Q: What is Kubernetes?
Request 4: [instance-802af1]   Q: How does load balancing work?
Request 5: [instance-3f7f67]   Q: What is Redis used for?
Total requests: 5
Instances used: {'instance-3f7f67', 'instance-aa57dc', 'instance-802af1'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```
Sau đó `docker stop day14-part5-agent-2` rồi gửi thêm 6 request cùng session: **6/6 trả 200**, history tăng lên **20 message** — Nginx chuyển traffic sang 2 instance còn lại, session vẫn còn vì nằm trong Redis.

## Output `check_production_ready.py`
Chạy bản đầy đủ (có Docker) trong container Linux `python:3.11-slim` có Docker CLI, mount Docker socket của Docker Desktop và `--network host` (Windows không gửi được SIGTERM nên bước graceful shutdown runtime phải chạy trên Linux). Không sửa script.

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```
Chi tiết đáng chú ý: image 56 MB, build 5 s; `docker stop` exit code 0 trong 1.3 s; 429 sau 5 request (RATE_LIMIT_PER_MINUTE=5) và vẫn 429 sau khi restart agent; `/ready` 503 khi mất Redis.

## AI log
- Công cụ: Claude Code (Claude Opus).
- Dùng để: rà code Part 6 và viết 24 test (fakeredis); chạy eval/load test Part 7 và sửa `KNOWLEDGE_BASE` (thêm mục JWT và HPA); chạy `check_production_ready.py` trong container Linux; chạy observability stack, chụp ảnh Grafana/Jaeger bằng Chrome headless, viết script đo thời gian alert cho các thí nghiệm A–E; chạy thử Part 4/5 và ghi output vào file này.
- Tôi tự kiểm tra lại: số trong `BENCHMARK_REPORT.md` đối chiếu với file JSON/CSV; các lệnh ở trên đều chạy thật trên máy, output dán nguyên văn (rút gọn phần lặp).
