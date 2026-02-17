/* ═══════════════════════════════════════════════════════════════════════════
   Entity Allocation — Single-page application
   ═══════════════════════════════════════════════════════════════════════════ */

const API = '';
let currentPage = 'dashboard';
let currentMonth = '2025-01';
let enumsCache = null;

// ─── Utilities ──────────────────────────────────────────────────────────────

async function api(path, opts = {}) {
    const url = `${API}${path}`;
    const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || JSON.stringify(err));
    }
    return res.json();
}

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function fmt(n) {
    if (n == null) return '-';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);
}

function fmtDec(n) {
    if (n == null) return '-';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

function pct(n) {
    return n != null ? `${n.toFixed(1)}%` : '-';
}

function toast(msg, type = 'info') {
    const c = $('#toast-container');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

function badge(text, cls) {
    return `<span class="badge badge-${cls}">${text}</span>`;
}

function statusBadge(status) {
    return badge(status, status);
}

function typeBadge(type) {
    return badge(type, (type || '').toLowerCase());
}

async function getEnums() {
    if (!enumsCache) enumsCache = await api('/api/enums');
    return enumsCache;
}

// ─── Navigation ─────────────────────────────────────────────────────────────

function navigate(page) {
    currentPage = page;
    $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === page));
    renderPage(page);
}

function renderPage(page) {
    const main = $('#main-content');
    main.innerHTML = '<div class="loading-center"><div class="spinner"></div></div>';
    const renderers = {
        dashboard: renderDashboard,
        expenses: renderExpenses,
        allocations: renderAllocations,
        entities: renderEntities,
        policies: renderPolicies,
        journal: renderJournal,
        compliance: renderCompliance,
    };
    (renderers[page] || renderDashboard)();
}

// ─── Modal ──────────────────────────────────────────────────────────────────

function openModal(html) {
    $('#modal-content').innerHTML = html;
    $('#modal-overlay').classList.add('active');
}

function closeModal() {
    $('#modal-overlay').classList.remove('active');
}

function closeModalOverlay(e) {
    if (e.target === e.currentTarget) closeModal();
}

// ═══════════════════════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════════════════════

async function renderDashboard() {
    const main = $('#main-content');
    try {
        const [data, months] = await Promise.all([
            api(`/api/dashboard?month=${currentMonth}`),
            api('/api/dashboard/months'),
        ]);

        const entityRows = (data.by_entity || [])
            .sort((a, b) => b.allocated_amount - a.allocated_amount)
            .map(e => `<tr>
                <td class="vendor">${e.entity}</td>
                <td>${typeBadge(e.type)}</td>
                <td class="amount">${fmtDec(e.allocated_amount)}</td>
                <td class="amount">${e.allocation_count}</td>
            </tr>`).join('');

        const categoryRows = (data.by_category || [])
            .sort((a, b) => b.amount - a.amount)
            .map(c => `<tr>
                <td class="vendor">${c.category}</td>
                <td class="amount">${c.count}</td>
                <td class="amount">${fmtDec(c.amount)}</td>
            </tr>`).join('');

        // Compliance summary
        const compFunds = Object.entries(data.compliance || {});
        const compliantCount = compFunds.filter(([_, v]) => v.compliant).length;
        const violationCount = compFunds.length - compliantCount;

        const monthOpts = months.map(m =>
            `<option value="${m.value}" ${m.value === currentMonth ? 'selected' : ''}>${m.label}</option>`
        ).join('');

        main.innerHTML = `
            <div class="page-header">
                <h2>Dashboard</h2>
                <div class="actions">
                    <select class="form-control" style="width:160px" onchange="currentMonth=this.value; renderDashboard()">
                        ${monthOpts}
                    </select>
                </div>
            </div>

            <div class="stats-grid">
                <div class="stat-card accent">
                    <div class="stat-label">Total Expenses</div>
                    <div class="stat-value">${fmtDec(data.total_expense_amount)}</div>
                    <div class="stat-sub">${data.total_expense_count} expenses in ${data.period}</div>
                </div>
                <div class="stat-card yellow">
                    <div class="stat-label">Pending</div>
                    <div class="stat-value">${data.pending_count}</div>
                    <div class="stat-sub">awaiting allocation</div>
                </div>
                <div class="stat-card green">
                    <div class="stat-label">Allocated</div>
                    <div class="stat-value">${data.allocated_count}</div>
                    <div class="stat-sub">fully allocated</div>
                </div>
                <div class="stat-card ${violationCount > 0 ? 'red' : 'green'}">
                    <div class="stat-label">LPA Compliance</div>
                    <div class="stat-value">${violationCount > 0 ? violationCount + ' Issue' + (violationCount > 1 ? 's' : '') : 'All Clear'}</div>
                    <div class="stat-sub">${compFunds.length} funds monitored</div>
                </div>
            </div>

            <div class="grid-2">
                <div class="card">
                    <div class="card-header"><h3>Allocation by Entity</h3></div>
                    <div class="chart-container"><canvas id="entityChart"></canvas></div>
                    <div class="table-container" style="margin-top:16px">
                        <table>
                            <thead><tr><th>Entity</th><th>Type</th><th class="amount">Allocated</th><th class="amount">#</th></tr></thead>
                            <tbody>${entityRows || '<tr><td colspan="4" class="empty-state">No allocations</td></tr>'}</tbody>
                        </table>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header"><h3>By Expense Category</h3></div>
                    <div class="chart-container"><canvas id="categoryChart"></canvas></div>
                    <div class="table-container" style="margin-top:16px">
                        <table>
                            <thead><tr><th>Category</th><th class="amount">Count</th><th class="amount">Amount</th></tr></thead>
                            <tbody>${categoryRows || '<tr><td colspan="3" class="empty-state">No data</td></tr>'}</tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;

        // Render charts
        renderEntityChart(data.by_entity || []);
        renderCategoryChart(data.by_category || []);

    } catch (err) {
        main.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><div class="title">Error loading dashboard</div><div class="subtitle">${err.message}</div></div>`;
    }
}

