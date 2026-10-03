# RTO Risk Scorer

A multi-agent AI pipeline for Cash-on-Delivery (COD) order Return-to-Origin (RTO) risk assessment. Evaluates orders at checkout-time and assigns a deterministic 0–100 risk score with actionable recommendations.

## Problem Statement

In Indian e-commerce, **25–40% of COD orders** are returned to origin (RTO). Each RTO costs merchants **₹50–150** in logistics, packaging, and opportunity cost. Small and mid-sized merchants lack automated tools to identify high-risk orders before shipping, leading to preventable losses.

## Solution

RTO Risk Scorer evaluates every COD order at checkout-time using a **deterministic 4-agent pipeline**:


| Score Range | Recommendation | Action                                           |
| ----------- | -------------- | ------------------------------------------------ |
| **0–25**    | Auto-Approve   | Ship immediately                                 |
| **26–60**   | Manual Review  | Flag for verification call or partial prepayment |
| **61–100**  | Auto-Reject    | Cancel or request 100% prepayment                |


**Core Philosophy**: *"Deterministic decisions, LLM explanations, graceful degradation."*

- Risk scores are computed by **pure Python rules** — auditable, reproducible, no black box
- LLM generates **human-readable narratives only** — never overrides the score
- If any agent fails, system degrades gracefully with lower confidence and defaults to "Manual Review"



## Current State

- **Two routes**: `/` is the user flow (verify → read-only canonical details → result); `/dev` is the developer console (test cases, endpoint list, live metrics/benchmark panels, raw request/response viewer). Shared flow lives in `frontend/shared.js`.
- **Order integrity gate**: `/api/v1/analyze` rejects altered order details with HTTP 409 (`{message, code, mismatches}`) before any pipeline runs. Stable codes: `CUSTOMER_NOT_FOUND`, `ORDER_NOT_FOUND`, `CUSTOMER_MISMATCH`, `ORDER_FIELD_MISMATCH`.
- **Canonical scoring**: the risk agent scores profile fields; signals are scoped to one exact order (`customer_id` + `order_id`) with pincode validation and never reused across orders.
- **Cache correctness**: versioned keys (`v1:{customer}_{order}_profile`, `v1:{customer}_{order}_{pincode}_{category}_signals`) store each agent's confidence deduction and warnings and reapply them on hits, so cold and warm requests return identical score, confidence, action, and warnings. Errors are a plain list — each unique warning appears once.
- **Benchmark service**: `evaluation/service.py` computes the real benchmark once with an async single-flight lock, caches it for one hour, and invalidates on dataset file changes. `/metrics` and `/benchmark` share it; LLM narratives are forced off during benchmarks. No mock fallbacks — unavailable data returns a clear service error.
- **Test isolation**: all test datasets generate under `tmp_path`; tracked CSVs are never rewritten by the suite. CI runs Python 3.11 and 3.12 (`requires-python = ">=3.11,<3.13"`).
- **81 tests passing**, ruff clean, mypy clean, JS syntax clean.

> **Security note**: `.env.example` ships a placeholder key. A Gemini key was previously committed to this repo's history — rotate any exposed credentials in the provider dashboard before deploying. Deployment is blocked until rotation is confirmed.



## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    RTO RISK SCORER PIPELINE                     │
└─────────────────────────────────────────────────────────────────┘

POST /api/v1/analyze
│  (409 gate: order/customer/fields must match the stored record)
▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Profile Agent   │───▶│  Signal Agent    │───▶│   Risk Agent     │───▶│ Synthesis Agent  │
│                  │    │                  │    │                  │    │                  │
│ • Transaction    │    │ • Pincode RTO    │    │ • 9 Deterministic│    │ • 5-Section      │
│   History        │    │   Rate           │    │   Rules          │    │   Brief          │
│ • Return Rate    │    │ • Category       │    │ • Score 0-100    │    │ • Deterministic  │
│ • Account Age    │    │   Return Rate    │    │ • Recommendation │    │   Override       │
└──────────────────┘    │ • Complaint Score│    └──────────────────┘    └──────────────────┘
                        │ • Social Sentiment│
                        └──────────────────┘
