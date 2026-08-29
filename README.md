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



## ✨ Recent Updates (v0.1.1)

- **Frontend Dashboard**: Built-in web UI at `/` (served by FastAPI)
- **Model Upgrade**: Switched to `gemini-2.0-flash-lite` for faster LLM responses (~300-600ms)
- **Static File Serving**: Frontend assets served at `/static/`
- **All 81 tests passing** with ruff linting clean
- **LangGraph 1.2+ compatibility** fixed (removed deprecated `retry_policy`)



## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    RTO RISK SCORER PIPELINE                     │
└─────────────────────────────────────────────────────────────────┘

POST /api/v1/analyze
│
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
| **Signal**    | Customer ID, Pincode, Category | External Signals    | Pincode RTO rate, category return rate, complaints, sentiment |
| **Risk**      | Profile + Signals              | Risk Score (0-100)  | 9 deterministic weighted rules (see below)                    |
| **Synthesis** | All prior outputs              | Action Brief        | LLM narratives + deterministic override                       |




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

## Quick Start



### Prerequisites

- Python 3.11+
- Google Gemini API key (optional, for LLM narratives)



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
GEMINI_API_KEY=your_gemini_key_here
GEMINI_MODEL=gemini-3.6-flash
CACHE_TTL_SECONDS=86400
```

**Recommended Models** (by speed/cost):


| Model                   | Speed     | Cost   | Best For                 |
| ----------------------- | --------- | ------ | ------------------------ |
| `gemini-2.0-flash-lite` | ⚡ Fastest | Lowest | Production (recommended) |
| `gemini-1.5-flash-8b`   | Fast      | Low    | High volume              |
| `gemini-1.5-pro`        | Medium    | Higher | Complex narratives       |


> **Note**: `gemini-1.5-flash` is deprecated and returns 404. Use `gemini-2.0-flash-lite` instead.



### Generate Synthetic Data

```bash
# Generate 500 customers (400 train / 100 test) with orders and signals
uv run python -m synthetic_data.generator
```



### Run API Server

```bash
# Development
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Or with Docker
docker-compose up --build
```

**Web Dashboard**: Open [http://localhost:8000](http://localhost:8000) in browser after starting server.

**API Docs**: Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs)

### Run Benchmark

```bash
# Run full benchmark on held-out test set (100 test customers)
uv run python -m evaluation.benchmark
```



## API Reference



### Endpoints


| Method | Endpoint            | Description                 |
| ------ | ------------------- | --------------------------- |
| `GET`  | `/health`           | Health check                |
| `POST` | `/api/v1/analyze`   | Analyze COD order risk      |
| `GET`  | `/api/v1/metrics`   | Precision/Recall/F1 metrics |
| `GET`  | `/api/v1/benchmark` | Full benchmark report       |




### Analyze Request

```bash
POST /api/v1/analyze
Content-Type: application/json

{
  "order_id": "ORD_123456",
  "customer_id": "CUST_78901",
  "order_value": 8500.00,
  "category": "fashion",
  "payment_method": "cod",
  "delivery_pincode": "560001"
}
```



### Valid Test Customer IDs (from synthetic data)

Use these customer IDs from the test set (100 customers, IDs `CUST_00401`–`CUST_00500`):


| Customer ID  | Profile                            | Expected Risk              |
| ------------ | ---------------------------------- | -------------------------- |
| `CUST_00401` | Good (low returns, old account)    | **Low** (Auto-Approve)     |
| `CUST_00402` | Good                               | **Low** (Auto-Approve)     |
| `CUST_00403` | Serial Returner (high return rate) | **High** (Auto-Reject)     |
| `CUST_00404` | Occasional Returner                | **Medium** (Manual Review) |
| `CUST_00405` | Good                               | **Low** (Auto-Approve)     |
| `CUST_00410` | Serial Returner                    | **High** (Auto-Reject)     |


> **Full list**: Check `synthetic_data/customers.csv` where `split=test`



### Example curl Commands



#### 1. Low Risk Order (Auto-Approve)

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD_123456",
    "customer_id": "CUST_00401",
    "order_value": 3500,
    "category": "fashion",
    "payment_method": "upi",
    "delivery_pincode": "560001"
  }'
```

**Expected Response**:

