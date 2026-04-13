/**
 * WalletHound dashboard JavaScript
 * Handles scan actions, table rendering, and Chart.js visualizations.
 */

// ── State ──────────────────────────────────────────────────────────────────
let allResults = [];
let tierChart = null;
let profitChart = null;

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtUSD(val) {
    const sign = val >= 0 ? '+' : '';
    return `${sign}$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(val) {
    const sign = val >= 0 ? '+' : '';
    return `${sign}${val.toFixed(1)}%`;
}

function profitClass(val) {
    return val >= 0 ? 'text-success' : 'text-danger';
}

function tierBadges(tiers) {
    if (!tiers || !tiers.length) return '<span class="text-muted">—</span>';
    const map = {
        big_winner: '<span class="tier-badge big-winner">🏆 Big</span>',
        consistent_winner: '<span class="tier-badge consistent">🎯 Consistent</span>',
        compounder: '<span class="tier-badge compounder">📈 Compounder</span>',
    };
    return tiers.map(t => map[t] || t).join(' ');
}

// ── Table rendering ────────────────────────────────────────────────────────

function renderResults(data) {
    const tbody = document.getElementById('resultsBody');
    if (!tbody) return;

    if (!data.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-5">No wallets matched.</td></tr>';
        return;
    }

    tbody.innerHTML = data.map((r, i) => `
        <tr>
            <td>${i + 1}</td>
            <td>
                <a href="/wallet/${r.wallet}" class="text-warning text-decoration-none">
                    ${r.display_name || r.wallet.slice(0, 12) + '…'}
                </a>
            </td>
            <td>${tierBadges(r.tiers)}</td>
            <td class="text-end ${profitClass(r.total_profit_usdc)} fw-bold">${fmtUSD(r.total_profit_usdc)}</td>
            <td class="text-end">${r.win_rate_pct ? fmtPct(r.win_rate_pct) : '—'}</td>
            <td class="text-end">${r.consistency_score ? r.consistency_score.toFixed(1) : '—'}</td>
            <td class="text-end ${profitClass(r.organic_growth_pct)}">${fmtPct(r.organic_growth_pct)}</td>
            <td class="text-end">${r.total_deposits_usdc ? '$' + r.total_deposits_usdc.toLocaleString(undefined, {maximumFractionDigits: 0}) : '—'}</td>
            <td class="text-end">${r.big_win_count || '—'}</td>
        </tr>
    `).join('');
}

// ── Charts ─────────────────────────────────────────────────────────────────

function updateCharts(data) {
    // Tier distribution (doughnut)
    const tierCounts = { big_winner: 0, consistent_winner: 0, compounder: 0 };
    data.forEach(r => (r.tiers || []).forEach(t => { if (t in tierCounts) tierCounts[t]++; }));

    const tierCtx = document.getElementById('tierChart');
    if (tierCtx) {
        if (tierChart) tierChart.destroy();
        tierChart = new Chart(tierCtx, {
            type: 'doughnut',
            data: {
                labels: ['🏆 Big Winners', '🎯 Consistent', '📈 Compounders'],
                datasets: [{
                    data: [tierCounts.big_winner, tierCounts.consistent_winner, tierCounts.compounder],
                    backgroundColor: ['#198754', '#0dcaf0', '#0d6efd'],
                    borderWidth: 0,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#adb5bd' } },
                },
            },
        });
    }

    // Top wallets by profit (bar)
    const top10 = data.slice(0, 10);
    const profitCtx = document.getElementById('profitChart');
    if (profitCtx) {
        if (profitChart) profitChart.destroy();
        profitChart = new Chart(profitCtx, {
            type: 'bar',
            data: {
                labels: top10.map(r => r.display_name || r.wallet.slice(0, 10) + '…'),
                datasets: [{
                    label: 'Profit (USDC)',
                    data: top10.map(r => r.total_profit_usdc),
                    backgroundColor: top10.map(r => r.total_profit_usdc >= 0 ? '#198754' : '#dc3545'),
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    x: { ticks: { color: '#adb5bd' }, grid: { color: '#21262d' } },
                    y: { ticks: { color: '#adb5bd' }, grid: { display: false } },
                },
            },
        });
    }
}

// ── Summary cards ──────────────────────────────────────────────────────────

function updateSummary(data) {
    const el = (id) => document.getElementById(id);
    if (el('totalTracked')) el('totalTracked').textContent = data.length;

    let bigW = 0, consW = 0, compW = 0;
    data.forEach(r => {
        (r.tiers || []).forEach(t => {
            if (t === 'big_winner') bigW++;
            if (t === 'consistent_winner') consW++;
            if (t === 'compounder') compW++;
        });
    });
    if (el('bigWinnerCount')) el('bigWinnerCount').textContent = bigW;
    if (el('consistentCount')) el('consistentCount').textContent = consW;
    if (el('compounderCount')) el('compounderCount').textContent = compW;
}

// ── Scan action ────────────────────────────────────────────────────────────

async function runScan() {
    const topSelect = document.getElementById('topNSelect');
    if (!topSelect) return;
    const top = topSelect.value;
    const tbody = document.getElementById('resultsBody');
    const spinner = document.getElementById('loadingSpinner');
    const loadText = document.getElementById('loadingText');

    if (tbody) {
        tbody.innerHTML = `
            <tr><td colspan="9" class="text-center py-5">
                <div class="spinner-border text-warning"></div>
                <p class="mt-2 text-muted">Scanning top-${top} wallets… this may take a moment.</p>
            </td></tr>`;
    }

    try {
        const resp = await fetch(`/api/hound/scan?top=${top}`);
        allResults = await resp.json();
        renderResults(allResults);
        updateSummary(allResults);
        updateCharts(allResults);
    } catch (err) {
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-center text-danger py-5">Error: ${err.message}</td></tr>`;
        }
    }
}

// ── Tier filter buttons ────────────────────────────────────────────────────

function setupTierFilters() {
    document.querySelectorAll('.tier-filter').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tier-filter').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tier = btn.dataset.tier;
            if (tier === 'all') {
                renderResults(allResults);
            } else {
                renderResults(allResults.filter(r => (r.tiers || []).includes(tier)));
            }
        });
    });
}

// ── Wallet search ──────────────────────────────────────────────────────────

function setupWalletSearch() {
    const form = document.getElementById('walletSearchForm');
    if (form) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = document.getElementById('walletSearchInput');
            const addr = (input.value || '').trim();
            if (addr) {
                window.location.href = `/wallet/${addr}`;
            }
        });
    }
}

// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    setupTierFilters();
    setupWalletSearch();

    const scanBtn = document.getElementById('scanBtn');
    if (scanBtn) {
        scanBtn.addEventListener('click', runScan);
    }
});