function renderEntityChart(entities) {
    const canvas = document.getElementById('entityChart');
    if (!canvas || !entities.length) return;
    const colors = ['#6366f1', '#3b82f6', '#a855f7', '#14b8a6', '#eab308', '#ef4444', '#22c55e', '#f97316'];
    new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: entities.map(e => e.entity),
            datasets: [{
                data: entities.map(e => e.allocated_amount),
                backgroundColor: colors.slice(0, entities.length),
                borderWidth: 0,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { color: '#94a3b8', font: { size: 11 }, padding: 12 } },
                tooltip: {
                    callbacks: {
                        label: ctx => ` ${ctx.label}: ${fmtDec(ctx.raw)}`,
                    }
                }
            },
        },
    });
}

function renderCategoryChart(categories) {
    const canvas = document.getElementById('categoryChart');
    if (!canvas || !categories.length) return;
    const sorted = [...categories].sort((a, b) => b.amount - a.amount).slice(0, 8);
    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: sorted.map(c => c.category),
            datasets: [{
                data: sorted.map(c => c.amount),
                backgroundColor: '#6366f1',
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => fmtDec(ctx.raw) } },
            },
            scales: {
                x: { ticks: { color: '#64748b', callback: v => fmt(v) }, grid: { color: '#2a2e3f' } },
                y: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { display: false } },
            },
        },
    });
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPENSES
// ═══════════════════════════════════════════════════════════════════════════

async function renderExpenses() {
    const main = $('#main-content');
    try {
        const [res, enums] = await Promise.all([
            api(`/api/expenses?month=${currentMonth}&limit=200`),
            getEnums(),
        ]);

        const catOpts = enums.expense_categories.map(c => `<option value="${c}">${c}</option>`).join('');
        const statusOpts = enums.expense_statuses.map(s => `<option value="${s}">${s}</option>`).join('');

        const rows = res.expenses.map(e => `<tr>
            <td style="color:var(--text-muted);font-size:12px">${e.expense_id}</td>
            <td>${e.date}</td>
            <td class="vendor">${e.vendor}</td>
            <td class="amount">${fmtDec(e.amount)}</td>
            <td>${e.expense_category || '-'}</td>
            <td>${statusBadge(e.status)}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.description || ''}</td>
            <td>
                <button class="btn btn-sm btn-secondary" onclick="showExpenseDetail(${e.expense_id})">View</button>
            </td>
        </tr>`).join('');

        main.innerHTML = `
            <div class="page-header">
                <h2>Expenses</h2>
                <div class="actions">
                    <select class="form-control" style="width:140px" onchange="currentMonth=this.value; renderExpenses()">
                        <option value="">All Months</option>
                    </select>
                    <button class="btn btn-secondary" onclick="showUploadModal()">📁 Import CSV</button>
                    <button class="btn btn-primary" onclick="showAddExpenseModal()">+ Add Expense</button>
                </div>
            </div>

            <div class="card" style="margin-bottom:20px">
                <div class="upload-zone" id="upload-zone">
                    <input type="file" accept=".csv" onchange="handleFileUpload(this.files[0])">
                    <div class="icon">📄</div>
                    <div class="title">Drag & drop CSV file here</div>
                    <div class="subtitle">or click to browse — accepts standard expense CSV format</div>
                </div>
                <div id="upload-result"></div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>Expenses (${res.total})</h3>
                </div>
                <div class="table-container">
                    <table>
                        <thead><tr>
                            <th>ID</th><th>Date</th><th>Vendor</th><th class="amount">Amount</th>
                            <th>Category</th><th>Status</th><th>Description</th><th></th>
                        </tr></thead>
                        <tbody>${rows || '<tr><td colspan="8"><div class="empty-state"><div class="title">No expenses found</div></div></td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        `;

        // Setup drag and drop
        setupDragDrop();

        // Load month selector
        const months = await api('/api/dashboard/months');
        const sel = main.querySelector('.page-header select');
        months.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.value;
            opt.textContent = m.label;
            if (m.value === currentMonth) opt.selected = true;
            sel.appendChild(opt);
        });

    } catch (err) {
        main.innerHTML = `<div class="empty-state"><div class="title">Error</div><div class="subtitle">${err.message}</div></div>`;
    }
}

