// RTO Risk Scorer - shared frontend flow (used by user page and dev page)
const API_BASE = '/api/v1';

const verificationForm = document.getElementById('verification-form');
const verifyBtn = document.getElementById('verify-btn');
const verificationError = document.getElementById('verification-error');

const step1Verification = document.getElementById('step1-verification');
const step2Details = document.getElementById('step2-details');
const verifiedInfo = document.getElementById('verified-info');
const analyzeForm = document.getElementById('analyze-form');
const submitBtn = document.getElementById('submit-btn');
const backBtn = document.getElementById('back-btn');

const resultSection = document.getElementById('result-section');
const errorSection = document.getElementById('error-section');
const errorMessage = document.getElementById('error-message');

const scoreValue = document.getElementById('score-value');
const scoreCircle = document.getElementById('score-circle');
const recommendationBadge = document.getElementById('recommendation-badge');
const confidenceBadge = document.getElementById('confidence-badge');
const confidenceBar = document.getElementById('confidence-bar');
const briefSections = document.getElementById('brief-sections');
const auditList = document.getElementById('audit-list');
const processingTime = document.getElementById('processing-time');
const resultOrderId = document.getElementById('result-order-id');
// Dev-only element: null on the user page.
const comparisonBadge = document.getElementById('comparison-badge');
const companyInfo = document.getElementById('company-info');
const detailSections = document.getElementById('detail-sections');
const riskFactorsList = document.getElementById('risk-factors-list');
const riskNarrative = document.getElementById('risk-narrative');

let verifiedOrderData = null;

function showStep1() {
    step1Verification.style.display = 'block';
    step2Details.style.display = 'none';
    resultSection.style.display = 'none';
    errorSection.style.display = 'none';
    verificationError.style.display = 'none';
    verifiedOrderData = null;
    ['order_value', 'category', 'payment_method', 'delivery_pincode'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.readOnly = false; el.disabled = false; }
    });
}

function formatDetail(detail, fallback) {
    if (!detail) return fallback;
    if (typeof detail === 'string') return detail;
    if (typeof detail === 'object') {
        const parts = [];
        if (detail.message) parts.push(detail.message);
        if (detail.code) parts.push(`(${detail.code})`);
        if (Array.isArray(detail.mismatches) && detail.mismatches.length > 0) {
            const fields = detail.mismatches.map(m => {
                if (m && typeof m === 'object' && 'field' in m) {
                    return `${m.field}: expected ${m.expected}, got ${m.actual}`;
                }
                return String(m);
            });
            parts.push(fields.join('; '));
        }
        if (parts.length > 0) return parts.join(' ');
    }
    return fallback;
}

function showStep2(orderData) {
    // Keep only the canonical values returned by /verify-order.
    verifiedOrderData = {
        order_id: orderData.order_id,
        customer_id: orderData.customer_id,
        order_value: Number(orderData.order_value),
        category: orderData.category,
        payment_method: orderData.payment_method,
        pincode: orderData.pincode,
    };
    step1Verification.style.display = 'none';
    step2Details.style.display = 'block';

    // Pre-fill hidden fields
    document.querySelector('#verification-form #order_id').value = verifiedOrderData.order_id;
    document.getElementById('customer_id').value = verifiedOrderData.customer_id;

    // Show verified info as read-only
    verifiedInfo.innerHTML = `
        <div class="verified-field"><strong>Order ID:</strong> ${verifiedOrderData.order_id}</div>
        <div class="verified-field"><strong>Customer ID:</strong> ${verifiedOrderData.customer_id}</div>
        <div class="verified-field"><strong>Order Value:</strong> ₹${verifiedOrderData.order_value.toFixed(2)} (verified)</div>
        <div class="verified-field"><strong>Category:</strong> ${verifiedOrderData.category} (verified)</div>
        <div class="verified-field"><strong>Payment:</strong> ${verifiedOrderData.payment_method.toUpperCase()} (verified)</div>
        <div class="verified-field"><strong>Pincode:</strong> ${verifiedOrderData.pincode} (verified)</div>
    `;

    // Fill form with canonical values and lock it read-only
    document.getElementById('order_value').value = verifiedOrderData.order_value.toFixed(2);
    document.getElementById('category').value = verifiedOrderData.category;
    document.getElementById('payment_method').value = verifiedOrderData.payment_method;
    document.getElementById('delivery_pincode').value = verifiedOrderData.pincode;
    ['order_value', 'category', 'payment_method', 'delivery_pincode'].forEach(id => {
        const el = document.getElementById(id);
        el.readOnly = true;
        el.disabled = true;
    });

    step2Details.style.display = 'block';
    resultSection.style.display = 'none';
    errorSection.style.display = 'none';
}