```

### Agent Details


| Agent         | Input                          | Output              | Key Logic                                                     |
| ------------- | ------------------------------ | ------------------- | ------------------------------------------------------------- |
| **Profile**   | Customer ID, Order details     | Transaction Profile | Historical orders, return rate, account age, recent returns   |
| **Signal**    | Customer ID, Order ID, Pincode, Category | External Signals | Exact-order signals only; category defaults on miss; pincode validated |
| **Risk**      | Profile + Signals              | Risk Score (0-100)  | 9 deterministic weighted rules over canonical profile fields (see below) |
| **Synthesis** | All prior outputs              | Action Brief        | Brief sections + deterministic override (confidence < 0.5 → Manual Review) |



### Deterministic Risk Rules (9 Rules)


| Rule                    | Condition                                          | Weight |
| ----------------------- | -------------------------------------------------- | ------ |
| Serial Returner         | `return_rate > 0.50`                               | +30    |
| Return Velocity Spike   | `recent_returns_30d > 3`                           | +25    |
| High-Value New Customer | `order_value > 10000` AND `total_orders < 3`       | +20    |
| COD High-Value Order    | `payment_method == "cod"` AND `order_value > 5000` | +15    |
| High-RTO Pincode        | `pincode_rto_rate > 0.35`                          | +15    |
| High Complaint History  | `complaint_score > 0.70`                           | +15    |
| Negative Social Signals | `social_sentiment < -0.40`                         | +10    |
| Brand New Account       | `account_age_days < 7`                             | +15    |
| High-RTO Category       | `category_return_rate > 0.30`                      | +10    |


**Score Calculation**: `risk_score = min(100.0, sum(triggered_weights))`

### Order Integrity Gate (`/api/v1/analyze`)

Before the pipeline runs, the request is checked against the canonical stored order (shared lookup in `core/orders.py`, used identically by verify, analyze, and test-cases):

| Check | Failure code (HTTP 409) |
|-------|-------------------------|
| Customer not in database | `CUSTOMER_NOT_FOUND` |
| Order not in database | `ORDER_NOT_FOUND` |
| Order belongs to another customer | `CUSTOMER_MISMATCH` |
| `order_value` (₹0.01 tolerance), `category`, `payment_method`, `delivery_pincode` differ | `ORDER_FIELD_MISMATCH` + `mismatches: [{field, expected, actual}]` |

Non-finite or non-positive `order_value` values (`NaN`, `inf`) are rejected with HTTP 422, as are pattern violations, with readable `field: message` detail strings.

## Quick Start



### Prerequisites

- Python 3.11 or 3.12
- Google Gemini API key (optional, only for LLM narratives)



### Installation

```bash
# Clone and enter directory
cd rto-risk-scorer

# Install dependencies (using uv recommended)
uv sync

# Or with pip
pip install -e ".[dev]"
```



### Configuration

Copy `.env.example` to `.env` and configure:

```env
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL=gemini-3.1-flash-lite
CACHE_TTL_SECONDS=86400
ENABLE_LLM_NARRATIVES=false
```

**LLM Narratives Toggle:**

| Setting | Value | Behavior |
|---------|-------|----------|
| `ENABLE_LLM_NARRATIVES=false` (default) | Fast mode | Deterministic pipeline only, fallback narratives, no LLM calls |
| `ENABLE_LLM_NARRATIVES=true` | LLM mode | LLM-generated narratives with 15s timeout (never changes the score) |

> **Note**: Requires a valid, rotated `GEMINI_API_KEY` when enabled. Default is `false` for fast production mode (also set explicitly in `render.yaml`).



### Generate Synthetic Data

```bash
# Generate 505 customers (400 train / 105 test) with orders and signals,
# including 5 predictable test cases (ORD_000001-ORD_000005)
uv run python -m synthetic_data.generator
```

Arbitrary sizes use an 80/20 train/test split; the documented 500-customer dataset uses 400/100 plus the 5 predictable cases.



### Run API Server

```bash
# Development
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Or with Docker
docker-compose up --build
```

**User page**: [http://localhost:8000](http://localhost:8000) — verify → result.
**Developer console**: [http://localhost:8000/dev](http://localhost:8000/dev) — test cases, metrics, benchmark, raw traffic viewer.
**API Docs**: Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs)

### Run Benchmark

```bash
# Full async benchmark on the held-out test set (cached 1h, shared with /metrics)
uv run python -m evaluation.benchmark
```



## API Reference



### Endpoints

| Method | Endpoint               | Description                              |
| ------ | ---------------------- | ---------------------------------------- |
| `GET`  | `/`                    | User page (verify → result)              |
| `GET`  | `/dev`                 | Developer console (test cases + inspect) |
| `GET`  | `/health`              | Health check                             |
| `GET`  | `/docs`                | Swagger UI                               |
| `POST` | `/api/v1/verify-order` | Verify order/customer, return canonical order data |
| `POST` | `/api/v1/analyze`      | Analyze COD order risk (409-gated)       |
| `GET`  | `/api/v1/test-cases`   | Predictable test cases with expected risk levels |
| `GET`  | `/api/v1/metrics`      | Precision/Recall/F1 metrics (cached benchmark subset) |
| `GET`  | `/api/v1/benchmark`    | Full benchmark report (cached)           |



### Analyze Request

```bash
POST /api/v1/analyze
Content-Type: application/json