function setupDragDrop() {
    const zone = document.getElementById('upload-zone');
    if (!zone) return;
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleFileUpload(e.dataTransfer.files[0]);
    });
}

async function handleFileUpload(file) {
    if (!file) return;
    const resultDiv = document.getElementById('upload-result');
    resultDiv.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Uploading...</div>';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/expenses/upload', { method: 'POST', body: formData });
        const data = await res.json();

        if (data.imported > 0) {
            resultDiv.innerHTML = `
                <div class="upload-result success">
                    <strong>✅ Imported ${data.imported} expenses</strong>
                    ${data.skipped ? `<br>Skipped: ${data.skipped}` : ''}
                    ${data.duplicates?.length ? `<br>Duplicates: ${data.duplicates.length}` : ''}
                </div>`;
            toast(`Imported ${data.imported} expenses`, 'success');
            setTimeout(() => renderExpenses(), 1500);
        } else {
            resultDiv.innerHTML = `
                <div class="upload-result error">
                    <strong>⚠️ No expenses imported</strong>
                    ${data.errors?.map(e => `<br>• ${e}`).join('') || ''}
                    ${data.duplicates?.map(d => `<br>• ${d}`).join('') || ''}
                </div>`;
        }
    } catch (err) {
        resultDiv.innerHTML = `<div class="upload-result error"><strong>Error:</strong> ${err.message}</div>`;
    }
}