async function verifyOrderCustomer() {
    const orderId = document.querySelector('#verification-form #order_id').value;
    const customerId = document.getElementById('customer_id').value;

    verifyBtn.disabled = true;
    verifyBtn.textContent = 'Verifying...';
    verificationError.style.display = 'none';
    verificationError.textContent = '';

    try {
        const requestPayload = { order_id: orderId, customer_id: customerId };
        const response = await fetch(`${API_BASE}/verify-order`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestPayload),
        });

        const data = await response.json();
        if (window.recordApiCall) {
            window.recordApiCall('POST /verify-order', requestPayload, data, response.status);
        }

        if (!response.ok) {
            throw new Error(formatDetail(data.detail, `HTTP ${response.status}`));
        }

        // Check for verification errors
        if (data.errors && data.errors.length > 0) {
            throw new Error(data.errors[0]);
        }

        // Success - show step 2 with order data
        showStep2(data.order_data || data);
    } catch (err) {
        verificationError.textContent = err.message || 'Verification failed';
        verificationError.style.display = 'block';
    } finally {
        verifyBtn.disabled = false;
        verifyBtn.textContent = 'Verify & Continue';
    }
}

function setFormDisabled(disabled) {
    const inputs = analyzeForm.querySelectorAll('input, select, button');
    inputs.forEach(input => {
        if (input.id !== 'back-btn') input.disabled = disabled;
    });
    submitBtn.disabled = disabled;
    backBtn.disabled = disabled;
}