{
  "order_id": "ORD_000001",
  "customer_id": "CUST_GOOD_01",
  "order_value": 2000.00,
  "category": "electronics",
  "payment_method": "upi",
  "delivery_pincode": "110001"
}
```

Values must match the stored order record (see integrity gate); `category`/`payment_method` are case-insensitive, surrounding whitespace is trimmed.



### Predictable Test Cases

Reserved orders `ORD_000001`–`ORD_000005` (expected levels computed with the same shared rule engine as the pipeline):


| Order | Customer (Company) | Profile | Expected |
| ----- | ------------------ | ------- | -------- |
| `ORD_000001` | `CUST_GOOD_01` (Good Customer Inc) | good, 25 orders, 4% returns | **Auto-Approve** |
| `ORD_000002` | `CUST_SERIAL_01` (Serial Returner Ltd) | serial_returner, 70% returns | **Auto-Reject** |
| `ORD_000003` | `CUST_FRAUD_01` (Fraudster Corp) | fraudster, 100% returns, 3-day account | **Auto-Reject** |
| `ORD_000004` | `CUST_OCCASIONAL_01` (Occasional Returner) | occasional_returner, 20% returns | **Auto-Approve** |
| `ORD_000005` | `CUST_NEW_COD_01` (New COD Customer) | good, 1 order, 5-day account, COD ₹8000 | **Manual Review** |


> Pick these from the dropdown on the [/dev](#) console, or query `GET /api/v1/test-cases`.



### Example curl Commands



#### 1. Low Risk Order (Auto-Approve)

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD_000001",
    "customer_id": "CUST_GOOD_01",
    "order_value": 2000,
    "category": "electronics",
    "payment_method": "upi",
    "delivery_pincode": "110001"
  }'
```

**Response** (verified live output):

```json
{
  "order_id": "ORD_000001",
  "customer_id": "CUST_GOOD_01",
  "company_name": "Good Customer Inc",
  "risk_score": 0.0,
  "recommendation": "Auto-Approve",
  "confidence_score": 1.0,
  "risk_data": {
    "risk_score": 0.0,
    "risk_factors": [],
    "risk_narrative": "Risk assessment based on transaction history and delivery signals.",
    "recommendation": "Auto-Approve"
  },
  "action_brief": {
    "order_summary": "Order analysis pending due to system error.",
    "risk_assessment": "Risk computed deterministically. Narrative unavailable.",
    "market_context": "System degradation detected.",
    "mitigation_suggestions": ["Review order manually."],
    "key_concerns": ["LLM synthesis pipeline error encountered."],
    "recommended_action": "Auto-Approve"
  },
  "audit_trail": [],
  "processing_time_ms": 18
}
```

> The fallback `action_brief` prose above appears when `ENABLE_LLM_NARRATIVES=false`. With a valid key and LLM mode on, the same fields carry model-generated narratives; score, factors, and recommendation are identical either way.