async function showExpenseDetail(id) {
    try {
        const res = await api(`/api/expenses?limit=200`);
        const expense = res.expenses.find(e => e.expense_id === id);
        if (!expense) return;

        const allocRows = (expense.allocations || []).map(a => `<tr>
            <td class="vendor">${a.entity_name}</td>
            <td class="amount">${fmtDec(a.amount)}</td>
            <td class="amount">${pct(a.percentage)}</td>
            <td>${a.method}</td>
        </tr>`).join('');

        const barSegments = (expense.allocations || []).map((a, i) =>
            `<div class="alloc-bar-segment" style="width:${a.percentage}%" title="${a.entity_name}: ${pct(a.percentage)}">${a.percentage > 10 ? pct(a.percentage) : ''}</div>`
        ).join('');

        openModal(`
            <div class="modal-header">
                <h3>Expense #${expense.expense_id}</h3>
                <button class="btn btn-sm btn-secondary" onclick="closeModal()">✕</button>
            </div>
            <div class="modal-body">
                <div style="margin-bottom:16px">
                    <div style="font-size:18px;font-weight:600">${expense.vendor}</div>
                    <div style="color:var(--text-muted);font-size:13px;margin-top:2px">${expense.description || ''}</div>
                </div>
                <div class="form-row" style="margin-bottom:16px">
                    <div><span style="color:var(--text-muted);font-size:12px">DATE</span><br>${expense.date}</div>
                    <div><span style="color:var(--text-muted);font-size:12px">AMOUNT</span><br><strong style="font-family:var(--font-mono);font-size:18px">${fmtDec(expense.amount)}</strong></div>
                </div>
                <div class="form-row" style="margin-bottom:16px">
                    <div><span style="color:var(--text-muted);font-size:12px">CATEGORY</span><br>${expense.expense_category || '-'}</div>
                    <div><span style="color:var(--text-muted);font-size:12px">STATUS</span><br>${statusBadge(expense.status)}</div>
                </div>

                ${expense.allocations?.length ? `
                    <h4 style="font-size:13px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted);margin:20px 0 8px">Allocation</h4>
                    <div class="alloc-bar">${barSegments}</div>
                    <table style="margin-top:12px">
                        <thead><tr><th>Entity</th><th class="amount">Amount</th><th class="amount">%</th><th>Method</th></tr></thead>
                        <tbody>${allocRows}</tbody>
                    </table>
                ` : '<div style="color:var(--text-muted);margin-top:16px">No allocations yet</div>'}
            </div>
            <div class="modal-footer">
                ${expense.status === 'pending' ? `<button class="btn btn-primary" onclick="previewAndAllocate(${expense.expense_id})">▶ Allocate</button>` : ''}
                ${expense.status === 'allocated' ? `<button class="btn btn-secondary" onclick="showOverrideModal(${expense.expense_id})">Override</button>` : ''}
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>
        `);
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function showAddExpenseModal() {
    const enums = await getEnums();
    const entities = await api('/api/entities');
    const catOpts = enums.expense_categories.map(c => `<option value="${c}">${c}</option>`).join('');
    const entityOpts = entities.filter(e => e.entity_type === 'GP').map(e => `<option value="${e.entity_id}">${e.entity_name}</option>`).join('');

    openModal(`
        <div class="modal-header">
            <h3>Add Expense</h3>
            <button class="btn btn-sm btn-secondary" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
            <div class="form-row">
                <div class="form-group"><label>Date</label><input type="date" class="form-control" id="exp-date" value="2025-01-15"></div>
                <div class="form-group"><label>Amount</label><input type="number" class="form-control" id="exp-amount" placeholder="0.00" step="0.01"></div>
            </div>
            <div class="form-group"><label>Vendor</label><input type="text" class="form-control" id="exp-vendor" placeholder="e.g. Kirkland & Ellis"></div>
            <div class="form-group"><label>Description</label><input type="text" class="form-control" id="exp-desc" placeholder="Description"></div>
            <div class="form-row">
                <div class="form-group"><label>Category</label><select class="form-control" id="exp-cat">${catOpts}</select></div>
                <div class="form-group"><label>Source Entity</label><select class="form-control" id="exp-entity"><option value="">-</option>${entityOpts}</select></div>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="submitAddExpense()">Add Expense</button>
        </div>
    `);
}

async function submitAddExpense() {
    try {
        const body = {
            date: document.getElementById('exp-date').value,
            vendor: document.getElementById('exp-vendor').value,
            amount: parseFloat(document.getElementById('exp-amount').value),
            description: document.getElementById('exp-desc').value,
            category: document.getElementById('exp-cat').value,
            source_entity_id: document.getElementById('exp-entity').value ? parseInt(document.getElementById('exp-entity').value) : null,
        };
        await api('/api/expenses', { method: 'POST', body: JSON.stringify(body) });
        toast('Expense added', 'success');
        closeModal();
        renderExpenses();
    } catch (err) {
        toast(err.message, 'error');
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// ALLOCATIONS
// ═══════════════════════════════════════════════════════════════════════════

async function renderAllocations() {
    const main = $('#main-content');
    try {
        const [pending, months] = await Promise.all([
            api(`/api/expenses?status=pending&limit=200`),
            api('/api/dashboard/months'),
        ]);

        const monthOpts = months.map(m =>
            `<option value="${m.value}" ${m.value === currentMonth ? 'selected' : ''}>${m.label}</option>`
        ).join('');

        const rows = pending.expenses.map(e => `<tr>
            <td><input type="checkbox" class="alloc-check" value="${e.expense_id}" checked></td>
            <td>${e.date}</td>
            <td class="vendor">${e.vendor}</td>
            <td class="amount">${fmtDec(e.amount)}</td>
            <td>${e.expense_category || '-'}</td>
            <td><button class="btn btn-sm btn-secondary" onclick="previewSingleAlloc(${e.expense_id})">Preview</button></td>
        </tr>`).join('');

        main.innerHTML = `
            <div class="page-header">
                <h2>Allocations</h2>
                <div class="actions">
                    <select class="form-control" style="width:140px" id="alloc-month" onchange="currentMonth=this.value">
                        ${monthOpts}
                    </select>
                    <button class="btn btn-secondary" onclick="previewMonth()">👁 Preview Month</button>
                    <button class="btn btn-success" onclick="allocateMonth()">▶ Allocate Month</button>
                    <button class="btn btn-secondary" onclick="recalcMonth()">🔄 Recalculate</button>
                </div>
            </div>

            <div class="card" style="margin-bottom:20px">
                <div class="card-header">
                    <h3>Pending Expenses (${pending.total})</h3>
                    <button class="btn btn-sm btn-primary" onclick="allocateSelected()">Allocate Selected</button>
                </div>
                <div class="table-container">
                    <table>
                        <thead><tr><th style="width:30px"><input type="checkbox" onclick="toggleAllChecks(this)" checked></th><th>Date</th><th>Vendor</th><th class="amount">Amount</th><th>Category</th><th></th></tr></thead>
                        <tbody>${rows || '<tr><td colspan="6"><div class="empty-state"><div class="icon">✅</div><div class="title">All expenses allocated</div></div></td></tr>'}</tbody>
                    </table>
                </div>
            </div>

            <div id="allocation-preview"></div>
        `;
    } catch (err) {
        main.innerHTML = `<div class="empty-state"><div class="title">Error</div><div class="subtitle">${err.message}</div></div>`;
    }
}

function toggleAllChecks(master) {
    $$('.alloc-check').forEach(cb => cb.checked = master.checked);
}

async function previewSingleAlloc(expenseId) {
    try {
        const preview = await api(`/api/allocate/preview/${expenseId}`);
        const previewDiv = document.getElementById('allocation-preview');

        if (preview.error) {
            previewDiv.innerHTML = `<div class="card"><div class="upload-result error"><strong>Cannot allocate:</strong> ${preview.error}</div></div>`;
            return;
        }

        const segments = (preview.allocations || []).map((a, i) =>
            `<div class="alloc-bar-segment" style="width:${a.percentage}%">${a.percentage > 8 ? pct(a.percentage) : ''}</div>`
        ).join('');

        const rows = (preview.allocations || []).map(a => `<tr>
            <td class="vendor">${a.entity_name}</td>
            <td class="amount">${fmtDec(a.amount)}</td>
            <td class="amount">${pct(a.percentage)}</td>
        </tr>`).join('');

        previewDiv.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>Preview: ${preview.vendor} (${fmtDec(preview.amount)})</h3>
                    <button class="btn btn-sm btn-success" onclick="allocateSingle(${expenseId})">✓ Approve & Allocate</button>
                </div>
                <div class="alloc-bar">${segments}</div>
                <table style="margin-top:12px"><thead><tr><th>Entity</th><th class="amount">Amount</th><th class="amount">%</th></tr></thead><tbody>${rows}</tbody></table>
            </div>
        `;
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function allocateSingle(expenseId) {
    try {
        await api('/api/allocate', { method: 'POST', body: JSON.stringify({ expense_ids: [expenseId] }) });
        toast('Expense allocated', 'success');
        renderAllocations();
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function allocateSelected() {
    const ids = [...$$('.alloc-check:checked')].map(cb => parseInt(cb.value));
    if (!ids.length) { toast('No expenses selected', 'info'); return; }
    try {
        const res = await api('/api/allocate', { method: 'POST', body: JSON.stringify({ expense_ids: ids }) });
        toast(`Allocated ${res.allocated?.length || 0} expenses`, 'success');
        if (res.errors?.length) toast(`${res.errors.length} errors`, 'error');
        renderAllocations();
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function previewMonth() {
    const month = document.getElementById('alloc-month')?.value || currentMonth;
    try {
        const res = await api('/api/allocate', { method: 'POST', body: JSON.stringify({ month, preview: true }) });
        const previewDiv = document.getElementById('allocation-preview');
        const rows = (res.allocated || []).map(a => `<tr>
            <td>${a.expense_id}</td>
            <td class="vendor">${a.vendor}</td>
            <td class="amount">${fmtDec(a.amount)}</td>
            <td>${a.allocations?.length || 0} entities</td>
        </tr>`).join('');

        const errRows = (res.errors || []).map(e => `<tr style="color:var(--red)">
            <td>${e.expense_id}</td>
            <td>${e.vendor || ''}</td>
            <td colspan="2">${e.error}</td>
        </tr>`).join('');

        previewDiv.innerHTML = `<div class="card">
            <div class="card-header"><h3>Month Preview: ${month}</h3>
                <button class="btn btn-success" onclick="allocateMonth()">✓ Approve All</button>
            </div>
            <table><thead><tr><th>ID</th><th>Vendor</th><th class="amount">Amount</th><th>Entities</th></tr></thead>
            <tbody>${rows}${errRows}</tbody></table>
            <div style="margin-top:12px;font-size:13px;color:var(--text-muted)">
                ${res.allocated?.length || 0} to allocate, ${res.errors?.length || 0} errors
            </div>
        </div>`;
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function allocateMonth() {
    const month = document.getElementById('alloc-month')?.value || currentMonth;
    try {
        const res = await api('/api/allocate', { method: 'POST', body: JSON.stringify({ month }) });
        toast(`Allocated ${res.allocated?.length || 0} expenses for ${month}`, 'success');
        renderAllocations();
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function recalcMonth() {
    const month = document.getElementById('alloc-month')?.value || currentMonth;
    if (!confirm(`Recalculate all allocations for ${month}? This will replace existing allocations.`)) return;
    try {
        const res = await api('/api/allocate', { method: 'POST', body: JSON.stringify({ month, recalculate: true }) });
        toast(`Recalculated ${res.allocated?.length || 0} expenses`, 'success');
        renderAllocations();
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function previewAndAllocate(expenseId) {
    closeModal();
    try {
        await api('/api/allocate', { method: 'POST', body: JSON.stringify({ expense_ids: [expenseId] }) });
        toast('Expense allocated', 'success');
        if (currentPage === 'expenses') renderExpenses();
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function showOverrideModal(expenseId) {
    closeModal();
    const entities = await api('/api/entities');
    const funds = entities.filter(e => e.entity_type === 'Fund' || e.entity_type === 'GP');

    const rows = funds.map(e => `
        <div class="form-row" style="align-items:center; margin-bottom:8px">
            <label style="font-size:13px;text-transform:none;letter-spacing:0">${e.entity_name}</label>
            <input type="number" class="form-control override-pct" data-entity-id="${e.entity_id}" placeholder="0" step="0.01" min="0" max="1" style="width:100px">
        </div>
    `).join('');

    openModal(`
        <div class="modal-header">
            <h3>Override Allocation #${expenseId}</h3>
            <button class="btn btn-sm btn-secondary" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
            <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">Enter decimal percentages (must sum to 1.0)</p>
            ${rows}
            <div class="form-group" style="margin-top:16px">
                <label>Reason</label>
                <input type="text" class="form-control" id="override-reason" placeholder="e.g. Per IC approval">
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="submitOverride(${expenseId})">Apply Override</button>
        </div>
    `);
}

async function submitOverride(expenseId) {
    const inputs = $$('.override-pct');
    const splits = {};
    inputs.forEach(inp => {
        const val = parseFloat(inp.value);
        if (val > 0) splits[inp.dataset.entityId] = val;
    });
    const reason = document.getElementById('override-reason')?.value || '';
    const total = Object.values(splits).reduce((a, b) => a + b, 0);
    if (Math.abs(total - 1.0) > 0.01) { toast(`Splits sum to ${total.toFixed(2)}, need 1.0`, 'error'); return; }
    if (!reason) { toast('Reason is required', 'error'); return; }

    try {
        await api(`/api/expenses/${expenseId}/override`, { method: 'POST', body: JSON.stringify({ new_splits: splits, reason }) });
        toast('Override applied', 'success');
        closeModal();
        renderPage(currentPage);
    } catch (err) {
        toast(err.message, 'error');
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// ENTITIES
// ═══════════════════════════════════════════════════════════════════════════

async function renderEntities() {
    const main = $('#main-content');
    try {
        const entities = await api('/api/entities');

        const rows = entities.map(e => `<tr>
            <td style="color:var(--text-muted);font-size:12px">${e.entity_id}</td>
            <td class="vendor">${e.entity_name}</td>
            <td>${typeBadge(e.entity_type)}</td>
            <td>${statusBadge(e.status)}</td>
            <td class="amount">${e.committed_capital ? fmt(e.committed_capital) : '-'}</td>
            <td class="amount">${e.invested_capital ? fmt(e.invested_capital) : '-'}</td>
            <td class="amount">${e.aum ? fmt(e.aum) : '-'}</td>
            <td class="amount">${e.headcount || '-'}</td>
            <td><button class="btn btn-sm btn-secondary" onclick="showEditEntityModal(${e.entity_id})">Edit</button></td>
        </tr>`).join('');

        main.innerHTML = `
            <div class="page-header">
                <h2>Entities</h2>
                <div class="actions">
                    <button class="btn btn-primary" onclick="showAddEntityModal()">+ Add Entity</button>
                </div>
            </div>
            <div class="card">
                <div class="table-container">
                    <table>
                        <thead><tr>
                            <th>ID</th><th>Name</th><th>Type</th><th>Status</th>
                            <th class="amount">Committed</th><th class="amount">Invested</th>
                            <th class="amount">AUM</th><th class="amount">HC</th><th></th>
                        </tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        `;
    } catch (err) {
        main.innerHTML = `<div class="empty-state"><div class="title">Error</div><div class="subtitle">${err.message}</div></div>`;
    }
}

async function showAddEntityModal() {
    const enums = await getEnums();
    const typeOpts = enums.entity_types.map(t => `<option value="${t}">${t}</option>`).join('');

    openModal(`
        <div class="modal-header">
            <h3>Add Entity</h3>
            <button class="btn btn-sm btn-secondary" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
            <div class="form-group"><label>Name</label><input type="text" class="form-control" id="ent-name" placeholder="Entity name"></div>
            <div class="form-row">
                <div class="form-group"><label>Type</label><select class="form-control" id="ent-type">${typeOpts}</select></div>
                <div class="form-group"><label>Vintage Year</label><input type="number" class="form-control" id="ent-vintage" placeholder="2024"></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label>Committed Capital</label><input type="number" class="form-control" id="ent-committed" placeholder="0"></div>
                <div class="form-group"><label>Invested Capital</label><input type="number" class="form-control" id="ent-invested" placeholder="0"></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label>AUM</label><input type="number" class="form-control" id="ent-aum" placeholder="0"></div>
                <div class="form-group"><label>Headcount</label><input type="number" class="form-control" id="ent-hc" placeholder="0" step="0.5"></div>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="submitAddEntity()">Create Entity</button>
        </div>
    `);
}

async function submitAddEntity() {
    try {
        await api('/api/entities', { method: 'POST', body: JSON.stringify({
            entity_name: document.getElementById('ent-name').value,
            entity_type: document.getElementById('ent-type').value,
            committed_capital: parseFloat(document.getElementById('ent-committed').value) || 0,
            invested_capital: parseFloat(document.getElementById('ent-invested').value) || 0,
            aum: parseFloat(document.getElementById('ent-aum').value) || 0,
            headcount: parseFloat(document.getElementById('ent-hc').value) || 0,
            vintage_year: parseInt(document.getElementById('ent-vintage').value) || null,
        })});
        toast('Entity created', 'success');
        closeModal();
        renderEntities();
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function showEditEntityModal(id) {
    const entity = await api(`/api/entities/${id}`);
    const enums = await getEnums();
    const statusOpts = enums.entity_statuses.map(s => `<option value="${s}" ${s === entity.status ? 'selected' : ''}>${s}</option>`).join('');

    openModal(`
        <div class="modal-header">
            <h3>Edit: ${entity.entity_name}</h3>
            <button class="btn btn-sm btn-secondary" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
            <div class="form-group"><label>Name</label><input type="text" class="form-control" id="ent-name" value="${entity.entity_name}"></div>
            <div class="form-group"><label>Status</label><select class="form-control" id="ent-status">${statusOpts}</select></div>
            <div class="form-row">
                <div class="form-group"><label>Committed Capital</label><input type="number" class="form-control" id="ent-committed" value="${entity.committed_capital || 0}"></div>
                <div class="form-group"><label>Invested Capital</label><input type="number" class="form-control" id="ent-invested" value="${entity.invested_capital || 0}"></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label>AUM</label><input type="number" class="form-control" id="ent-aum" value="${entity.aum || 0}"></div>
                <div class="form-group"><label>Headcount</label><input type="number" class="form-control" id="ent-hc" value="${entity.headcount || 0}" step="0.5"></div>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="submitEditEntity(${id})">Save Changes</button>
        </div>
    `);
}

async function submitEditEntity(id) {
    try {
        await api(`/api/entities/${id}`, { method: 'PUT', body: JSON.stringify({
            entity_name: document.getElementById('ent-name').value,
            status: document.getElementById('ent-status').value,
            committed_capital: parseFloat(document.getElementById('ent-committed').value) || 0,
            invested_capital: parseFloat(document.getElementById('ent-invested').value) || 0,
            aum: parseFloat(document.getElementById('ent-aum').value) || 0,
            headcount: parseFloat(document.getElementById('ent-hc').value) || 0,
        })});
        toast('Entity updated', 'success');
        closeModal();
        renderEntities();
    } catch (err) {
        toast(err.message, 'error');
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// POLICIES
// ═══════════════════════════════════════════════════════════════════════════

async function renderPolicies() {
    const main = $('#main-content');
    try {
        const policies = await api('/api/policies');

        const rows = policies.map(p => `<tr>
            <td style="color:var(--text-muted);font-size:12px">${p.policy_id}</td>
            <td class="vendor">${p.policy_name}</td>
            <td><span class="badge badge-fund">${p.methodology}</span></td>
            <td>${(p.categories || []).join(', ') || '-'}</td>
            <td>${p.target_entity_id || '-'}</td>
            <td>${p.effective_date ? p.effective_date.split('T')[0] : '-'}</td>
        </tr>`).join('');

        main.innerHTML = `
            <div class="page-header">
                <h2>Allocation Policies</h2>
                <div class="actions">
                    <button class="btn btn-primary" onclick="showAddPolicyModal()">+ Add Policy</button>
                </div>
            </div>
            <div class="card">
                <div class="table-container">
                    <table>
                        <thead><tr><th>ID</th><th>Name</th><th>Method</th><th>Categories</th><th>Target</th><th>Effective</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        `;
    } catch (err) {
        main.innerHTML = `<div class="empty-state"><div class="title">Error</div><div class="subtitle">${err.message}</div></div>`;
    }
}

async function showAddPolicyModal() {
    const enums = await getEnums();
    const methodOpts = enums.allocation_methods.map(m => `<option value="${m}">${m}</option>`).join('');
    const catOpts = enums.expense_categories.map(c => `<label style="display:inline-block;margin:3px 8px 3px 0;font-size:12px;text-transform:none;letter-spacing:0"><input type="checkbox" class="policy-cat" value="${c}"> ${c}</label>`).join('');
    const entities = await api('/api/entities');
    const entityOpts = entities.map(e => `<option value="${e.entity_id}">${e.entity_name}</option>`).join('');

    openModal(`
        <div class="modal-header">
            <h3>Add Policy</h3>
            <button class="btn btn-sm btn-secondary" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
            <div class="form-group"><label>Policy Name</label><input type="text" class="form-control" id="pol-name"></div>
            <div class="form-group"><label>Methodology</label><select class="form-control" id="pol-method">${methodOpts}</select></div>
            <div class="form-group"><label>Applicable Categories</label><div style="max-height:120px;overflow-y:auto;padding:8px;background:var(--bg-input);border-radius:6px;border:1px solid var(--border)">${catOpts}</div></div>
            <div class="form-group"><label>Target Entity (for direct/deal_specific)</label><select class="form-control" id="pol-target"><option value="">-</option>${entityOpts}</select></div>
            <div class="form-group"><label>Custom Splits JSON (for custom_split)</label><input type="text" class="form-control" id="pol-splits" placeholder='{"1": 0.5, "2": 0.5}'></div>
            <div class="form-group"><label>LPA Reference</label><input type="text" class="form-control" id="pol-lpa"></div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="submitAddPolicy()">Create Policy</button>
        </div>
    `);
}

async function submitAddPolicy() {
    try {
        const cats = [...$$('.policy-cat:checked')].map(cb => cb.value);
        let splits = {};
        const splitsStr = document.getElementById('pol-splits').value;
        if (splitsStr) splits = JSON.parse(splitsStr);

        await api('/api/policies', { method: 'POST', body: JSON.stringify({
            policy_name: document.getElementById('pol-name').value,
            methodology: document.getElementById('pol-method').value,
            categories: cats,
            entity_splits: splits,
            target_entity_id: document.getElementById('pol-target').value ? parseInt(document.getElementById('pol-target').value) : null,
            lpa_reference: document.getElementById('pol-lpa').value || null,
        })});
        toast('Policy created', 'success');
        closeModal();
        renderPolicies();
    } catch (err) {
        toast(err.message, 'error');
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// JOURNAL ENTRIES
// ═══════════════════════════════════════════════════════════════════════════

async function renderJournal() {
    const main = $('#main-content');
    try {
        const months = await api('/api/dashboard/months');
        const monthOpts = months.map(m => `<option value="${m.value}" ${m.value === currentMonth ? 'selected' : ''}>${m.label}</option>`).join('');

        main.innerHTML = `
            <div class="page-header">
                <h2>Journal Entries</h2>
                <div class="actions">
                    <select class="form-control" style="width:140px" id="je-month" onchange="loadJournalEntries()">
                        ${monthOpts}
                    </select>
                    <button class="btn btn-primary" onclick="downloadJournalCSV()">📥 Export CSV</button>
                </div>
            </div>
            <div id="je-content"><div class="loading-center"><div class="spinner"></div></div></div>
        `;
        loadJournalEntries();
    } catch (err) {
        main.innerHTML = `<div class="empty-state"><div class="title">Error</div><div class="subtitle">${err.message}</div></div>`;
    }
}

async function loadJournalEntries() {
    const month = document.getElementById('je-month')?.value || currentMonth;
    const container = document.getElementById('je-content');
    try {
        const data = await api(`/api/journal-entries?month=${month}`);

        if (!data.entries?.length) {
            container.innerHTML = '<div class="card"><div class="empty-state"><div class="icon">📒</div><div class="title">No journal entries</div><div class="subtitle">Allocate expenses first to generate journal entries</div></div></div>';
            return;
        }

        const rows = data.entries.slice(0, 100).map(e => `<tr>
            <td>${e.date}</td>
            <td style="font-family:var(--font-mono);font-size:12px">${e.journal_entry_id}</td>
            <td>${e.entity}</td>
            <td style="font-family:var(--font-mono);font-size:12px">${e.account_code}</td>
            <td>${e.account_name}</td>
            <td class="amount" style="color:${e.debit > 0 ? 'var(--text-primary)' : 'var(--text-muted)'}">${e.debit > 0 ? fmtDec(e.debit) : ''}</td>
            <td class="amount" style="color:${e.credit > 0 ? 'var(--green)' : 'var(--text-muted)'}">${e.credit > 0 ? fmtDec(e.credit) : ''}</td>
            <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--text-muted)">${e.memo}</td>
        </tr>`).join('');

        container.innerHTML = `
            <div class="card">
                <div class="card-header"><h3>${data.count} Journal Entry Lines</h3></div>
                <div class="table-container">
                    <table>
                        <thead><tr><th>Date</th><th>JE ID</th><th>Entity</th><th>Acct Code</th><th>Account</th><th class="amount">Debit</th><th class="amount">Credit</th><th>Memo</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
                ${data.count > 100 ? `<div style="padding:12px;color:var(--text-muted);font-size:13px">Showing 100 of ${data.count} entries. Export CSV for full data.</div>` : ''}
            </div>
        `;
    } catch (err) {
        container.innerHTML = `<div class="card"><div class="upload-result error">${err.message}</div></div>`;
    }
}

function downloadJournalCSV() {
    const month = document.getElementById('je-month')?.value || currentMonth;
    window.open(`/api/journal-entries/export?month=${month}`, '_blank');
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPLIANCE
// ═══════════════════════════════════════════════════════════════════════════

async function renderCompliance() {
    const main = $('#main-content');
    try {
        const data = await api('/api/compliance?year=2025');

        const cards = Object.entries(data.funds).map(([fund, info]) => {
            const isCompliant = info.compliant;
            const violations = (info.violations || []).map(v => `
                <div class="violation-item">
                    <div class="rule">${v.rule} (${v.severity})</div>
                    <div class="detail">${v.description}</div>
                    <div class="detail">Limit: ${fmtDec(v.limit)} | Actual: ${fmtDec(v.actual)} | Excess: ${fmtDec(v.excess)}</div>
                </div>
            `).join('');

            return `
                <div class="compliance-card ${isCompliant ? 'compliant' : 'violation'}">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <div class="fund-name">${fund}</div>
                        <div>${isCompliant ? badge('Compliant', 'compliant') : badge(info.violations.length + ' Violation(s)', 'violation')}</div>
                    </div>
                    ${violations || '<div style="color:var(--green);font-size:13px;margin-top:8px">✓ All LPA limits within bounds</div>'}
                </div>
            `;
        }).join('');

        const totalFunds = Object.keys(data.funds).length;
        const compliantFunds = Object.values(data.funds).filter(f => f.compliant).length;

        main.innerHTML = `
            <div class="page-header">
                <h2>LPA Compliance</h2>
                <div class="actions">
                    <span style="color:var(--text-muted);font-size:13px">Year: ${data.year}</span>
                </div>
            </div>

            <div class="stats-grid" style="margin-bottom:24px">
                <div class="stat-card green">
                    <div class="stat-label">Compliant Funds</div>
                    <div class="stat-value">${compliantFunds} / ${totalFunds}</div>
                </div>
                <div class="stat-card ${compliantFunds < totalFunds ? 'red' : 'green'}">
                    <div class="stat-label">Overall Status</div>
                    <div class="stat-value">${compliantFunds === totalFunds ? 'All Clear' : 'Action Required'}</div>
                </div>
            </div>

            <div class="compliance-grid">
                ${cards || '<div class="empty-state"><div class="title">No funds configured for compliance monitoring</div></div>'}
            </div>
        `;
    } catch (err) {
        main.innerHTML = `<div class="empty-state"><div class="title">Error</div><div class="subtitle">${err.message}</div></div>`;
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    navigate('dashboard');
});
