# Deployment Information

## Public URL
https://agent-production-130c7cda.up.railway.app

## Platform
**Railway** — project `day14-agent-tranantu`, environment `production`, region `iad`.
Gồm 2 service: `agent` (build từ `06-lab-complete/Dockerfile`, cấu hình `06-lab-complete/railway.toml`) và `Redis` (database plugin của Railway, có volume).

## Cách deploy (đã làm, 2026-11-25)
```bash
cd 06-lab-complete
railway login
railway init --name day14-agent-tranantu
railway add --database redis
railway add --service agent \
  --variables "AGENT_API_KEY=<sinh ngẫu nhiên, không ghi vào repo>" \
  --variables 'REDIS_URL=${{Redis.REDIS_URL}}' \
  --variables "ENVIRONMENT=production" --variables "RATE_LIMIT_PER_MINUTE=10" \
  --variables "DAILY_BUDGET_USD=1.0" --variables "LOG_LEVEL=INFO"
railway up --service agent --ci        # build Dockerfile multi-stage trên Railway
railway domain --service agent         # tạo domain public
```

## Test Commands
```bash
BASE=https://agent-production-130c7cda.up.railway.app

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"   # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"    # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'                              # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'  # 200
```

### Kết quả thật (2026-11-25)
```text
$ curl $BASE/health
{"status":"ok","environment":"production"}  [200]
$ curl $BASE/ready
{"status":"ready"}  [200]
$ POST /ask không có key
{"detail":"Invalid or missing API key"}  [401]
$ POST /ask có key
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","cost_usd":1.035e-05}  [200]
$ 12 request liên tiếp (rate limit 10/phút)
200 200 200 200 000 200 200 200 200 200 429 429
```
Request thứ 5 (`000`) là lỗi kết nối tạm thời phía client, không tới server (log Railway không có request lỗi). Rate limit chặn từ request thứ 11 — state nằm trong Redis của Railway.

`python check_production_ready.py --public-url https://agent-production-130c7cda.up.railway.app` → `✅ Public URL: GET .../health → 200`.

## Environment Variables Set (trên Railway, không ghi trong code)
| Biến | Giá trị |
|---|---|
| `PORT` | do Railway cấp, app đọc qua `config.py` |
| `AGENT_API_KEY` | chuỗi ngẫu nhiên 32 ký tự, chỉ lưu trên Railway (gửi riêng cho Lab Coach nếu cần) |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` — tham chiếu tới service Redis, Railway tự điền |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `LOG_LEVEL` | `INFO` |

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running — `railway status` + log](screenshots/running.png)
- [Test results](screenshots/test.png)
