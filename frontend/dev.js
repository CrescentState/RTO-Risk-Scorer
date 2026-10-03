// RTO Risk Scorer Developer Console (/dev) - dev-only logic.
// Shared flow (verify/analyze/render) lives in shared.js.
const testCaseSelect = document.getElementById('test-case-select');
const refreshCasesBtn = document.getElementById('refresh-cases');
const clearSelectionBtn = document.getElementById('clear-selection');

const metricsBody = document.getElementById('metrics-body');
const refreshMetricsBtn = document.getElementById('refresh-metrics');
const benchmarkBody = document.getElementById('benchmark-body');
const refreshBenchmarkBtn = document.getElementById('refresh-benchmark');
const apiViewer = document.getElementById('api-viewer');
const clearViewerBtn = document.getElementById('clear-viewer');

window.expectedRiskLevel = null;

async function loadTestCases() {
    testCaseSelect.disabled = true;
    testCaseSelect.innerHTML = '<option value="">Loading test cases...</option>';
    refreshCasesBtn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/test-cases`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const cases = await response.json();

        testCaseSelect.innerHTML = '<option value="">Select a test case (or fill manually)</option>';
        cases.forEach(c => {
            const option = document.createElement('option');
            option.value = JSON.stringify(c);
            option.textContent = `${c.customer_id} (${c.company_name}) - ${c.customer_type} - ${c.expected_risk_level}`;
            testCaseSelect.appendChild(option);
        });
        testCaseSelect.disabled = false;
        refreshCasesBtn.disabled = false;
    } catch (err) {
        testCaseSelect.innerHTML = '<option value="">Failed to load test cases</option>';
        console.error('Failed to load test cases:', err);
        refreshCasesBtn.disabled = false;
    }
}

function resetDevSelection() {
    analyzeForm.reset();
    ['order_value', 'category', 'payment_method', 'delivery_pincode'].forEach(id => {
        const el = document.getElementById(id);
        el.readOnly = false;
        el.disabled = false;
    });
    testCaseSelect.value = '';
    clearSelectionBtn.style.display = 'none';
    window.expectedRiskLevel = null;
}

function renderKeyValues(container, entries) {
    container.innerHTML = '';
    entries.forEach(([key, value]) => {
        const div = document.createElement('div');
        div.className = 'dev-metric';
        const k = document.createElement('span');
        k.className = 'dev-metric-key';
        k.textContent = key;
        const v = document.createElement('span');
        v.className = 'dev-metric-value';
        v.textContent = value;
        div.appendChild(k);
        div.appendChild(v);
        container.appendChild(div);
    });
}

function renderStatus(container, message, isError) {
    container.innerHTML = '';
    const div = document.createElement('div');
    div.className = isError ? 'dev-status-error' : 'dev-status';
    div.textContent = message;
    container.appendChild(div);
}

async function loadMetrics() {
    renderStatus(metricsBody, 'Loading metrics...');
    try {
        const response = await fetch(`${API_BASE}/metrics`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
        }
        renderKeyValues(metricsBody, [
            ['Precision', data.precision],
            ['Recall', data.recall],
            ['F1 Score', data.f1_score],
            ['False Positive Rate', data.false_positive_rate],
            ['Auto-Approval Rate', data.auto_approval_rate],
            ['Est. Money Saved (₹)', data.estimated_money_saved_inr],
        ]);
    } catch (err) {
        renderStatus(metricsBody, `Metrics unavailable: ${err.message}`, true);
    }
}

async function loadBenchmark() {
    renderStatus(benchmarkBody, 'Computing benchmark (first run may take a while)...');
    try {
        const response = await fetch(`${API_BASE}/benchmark`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
        }
        const info = data.benchmark_info || {};
        renderKeyValues(benchmarkBody, [
            ['Total Orders', data.total_orders],
            ['True Positives', data.true_positives],
            ['False Positives', data.false_positives],
            ['False Negatives', data.false_negatives],
            ['True Negatives', data.true_negatives],
            ['Precision', data.precision],
            ['Recall', data.recall],
            ['F1 Score', data.f1_score],
            ['Test Customers', info.total_customers ?? '--'],
            ['Test Orders', info.total_test_orders ?? '--'],
            ['RTO Rate in Test', info.rto_rate_in_test ?? '--'],
        ]);
    } catch (err) {
        renderStatus(benchmarkBody, `Benchmark unavailable: ${err.message}`, true);
    }
}

// Raw request/response viewer, fed by hooks in shared.js.
window.recordApiCall = function (name, request, response, status) {
    const entry = document.createElement('details');
    entry.className = 'dev-api-entry';
    entry.open = true;
    const summary = document.createElement('summary');
    summary.textContent = `${name} → HTTP ${status}`;
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify({ request, response }, null, 2);
    entry.appendChild(summary);
    entry.appendChild(pre);
    apiViewer.prepend(entry);
    while (apiViewer.children.length > 10) {
        apiViewer.removeChild(apiViewer.lastChild);
    }
};

// Initialize dev console
wireSharedFlow();
loadTestCases();
loadMetrics();

testCaseSelect.addEventListener('change', (e) => {
    if (!e.target.value) return;
    const c = JSON.parse(e.target.value);
    document.querySelector('#verification-form #order_id').value = c.order_id;
    document.getElementById('customer_id').value = c.customer_id;
    document.getElementById('order_value').value = c.order_value.toFixed(2);
    document.getElementById('category').value = c.category;
    document.getElementById('payment_method').value = c.payment_method;
    document.getElementById('delivery_pincode').value = c.pincode;
    window.expectedRiskLevel = c.expected_risk_level;
    clearSelectionBtn.style.display = 'inline-block';
});

clearSelectionBtn.addEventListener('click', () => {
    resetDevSelection();
});

refreshCasesBtn.addEventListener('click', loadTestCases);
refreshMetricsBtn.addEventListener('click', loadMetrics);
refreshBenchmarkBtn.addEventListener('click', loadBenchmark);

clearViewerBtn.addEventListener('click', () => {
    apiViewer.innerHTML = '<div class="dev-status">Viewer cleared. Verify or analyze an order to capture traffic.</div>';
});