async function analyzeOrder() {
    // Submit the canonical values returned by /verify-order (inputs are read-only)
    const payload = verifiedOrderData ? {
        order_id: verifiedOrderData.order_id,
        customer_id: verifiedOrderData.customer_id,
        order_value: verifiedOrderData.order_value,
        category: verifiedOrderData.category,
        payment_method: verifiedOrderData.payment_method,
        delivery_pincode: verifiedOrderData.pincode,
    } : {
        order_id: document.querySelector('#verification-form #order_id').value,
        customer_id: document.querySelector('#verification-form #customer_id').value,
        order_value: parseFloat(document.getElementById('order_value').value),
        category: document.getElementById('category').value,
        payment_method: document.getElementById('payment_method').value,
        delivery_pincode: document.getElementById('delivery_pincode').value,
    };

    setFormDisabled(true);
    submitBtn.textContent = 'Analyzing...';
    resultSection.style.display = 'none';
    errorSection.style.display = 'none';

    try {
        const response = await fetch(`${API_BASE}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        const data = await response.json();
        if (window.recordApiCall) {
            window.recordApiCall('POST /analyze', payload, data, response.status);
        }

        if (!response.ok) {
            throw new Error(formatDetail(data.detail, `HTTP ${response.status}`));
        }

        renderResult(data);
        resultSection.style.display = 'block';
    } catch (err) {
        console.error('Analyze error:', err);
        errorMessage.textContent = err.message || String(err);
        errorSection.style.display = 'block';
    } finally {
        setFormDisabled(false);
        submitBtn.textContent = 'Analyze Risk';
    }
}

function renderResult(data) {
    const score = data.risk_score;
    scoreValue.textContent = score.toFixed(1);
    scoreCircle.style.background = getScoreGradient(score);

    const recommendedAction = data.action_brief?.recommended_action || data.recommendation;
    recommendationBadge.textContent = recommendedAction;
    recommendationBadge.className = 'recommendation-badge ' + recommendedAction.toLowerCase().replace(' ', '-');

    const confidence = data.confidence_score;
    confidenceBadge.textContent = `Confidence: ${(confidence * 100).toFixed(0)}%`;
    confidenceBar.style.width = `${confidence * 100}%`;
    confidenceBar.style.background = confidence >= 0.8 ? '#22c55e' : confidence >= 0.5 ? '#eab308' : '#ef4444';

    const companyName = data.company_name || data.action_brief?.company_name;
    if (companyName) {
        companyInfo.textContent = `Customer: ${companyName}`;
        companyInfo.style.display = 'block';
    } else {
        companyInfo.style.display = 'none';
    }

    // Dev-only: expected-vs-actual comparison badge (element exists only on /dev).
    if (comparisonBadge && window.expectedRiskLevel) {
        const actualAction = recommendedAction;
        const expected = window.expectedRiskLevel;
        const match = expected.includes(actualAction);

        comparisonBadge.textContent = match
            ? `✓ Expected: ${expected} | Actual: ${actualAction}`
            : `⚠ Expected: ${expected} | Actual: ${actualAction}`;
        comparisonBadge.className = `comparison-badge ${match ? 'match' : 'mismatch'}`;
        comparisonBadge.style.display = 'inline-block';
    } else if (comparisonBadge) {
        comparisonBadge.style.display = 'none';
    }

    // Check for order/customer mismatch in errors or audit_trail
    const allErrors = [...(data.errors || []), ...(data.audit_trail || [])];
    const mismatchError = allErrors.find(e => e.includes('does not belong to customer'));
    if (mismatchError) {
        showErrorModal('Order/Customer Mismatch', mismatchError);
        errorSection.style.display = 'none';
        resultSection.style.display = 'none';
        return;
    }

    if (data.risk_data?.risk_factors && data.risk_data.risk_factors.length > 0) {
        riskFactorsList.innerHTML = '';
        data.risk_data.risk_factors.forEach(factor => {
            const li = document.createElement('li');
            li.textContent = factor;
            riskFactorsList.appendChild(li);
        });
        detailSections.style.display = 'block';
    } else {
        detailSections.style.display = 'none';
    }

    if (data.risk_data?.risk_narrative) {
        riskNarrative.textContent = data.risk_data.risk_narrative;
        detailSections.style.display = 'block';
    }

    const brief = data.action_brief;
    const sections = [
        { key: 'order_summary', label: 'Order Summary' },
        { key: 'risk_assessment', label: 'Risk Assessment' },
        { key: 'market_context', label: 'Market Context' },
        { key: 'mitigation_suggestions', label: 'Mitigation Suggestions', isList: true },
        { key: 'key_concerns', label: 'Key Concerns', isList: true },
    ];

    briefSections.innerHTML = '';
    sections.forEach(s => {
        const value = brief[s.key];
        if (!value) return;

        const div = document.createElement('div');
        div.className = 'brief-section';
        const h3 = document.createElement('h3');
        h3.textContent = s.label;
        div.appendChild(h3);

        if (s.isList && Array.isArray(value)) {
            const ul = document.createElement('ul');
            value.forEach(item => {
                const li = document.createElement('li');
                li.textContent = item;
                ul.appendChild(li);
            });
            div.appendChild(ul);
        } else {
            const p = document.createElement('p');
            p.textContent = value;
            div.appendChild(p);
        }
        briefSections.appendChild(div);
    });

    auditList.innerHTML = '';
    if (data.audit_trail && data.audit_trail.length > 0) {
        // Deduplicate audit trail errors
        const uniqueErrors = [...new Set(data.audit_trail)];
        uniqueErrors.forEach(err => {
            const li = document.createElement('li');
            li.textContent = err;
            auditList.appendChild(li);
        });
    } else {
        const li = document.createElement('li');
        li.textContent = 'No errors or warnings';
        li.style.borderLeftColor = '#22c55e';
        li.style.color = '#166534';
        auditList.appendChild(li);
    }

    processingTime.textContent = data.processing_time_ms;
    resultOrderId.textContent = data.order_id;
}

function getScoreGradient(score) {
    if (score <= 25) {
        return 'conic-gradient(from 0deg, #22c55e 0deg, #22c55e 90deg, #eab308 240deg, #ef4444 360deg)';
    } else if (score <= 60) {
        return 'conic-gradient(from 0deg, #22c55e 0deg, #eab308 90deg, #eab308 240deg, #ef4444 360deg)';
    } else {
        return 'conic-gradient(from 0deg, #22c55e 0deg, #eab308 90deg, #ef4444 240deg, #ef4444 360deg)';
    }
}

function showErrorModal(title, message) {
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center;
        z-index: 10000;
    `;
    modal.innerHTML = `
        <div style="background: white; padding: 24px; border-radius: 12px; max-width: 400px; margin: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.2);">
            <h3 style="margin: 0 0 12px; color: #ef4444; font-size: 1.1rem;">${title}</h3>
            <p style="margin: 0 0 20px; color: #374151; line-height: 1.5;">${message}</p>
            <button onclick="this.closest('.modal-overlay').remove()" style="
                background: #ef4444; color: white; border: none; padding: 10px 24px;
                border-radius: 6px; font-weight: 600; cursor: pointer; width: 100%;
            ">OK</button>
        </div>
    `;
    modal.className = 'modal-overlay';
    document.body.appendChild(modal);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });
}

function wireSharedFlow() {
    verificationForm.addEventListener('submit', (e) => {
        e.preventDefault();
        verifyOrderCustomer();
    });

    backBtn.addEventListener('click', showStep1);

    analyzeForm.addEventListener('submit', (e) => {
        e.preventDefault();
        analyzeOrder();
    });
}
