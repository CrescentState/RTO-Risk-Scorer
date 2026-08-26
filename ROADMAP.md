# RTO Risk Scorer — 10-Day Build Roadmap
# Razorpay AI Buildathon — Track 02: AI Risk Manager
# Deadline: September 5, 2026

================================================================================
DAY 1 — FOUNDATION (Aug 26) ✅ COMPLETE
================================================================================

Tasks:
  [✅] Set up project structure (uv, pyproject.toml, .venv)
  [✅] Copy Chrimatos core modules (state, config, cache, clients, orchestrator)
  [✅] Fix critical bugs (model name, CORS, client consistency)
  [✅] Build synthetic data generator (500 customers, 717 orders, 717 signals)
  [✅] Verify imports: uv run python -c "from core.state import init_state"

Deliverables:
  → Working core/ module
  → synthetic_data/ with generator.py + 3 CSV files
  → Clean pyproject.toml with uv working

End-of-day check:
  $ uv run python -c "from core.orchestrator import create_pipeline; print('OK')"

================================================================================
DAY 2 — AGENT 1: PROFILE AGENT (Aug 27)
================================================================================

Tasks:
  [ ] Build agents/profile_agent.py
      - Read customers.csv + orders.csv
      - Build TransactionProfile for given customer_id
      - Cache lookup (24h TTL)
      - Confidence docking on missing fields
  [ ] Write tests/test_profile_agent.py (15 tests)
      - Cache hit/miss
      - Missing critical fields
      - Missing secondary fields
      - Invalid customer_id
      - Database timeout fallback
  [ ] Verify agent integrates with orchestrator

Deliverables:
  → Agent 1 working end-to-end
  → 15 passing tests
  → TransactionProfile populated correctly

Code sketch:
  def profile_agent(state: SystemState) -> dict:
      customer_id = state["customer_id"]
      cached = get_cached_response(f"{customer_id}_profile")
      if cached: return {"transaction_profile": cached, ...}

      # Read from CSV
      customer = lookup_customer(customer_id)
      orders = lookup_orders(customer_id)

      # Build profile
      profile = build_transaction_profile(customer, orders, state)

      # Cache and return
      set_cached_response(f"{customer_id}_profile", profile)
      return {"transaction_profile": profile, "company_name": ..., "confidence": ..., "errors": [...]}

================================================================================
DAY 3 — AGENT 2: SIGNAL AGENT (Aug 28)
================================================================================

Tasks:
  [ ] Build agents/signal_agent.py
      - Read signals.csv for given customer_id + order_id
      - Build SignalData with external signals
      - Mock LLM sentiment extraction (optional, fallback-heavy)
      - Schema validation + 1 retry
  [ ] Write tests/test_signal_agent.py (20 tests)
      - Signal parsing
      - Schema validation
      - Retry logic
      - Hostile signals detection
      - Missing signals fallback
  [ ] Verify agents 1+2 chain correctly

Deliverables:
  → Agent 2 working end-to-end
  → 20 passing tests
  → SignalData populated with realistic signals

================================================================================
DAY 4 — AGENT 3: RISK SCORER (Aug 29)
================================================================================