#### 2. High Risk Order (Auto-Reject) — Serial Returner + COD High Value

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD_000003",
    "customer_id": "CUST_FRAUD_01",
    "order_value": 15000,
    "category": "electronics",
    "payment_method": "cod",
    "delivery_pincode": "700002"
  }'
```

**Response** (verified live output, brief prose trimmed):

```json
{
  "risk_score": 100.0,
  "recommendation": "Auto-Reject",
  "confidence_score": 0.95,
  "risk_data": {
    "risk_score": 100.0,
    "risk_factors": [
      "Serial returner (rate: 100%)",
      "COD high-value order",
      "High-RTO delivery pincode (50%)",
      "High complaint history",
      "Negative social signals",
      "Brand new account"
    ],
    "risk_narrative": "Risk assessment based on transaction history and delivery signals.",
    "recommendation": "Auto-Reject"
  }
}
```



#### 3. Altered Order Details (HTTP 409, no pipeline run)

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD_000001",
    "customer_id": "CUST_GOOD_01",
    "order_value": 7000,
    "category": "electronics",
    "payment_method": "upi",
    "delivery_pincode": "110001"
  }'
```

```json
{
  "detail": {
    "message": "Order details do not match the stored record",
    "code": "ORDER_FIELD_MISMATCH",
    "mismatches": [{ "field": "order_value", "expected": 2000.0, "actual": 7000.0 }]
  }
}
```



### Verify Order Endpoint

```bash
# Verify order and customer match before analysis
curl -X POST http://localhost:8000/api/v1/verify-order \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD_000001",
    "customer_id": "CUST_GOOD_01"
  }'
```

**Success Response** (200, verified live output):

```json
{
  "order_id": "ORD_000001",
  "customer_id": "CUST_GOOD_01",
  "order_value": 2000.0,
  "category": "electronics",
  "payment_method": "upi",
  "pincode": "110001",
  "order_data": {
    "order_id": "ORD_000001",
    "customer_id": "CUST_GOOD_01",
    "order_value": 2000.0,
    "category": "electronics",
    "payment_method": "upi",
    "pincode": "110001"
  }
}
```

**Mismatch Response** (409):

```json
{
  "detail": {
    "message": "Order ID ORD_000001 does not belong to customer CUST_SERIAL_01",
    "code": "CUSTOMER_MISMATCH",
    "mismatches": []
  }
}
```

> The two-step web flow calls this endpoint first, then submits the returned canonical values to `/analyze`.



#### 4. Health Check

```bash
curl http://localhost:8000/health
```



#### 5. Metrics and Benchmark (shared cached report)

```bash
curl http://localhost:8000/api/v1/metrics
curl http://localhost:8000/api/v1/benchmark
```

`/metrics` returns the metric subset of the same cached report `/benchmark` returns in full (1h TTL, invalidated when dataset files change). Unavailable data returns HTTP 503 with a clear message — there are no mock fallbacks.



### Analyze Response Schema

```json
{
  "order_id": "ORD_000001",
  "customer_id": "CUST_GOOD_01",
  "company_name": "Good Customer Inc",
  "risk_score": 0.0,
  "recommendation": "Auto-Approve",
  "confidence_score": 1.0,
  "risk_data": {
    "risk_score": 0.0,
    "risk_factors": [],
    "risk_narrative": "...",
    "recommendation": "Auto-Approve"
  },
  "action_brief": {
    "order_summary": "...",
    "risk_assessment": "...",
    "market_context": "...",
    "mitigation_suggestions": ["..."],
    "key_concerns": ["..."],
    "recommended_action": "Auto-Approve"
  },
  "audit_trail": [],
  "processing_time_ms": 18
}
```

`risk_data` exposes public fields only (the internal rule bitmask is omitted). Confidence below 0.5 forces `recommended_action` to Manual Review regardless of score.



## Performance Characteristics