```json
{
  "risk_score": 0.0,
  "recommendation": "Auto-Approve",
  "confidence_score": 1.0,
  "risk_factors": [],
  "action_brief": {
    "recommended_action": "Auto-Approve",
    "order_summary": "Order analysis pending due to system error.",
    "risk_assessment": "Risk computed deterministically. Narrative unavailable.",
    "market_context": "System degradation detected.",
    "mitigation_suggestions": ["Review order manually."],
    "key_concerns": ["LLM synthesis pipeline error encountered."]
  },
  "processing_time_ms": 8
}
```



#### 2. High Risk Order (Auto-Reject) - Serial Returner + COD High Value

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD_123457",
    "customer_id": "CUST_00403",
    "order_value": 8500,
    "category": "electronics",
    "payment_method": "cod",
    "delivery_pincode": "110001"
  }'
```

**Expected Response**:

```json
{
  "risk_score": 80.0,
  "recommendation": "Auto-Reject",
  "confidence_score": 1.0,
  "risk_factors": [
    "Serial returner (rate: 78%)",
    "Return velocity spike (4 in 30d)",
    "COD high-value order",
    "High-RTO category (34%)"
  ],
  "action_brief": {
    "recommended_action": "Auto-Reject",
    "order_summary": "Order analysis pending due to system error.",
    "risk_assessment": "Risk computed deterministically. Narrative unavailable.",
    "market_context": "System degradation detected.",
    "mitigation_suggestions": ["Review order manually."],
    "key_concerns": ["LLM synthesis pipeline error encountered."]
  },
  "processing_time_ms": 10
}
```



#### 3. Medium Risk Order (Manual Review) - New Customer + COD

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD_123458",
    "customer_id": "CUST_00404",
    "order_value": 6500,
    "category": "home",
    "payment_method": "cod",
    "delivery_pincode": "400001"
  }'
```

**Expected Response**:

```json
{
  "risk_score": 15.0,
  "recommendation": "Auto-Approve",
  "confidence_score": 0.9,
  "risk_factors": ["COD high-value order"],
  "action_brief": {
    "recommended_action": "Auto-Approve",
    ...
  },
  "processing_time_ms": 9
}
```

> **Note**: With valid `GEMINI_API_KEY`, `action_brief` contains rich LLM-generated narratives instead of fallback messages.



#### 4. Health Check

```bash
curl http://localhost:8000/api/v1/health
```



#### 5. Full Benchmark (takes ~30-60s)

```bash
curl http://localhost:8000/api/v1/benchmark
```



### Analyze Response

```json
{
  "order_id": "ORD_123456",
  "customer_id": "CUST_78901",
  "risk_score": 72.0,
  "recommendation": "Auto-Reject",
  "confidence_score": 0.85,
  "action_brief": {
    "order_summary": "Order #123456 for ₹8,500 (Fashion, COD)",
    "risk_assessment": "High risk: Serial returner + COD + High-RTO pincode",
    "market_context": "Festive season may increase RTO rates",
    "mitigation_suggestions": ["Request partial prepayment", "Verify phone number"],
    "key_concerns": ["Return rate: 80%", "Pincode RTO: 42%"],
    "recommended_action": "Auto-Reject"
  },
  "audit_trail": [],
  "processing_time_ms": 142
}
```



## Performance Characteristics


| Mode                                       | Latency        | Notes                         |
| ------------------------------------------ | -------------- | ----------------------------- |
| **No LLM (fallback)**                      | **~5-10ms**    | Deterministic pipeline only   |
| **LLM Enabled (gemini-2.0-flash-lite)**    | **~300-600ms** | First call; cached thereafter |
| **LLM Cached**                             | **~5-10ms**    | Subsequent similar orders     |
| **Cache Warm (2nd request same customer)** | **~2-5ms**     | Profile + Signal cached       |




### Caching Strategy

- **Profile Cache**: 24hr TTL, keyed by `customer_id` (`{customer_id}_profile.json`)
- **Signal Cache**: 24hr TTL, keyed by `customer_id + pincode` (`{customer_id}_{pincode}_signals.json`)
- **LLM Narrative Cache**: Not yet implemented (planned)



### Latency Breakdown (Cold Start, No LLM)


| Component                                | Time     |
| ---------------------------------------- | -------- |
| Profile Agent (CSV lookup + computation) | ~2ms     |
| Signal Agent (CSV lookup + computation)  | ~2ms     |
| Risk Agent (9 rule evaluations)          | ~1ms     |
| Synthesis Agent (fallback template)      | ~1ms     |
| **Total**                                | **~6ms** |