Tasks:
  [ ] Build agents/risk_agent.py
      - Pure Python deterministic rules (NO LLM for scoring)
      - 8 risk rules with exact thresholds
      - Score calculation: min(100, sum(weights))
      - Recommendation: Auto-Approve / Manual Review / Auto-Reject
      - LLM narrative generation only (with "DO NOT RECOMPUTE" prompt)
  [ ] Write tests/test_risk_agent.py (18 tests)
      - Boundary testing (0.50, 10000, 5000, 0.35, 0.70, -0.40)
      - None-safety (missing fields don't crash)
      - LLM fallback (narrative unavailable, score preserved)
      - All 8 rules triggered independently
  [ ] Verify agents 1+2+3 chain correctly

Deliverables:
  → Agent 3 working end-to-end
  → 18 passing tests
  → Deterministic risk scores with clear audit trail

Critical rules:
  return_rate > 0.50              → +30
  recent_returns_30d > 3          → +25
  order_value > 10000 + orders < 3 → +20
  cod + order_value > 5000        → +15
  pincode_rto_rate > 0.35         → +15
  complaint_score > 0.70          → +15
  social_sentiment < -0.40        → +10
  account_age_days < 7            → +15
  category_return_rate > 0.30     → +10

================================================================================
DAY 5 — AGENT 4: SYNTHESIS + EVALUATION (Aug 30)
================================================================================

Tasks:
  [ ] Build agents/synthesis_agent.py
      - Generate 5 narrative sections via LLM
      - Deterministic recommendation override
      - Fallback brief on LLM failure
  [ ] Build evaluation/metrics.py
      - Precision, Recall, F1, False Positive Rate
      - Auto-approval rate
      - Money saved estimate
  [ ] Build evaluation/benchmark.py
      - Run full pipeline on held-out test set
      - Generate benchmark report JSON
  [ ] Write tests/test_synthesis_agent.py (8 tests)
  [ ] Write tests/test_evaluation.py (10 tests)

Deliverables:
  → Agent 4 working end-to-end
  → Evaluation metrics computed on synthetic data
  → 18 passing tests (8 + 10)
  → Benchmark report showing precision/recall

================================================================================
DAY 6 — API LAYER + INTEGRATION (Aug 31)
================================================================================

Tasks:
  [ ] Build api/routes.py
      - POST /api/v1/analyze — full pipeline
      - GET /api/v1/metrics — precision/recall on held-out set
      - GET /health — container probe
      - Input validation (regex for order_id, customer_id, pincode)
  [ ] Build main.py
      - FastAPI app with CORS
      - Include router
  [ ] Write tests/test_pipeline_integration.py (12 tests)
      - E2E mock pipeline
      - Recommendation logic
      - State preservation
      - Error accumulation
  [ ] Verify full pipeline: curl -X POST /api/v1/analyze

Deliverables:
  → Working FastAPI server
  → All endpoints tested
  → 12 integration tests passing
  → Can analyze an order via API

================================================================================
DAY 7 — FRONTEND + DOCKER (Sep 1)
================================================================================

Tasks:
  [ ] Build frontend/index.html
      - Input form (order_id, customer_id, order_value, category, payment, pincode)
      - Submit button
      - Result card (risk score color-coded: green/yellow/red)
      - Recommendation badge
      - Expandable brief sections
      - Confidence indicator
  [ ] Build frontend/app.js
      - Fetch API call to /api/v1/analyze
      - Render results dynamically
      - Error handling
  [ ] Build frontend/styles.css
      - Clean, mobile-responsive design
      - Color coding for risk levels
  [ ] Build Dockerfile
      - Python 3.11 slim base
      - Copy code, install deps
      - Expose port 8000
  [ ] Build docker-compose.yml
      - App service with env file
      - Volume mount for cache
  [ ] Test: docker-compose up → visit localhost:8000

Deliverables:
  → Working web dashboard
  → Docker container builds and runs
  → Can demo via browser

================================================================================
DAY 8 — POLISH + README (Sep 2)
================================================================================

Tasks:
  [ ] Polish README.md
      - Problem statement
      - Architecture diagram
      - API documentation
      - Metrics summary
      - Installation instructions
      - Honest limitations section
  [ ] Add .env.example
      - All required and optional env vars
      - Comments explaining each
  [ ] Add .gitignore
      - cache/, .venv, __pycache__, .env
  [ ] Code cleanup
      - Remove dead code
      - Add docstrings where missing
      - Run ruff format + ruff check
      - Run mypy type check
  [ ] Verify all tests pass: uv run pytest tests/ -v
  [ ] Verify metrics: uv run python -m evaluation.benchmark

Deliverables:
  → Clean, documented codebase
  → All 83 tests passing
  → Benchmark report generated
  → Ready for video recording

================================================================================
DAY 9 — PITCH VIDEO (Sep 3)
================================================================================

Tasks:
  [ ] Record 5-minute pitch video
      - 0:00-0:30: Problem (RTO costs merchants 2-3% GMV)
      - 0:30-1:30: Demo (show 3 orders: auto-approve, manual review, auto-reject)
      - 1:30-2:30: Architecture (4 agents, deterministic-first, LangGraph)
      - 2:30-3:30: Metrics (precision 72%, recall 60%, F1 0.66)
      - 3:30-4:30: Failure handling (degraded mode with all APIs down)
      - 4:30-5:00: Honest limitations + next steps
  [ ] Edit video (trim, add captions if possible)
  [ ] Upload to YouTube/Vimeo as unlisted
  [ ] Test audio quality

Deliverables:
  → 5-minute pitch video uploaded
  → Link ready for submission

================================================================================
DAY 10 — BUFFER + SUBMISSION (Sep 4)
================================================================================

Tasks:
  [ ] Final bug fixes
  [ ] Improve metrics if possible (tune thresholds)
  [ ] Add edge case handling
  [ ] Verify Docker build one more time
  [ ] Verify all tests pass
  [ ] Push to GitHub
  [ ] Review submission requirements
  [ ] Submit before deadline

Deliverables:
  → Submission-ready repository
  → Public GitHub repo with clean history
  → Working demo URL (if deployed)
  → Video link

================================================================================
SUBMISSION DAY (Sep 5)
================================================================================

Submit to: https://razorpay.com/buildathon/

Required:
  [ ] Public GitHub repository
  [ ] 5-minute pitch video (YouTube/Vimeo link)
  [ ] Architecture documentation (README.md)
  [ ] Working code (Dockerfile or deployment URL)

================================================================================
DAILY CHECKLIST (Every Day)
================================================================================

Morning:
  [ ] git pull (if working across devices)
  [ ] uv sync --group dev
  [ ] uv run pytest tests/ -v (ensure nothing broke overnight)

Evening:
  [ ] git add -A && git commit -m "Day N: description"
  [ ] git push
  [ ] Update this roadmap (mark tasks complete)

================================================================================
RISK MITIGATION
================================================================================

If behind schedule:
  - Skip frontend styling (plain HTML is fine)
  - Reduce test count (aim for 50 instead of 83)
  - Skip Docker if running out of time (document "docker planned")
  - Use mock LLM responses instead of real Gemini calls

If ahead of schedule:
  - Add more realistic synthetic data (seasonality, promotions)
  - Deploy to Render/Railway for live demo URL
  - Add more evaluation metrics (ROC curve, confusion matrix)
  - Build a simple CLI tool for batch analysis

================================================================================
END OF ROADMAP
================================================================================