| Mode                                       | Latency        | Notes                         |
| ------------------------------------------ | -------------- | ----------------------------- |
| **Fast Mode (ENABLE_LLM_NARRATIVES=false)** | **~ms**        | Deterministic pipeline only   |
| **LLM Enabled (gemini-3.1-flash-lite)**    | **~2-30s**     | 15s timeout per LLM call; rich narratives |
| **Cache Warm (repeat order)** | **identical output** | Score, confidence, action, and warnings match cold run |



### Caching Strategy

- **Profile Cache**: 24hr TTL, versioned key `v1:{customer_id}_{order_id}_profile` — stores the data-phase confidence deduction and data warnings, reapplied on hits.
- **Signal Cache**: 24hr TTL, versioned key `v1:{customer_id}_{order_id}_{pincode}_{category}_signals` — exact-order rows only, never another order's signals; deduction/warnings reapplied on hits.
- **Benchmark Cache**: 1h TTL, process-local, invalidated on customers/orders/signals file changes; single-flight async lock.
- **LLM Narrative Cache**: Not implemented.



## Synthetic Data

The system includes a realistic data generator for development and benchmarking:

- **505 customers** across 4 behavioral types (400 train / 105 test, incl. 5 predictable cases):
  - Good: low return rate, established accounts
  - Occasional Returner: moderate return rate (10-30%)
  - Serial Returner: high return rate (50-90%)
  - Fraudster: very high return rate, often new accounts
- **Orders**: log-normal value distribution (₹500–25,000), category/payment/pincode distributions matching Indian e-commerce; reserved IDs `ORD_000001`–`ORD_000005` for predictable cases
- **Signals**: exact-order rows (`customer_id` + `order_id`) with pincode RTO rates, category return rates, complaint scores, social sentiment, recent events; category-rate defaults apply on miss
- **Split**: train/test customers with ground truth RTO labels; held-out test orders drive `/benchmark`



## Evaluation Metrics


| Metric                  | Formula                  | Target |
| ----------------------- | ------------------------ | ------ |
| **Precision**           | TP / (TP + FP)           | ≥70%   |
| **Recall**              | TP / (TP + FN)           | ≥60%   |
| **F1 Score**            | 2 × (P × R) / (P + R)    | ≥0.65  |
| **False Positive Rate** | FP / (FP + TN)           | ≤15%   |
| **Auto-Approval Rate**  | Score ≤25 / Total        | ≥40%   |
| **Money Saved**         | (TP × ₹100) - (FP × ₹50) | >₹0    |



Flagged = score > 25 (Manual Review / Auto-Reject). Run `uv run python -m evaluation.benchmark` or `GET /api/v1/benchmark` for the measured report.



## Project Structure

```
rto-risk-scorer/
├── agents/
│   ├── profile_agent.py      # Transaction profile from history + order validation
│   ├── signal_agent.py       # Exact-order external signals, category defaults
│   ├── risk_agent.py         # 9-rule deterministic scorer + shared rule registry
│   └── synthesis_agent.py    # Action brief with LLM narratives + deterministic override
├── api/
│   └── routes.py             # FastAPI endpoints (verify/analyze/test-cases/metrics/benchmark)
├── core/
│   ├── state.py              # TypedDict SystemState (plain error list, unique-append)
│   ├── orchestrator.py       # LangGraph pipeline (async primary, sync wrapper)
│   ├── orders.py             # Shared order/customer/signal repository + 409 checks
│   ├── cache.py              # File-based cache (24hr TTL, atomic writes, file locking)
│   ├── config.py             # Pydantic Settings
│   └── clients.py            # Singleton HTTP/Gemini clients
├── synthetic_data/
│   ├── generator.py          # Data generator (80/20 split; 400/100 for 500)
│   ├── customers.csv
│   ├── orders.csv
│   └── signals.csv
├── evaluation/
│   ├── metrics.py            # Precision/Recall/F1/FPR (no mock fallbacks)
│   ├── benchmark.py          # Async full benchmark runner
│   └── service.py            # Shared cached benchmark service (1h TTL, single-flight)
├── frontend/
│   ├── index.html            # User page (/)
│   ├── dev.html              # Developer console (/dev)
│   ├── shared.js             # Shared verify/analyze/render flow
│   ├── app.js                # User page wiring
│   ├── dev.js                # Dev console wiring (test cases, metrics, viewer)
│   └── styles.css
├── tests/
│   ├── conftest.py           # LLM off + tmp-path dataset isolation fixtures
│   ├── test_profile_agent.py
│   ├── test_signal_agent.py
│   ├── test_risk_agent.py
│   ├── test_synthesis_agent.py
│   ├── test_pipeline_integration.py
│   └── test_evaluation.py
├── main.py                   # FastAPI entry point (/ and /dev routes)
├── start.sh                  # Container startup (data check + uvicorn on $PORT)
├── pyproject.toml            # Python >=3.11,<3.13
├── mypy.ini                  # Mypy config (valid INI)
├── Dockerfile                # Builds + generates full dataset in-image
├── docker-compose.yml
├── render.yaml               # Render blueprint (LLM narratives off)
├── .github/workflows/ci.yml # CI: Python 3.11/3.12 × ruff/mypy/JS/pytest + route smoke
└── .env.example
```



