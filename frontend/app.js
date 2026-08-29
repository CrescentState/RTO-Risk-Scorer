// RTO Risk Scorer Dashboard - Frontend Application
// Configurable API base URL (works for same-origin and cross-origin)
const API_BASE = window.RTO_API_BASE || '';

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('risk-form');
    const submitBtn = document.getElementById('submit-btn');
    const placeholder = document.getElementById('placeholder-text');
    const resultsContent = document.getElementById('results-content');
    const btnText = submitBtn.querySelector('.btn-text') || submitBtn;

    // Add loading spinner to button
    const spinnerHtml = '<span class="spinner"></span>';
    const originalBtnHtml = submitBtn.innerHTML;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Clear previous validation errors
        clearValidationErrors();

        // Validate form
        if (!validateForm()) {
            return;
        }

        // UI Loading state
        submitBtn.disabled = true;
        submitBtn.innerHTML = spinnerHtml + ' Evaluating...';

        const payload = {
            order_id: document.getElementById('order_id').value.trim(),
            customer_id: document.getElementById('customer_id').value.trim(),
            order_value: parseFloat(document.getElementById('order_value').value),
            category: document.getElementById('category').value,
            payment_method: document.getElementById('payment_method').value,
            delivery_pincode: document.getElementById('delivery_pincode').value.trim()
        };

        try {
            const response = await fetch(`${API_BASE}/api/v1/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            // Handle non-JSON error responses
            let data;
            const contentType = response.headers.get('content-type');
            if (!response.ok) {
                let errorMsg = `Request failed with status ${response.status}`;
                if (contentType && contentType.includes('application/json')) {
                    try {
                        const errorData = await response.json();
                        errorMsg = errorData.detail || errorMsg;
                    } catch {
                        // Ignore JSON parse errors
                    }
                } else {
                    try {
                        const text = await response.text();
                        if (text) errorMsg = text.substring(0, 200);
                    } catch { }
                }
                throw new Error(errorMsg);
            }

            data = await response.json();
            renderResults(data);

        } catch (err) {
            showError(err.message || 'Analysis request failed');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnHtml;
        }
    });

    function validateForm() {
        let isValid = true;
        const fields = [
            { id: 'order_id', pattern: /^ORD_[0-9]{6}$/, msg: 'Format: ORD_XXXXXX' },
            { id: 'customer_id', pattern: /^CUST_[0-9]{5}$/, msg: 'Format: CUST_XXXXX' },
            { id: 'order_value', type: 'number', min: 0.01, msg: 'Must be > 0' },
            { id: 'delivery_pincode', pattern: /^[0-9]{6}$/, msg: '6-digit pincode' }
        ];

        fields.forEach(field => {
            const input = document.getElementById(field.id);
            const errorEl = input.parentElement.querySelector('.field-error');
            let valid = true;

            if (field.type === 'number') {
                const val = parseFloat(input.value);
                valid = !isNaN(val) && val >= (field.min || 0);
            } else if (field.pattern) {
                valid = field.pattern.test(input.value.trim());
            } else {
                valid = input.value.trim().length > 0;
            }

            if (!valid) {
                isValid = false;
                showFieldError(input, field.msg || 'Invalid input');
            } else if (errorEl) {
                errorEl.remove();
            }
        });

        return isValid;
    }

    function showFieldError(input, message) {
        let errorEl = input.parentElement.querySelector('.field-error');
        if (!errorEl) {
            errorEl = document.createElement('div');
            errorEl.className = 'field-error';
            errorEl.style.color = 'var(--red-color)';
            errorEl.style.fontSize = '0.75rem';
            errorEl.style.marginTop = '4px';
            input.parentElement.appendChild(errorEl);
        }
        errorEl.innerText = errorEl.dataset.msg = input.parentElement.querySelector('.field-error')?.dataset.msg || '';
        errorEl.innerText = message;
    }

    function clearValidationErrors() {
        document.querySelectorAll('.field-error').forEach(el => el.remove());
        const existingError = document.querySelector('.form-error');
        if (existingError) existingError.remove();
    }

    function showError(message) {
        clearValidationErrors();
        const errorDiv = document.createElement('div');
        errorDiv.className = 'form-error';
        errorDiv.style.cssText = 'color: var(--red-color); padding: 12px; background: var(--red-light); border-radius: 6px; margin-bottom: 16px;';
        errorDiv.innerText = message;
        form.prepend(errorDiv);
    }

    function renderResults(data) {
        placeholder.classList.add('hidden');
        resultsContent.classList.remove('hidden');

        // Risk score styling & rendering
        const scoreElem = document.getElementById('risk-score');
        const score = data.risk_score;
        scoreElem.innerText = score.toFixed(1);

        scoreElem.className = 'score-badge';
        if (score <= 25.0) {
            scoreElem.classList.add('bg-green');
        } else if (score <= 60.0) {
            scoreElem.classList.add('bg-yellow');
        } else {
            scoreElem.classList.add('bg-red');
        }

        // Recommendation Badge - FIX: use action_brief.recommended_action
        const recBadge = document.getElementById('recommendation-badge');
        const rec = data.action_brief?.recommended_action || data.recommendation || 'Manual Review';
        recBadge.innerText = rec;
        recBadge.className = 'badge';

        if (rec === 'Auto-Approve') {
            recBadge.classList.add('badge-green');
        } else if (rec === 'Manual Review') {
            recBadge.classList.add('badge-yellow');
        } else {
            recBadge.classList.add('badge-red');
        }

        // Confidence Indicator
        const confidencePct = Math.round(data.confidence_score * 100);
        document.getElementById('confidence-text').innerText = `${confidencePct}%`;
        const fill = document.getElementById('confidence-fill');
        fill.style.width = `${confidencePct}%`;

        if (confidencePct < 50) {
            fill.style.backgroundColor = 'var(--red-color)';
        } else if (confidencePct < 80) {
            fill.style.backgroundColor = 'var(--yellow-color)';
        } else {
            fill.style.backgroundColor = 'var(--green-color)';
        }

        // Narrative ActionBrief Populate - FIX: use correct field names
        const brief = data.action_brief || {};
        document.getElementById('brief-order-summary').innerText = brief.order_summary || 'N/A';
        document.getElementById('brief-risk-assessment').innerText = brief.risk_assessment || 'N/A';
        document.getElementById('brief-market-context').innerText = brief.market_context || 'N/A';

        // Lists rendering helper - FIX: use correct field names
        renderList('brief-concerns', data.risk_data?.risk_factors || brief.key_concerns || []);
        renderList('brief-mitigations', brief.mitigation_suggestions || []);

        // Audit Trail - FIX: use data.errors
        document.getElementById('processing-time').innerText = data.processing_time_ms || 0;
        renderList('audit-logs', data.audit_trail || data.errors || [], 'No pipeline errors or flags recorded.');
    }

    function renderList(elementId, items, emptyMessage = 'None reported.') {
        const ul = document.getElementById(elementId);
        if (!ul) return;

        ul.innerHTML = '';
        if (!items || items.length === 0) {
            const li = document.createElement('li');
            li.innerText = emptyMessage;
            li.className = 'text-muted';
            ul.appendChild(li);
            return;
        }

        items.forEach(item => {
            const li = document.createElement('li');
            li.innerText = item;
            ul.appendChild(li);
        });
    }

    function showError(message) {
        const existingError = document.querySelector('.form-error');
        if (existingError) existingError.remove();

        const errorDiv = document.createElement('div');
        errorDiv.className = 'form-error';
        errorDiv.style.cssText = 'color: var(--red-color); padding: 12px; background: var(--red-light); border-radius: 6px; margin-bottom: 16px;';
        errorDiv.innerText = message;
        form.prepend(errorDiv);
    }
});