## Synthetic Data

The system includes a realistic data generator for development and benchmarking:

- **500 customers** across 4 behavioral types:
  - Good (60%): Low return rate (0-10%), 5-50 orders
  - Occasional Returner (25%): Moderate return rate (10-30%), 3-30 orders
  - Serial Returner (10%): High return rate (50-90%), 10-40 orders
  - Fraudster (5%): Very high return rate (50-100%), 1-15 orders, often new accounts
- **Orders**: Log-normal value distribution (₹500–25,000), category/payment/pincode distributions matching Indian e-commerce
- **Signals**: Pincode RTO rates, category return rates, complaint scores, social sentiment, recent events
- **Split**: 400 train / 100 held-out test customers with ground truth RTO labels



## Evaluation Metrics


| Metric                  | Formula                  | Target |
| ----------------------- | ------------------------ | ------ |
| **Precision**           | TP / (TP + FP)           | ≥70%   |
| **Recall**              | TP / (TP + FN)           | ≥60%   |
| **F1 Score**            | 2 × (P × R) / (P + R)    | ≥0.65  |
| **False Positive Rate** | FP / (FP + TN)           | ≤15%   |
| **Auto-Approval Rate**  | Score ≤25 / Total        | ≥40%   |
| **Money Saved**         | (TP × ₹100) - (FP × ₹50) | >₹0    |




## Project Structure

```
rto-risk-scorer/
├── agents/
│   ├── profile_agent.py      # Transaction profile from history
│   ├── signal_agent.py       # External signals (pincode, category, complaints)
│   ├── risk_agent.py         # 9-rule deterministic scorer
│   └── synthesis_agent.py    # Action brief with LLM narratives
├── api/
│   └── routes.py             # FastAPI endpoints
├── core/
│   ├── state.py              # TypedDict SystemState
│   ├── orchestrator.py       # LangGraph pipeline
│   ├── cache.py              # File-based cache (24hr TTL)
│   ├── config.py             # Pydantic Settings
│   └── clients.py            # Singleton HTTP/Gemini clients
├── synthetic_data/
│   ├── generator.py          # Data generator
│   ├── customers.csv
│   ├── orders.csv
│   └── signals.csv
├── evaluation/
│   ├── metrics.py            # Precision/Recall/F1/FPR
│   └── benchmark.py          # Full benchmark runner
├── tests/
│   ├── test_profile_agent.py
│   ├── test_signal_agent.py
│   ├── test_risk_agent.py
│   ├── test_synthesis_agent.py
│   └── test_pipeline_integration.py
├── main.py                   # FastAPI entry point
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
└── .env.example
```



## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific agent tests
uv run pytest tests/test_risk_agent.py -v
uv run pytest tests/test_signal_agent.py -v
uv run pytest tests/test_pipeline_integration.py -v
```



## Web Dashboard

The built-in frontend provides a real-time risk assessment UI:

**Access**: [http://localhost:8000](http://localhost:8000) (after starting server)

**Features**:

- Order input form with validation
- Live risk score with color-coded badge (Green/Yellow/Red)
- Recommendation badge (Auto-Approve / Manual Review / Auto-Reject)
- Confidence progress bar
- Expandable sections: Order Summary, Risk Assessment, Market Context, Key Concerns, Mitigations, Audit Trail
- Processing time display

**Architecture**: Static files served via FastAPI at `/static/`, API calls to `/api/v1/analyze`

---



## Deployment



### Docker

```bash
docker-compose up --build
```



## Design Decisions


| Decision                          | Rationale                                                                     |
| --------------------------------- | ----------------------------------------------------------------------------- |
| TypedDict over Pydantic for state | Lightweight, mutable, JSON-serializable; idiomatic for LangGraph              |
| `operator.add` on errors          | LangGraph reducer pattern — each agent appends, never overwrites              |
| Sequential execution              | Data dependencies: Signal needs Profile; Risk needs both; Synthesis needs all |
| File-based cache (24hr TTL)       | Eliminates repeated DB/API calls; atomic writes with `os.replace()`           |
| Deterministic risk scoring        | Reproducible, auditable, no LLM hallucination on money decisions              |
| Confidence scoring                | Quantified reliability — merchants know when to trust auto-decisions          |
| LLM for narratives only           | Prevents hallucination on quantitative decisions                              |




## License

MIT License