## Testing

```bash
# Run all tests (81 tests; datasets generate under tmp_path, tracked CSVs untouched)
uv run pytest tests/ -q

# Run specific agent tests
uv run pytest tests/test_risk_agent.py -v
uv run pytest tests/test_signal_agent.py -v
uv run pytest tests/test_pipeline_integration.py -v

# Lint, types, JS
uv run ruff check .
uv run mypy --config-file mypy.ini agents/ core/ api/ synthetic_data/ evaluation/ main.py
node --check frontend/shared.js frontend/app.js frontend/dev.js
```



## Web Frontend

Two routes served by FastAPI (`/` and `/dev`), sharing `frontend/shared.js`:

**User page** (`/`): Step 1 (Order ID + Customer ID → Verify & Continue) → Step 2 (verified canonical values, read-only) → Analyze Risk → score badge, recommendation, confidence bar, risk factors, narrative, brief sections, audit trail, processing time. 409/422 failures render as readable messages.

**Developer console** (`/dev`): same flow plus test-case picker with expected-vs-actual badge, endpoint list, live metrics and benchmark panels, and a raw request/response viewer.

**Architecture**: Static files served at `/static/`; API calls to `/api/v1/verify-order` and `/api/v1/analyze`.

---



## Deployment



### Docker

```bash
docker-compose up --build
```

The image (`python:3.11-slim`) installs dependencies, generates the full 500-customer dataset at build time (no data volume required), and starts via `start.sh` (uvicorn on `${PORT:-8000}`). Healthcheck uses the Python standard library. `docker-compose.yml` mounts only `./cache`.

### Render

`render.yaml` defines the Docker web service with health check path `/health` and `ENABLE_LLM_NARRATIVES=false`. Set `GEMINI_API_KEY` in the Render dashboard (never in the repo) — only after rotating the previously exposed credentials.



## Design Decisions


| Decision                          | Rationale                                                                     |
| --------------------------------- | ----------------------------------------------------------------------------- |
| TypedDict over Pydantic for state | Lightweight, mutable, JSON-serializable; idiomatic for LangGraph              |
| Plain error list, unique-append   | Sequential agents carry the full list; no reducer duplication on retry/cache-hit |
| 409 gate before scoring           | Altered order details are rejected, never scored; canonical values only       |
| Order-scoped signals              | Exact `customer_id + order_id` rows with pincode check; no cross-order reuse  |
| Versioned cache + deduction reapply | Cold and warm requests return identical confidence and warnings             |
| Sequential execution              | Data dependencies: Signal needs Profile; Risk needs both; Synthesis needs all |
| File-based cache (24hr TTL)       | Eliminates repeated DB/API calls; atomic writes with `os.replace()`           |
| Deterministic risk scoring        | Reproducible, auditable, no LLM hallucination on money decisions              |
| Confidence scoring                | Quantified reliability — merchants know when to trust auto-decisions          |
| LLM for narratives only           | Prevents hallucination on quantitative decisions                              |
| Benchmark single-flight cache     | One real computation shared by `/metrics` and `/benchmark`; file-change invalidation |



## License

MIT License
