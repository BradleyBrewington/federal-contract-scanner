/* Federal Contract Scanner — Dashboard App */

const API = '';
let currentView = 'opportunities';
let allOpportunities = [];
let activeCategoryTab = 'all'; // 'all' | 'engineering' | 'general'

// --- API calls ---
async function api(path, opts = {}) {
    const res = await fetch(API + path, {
        ...opts,
        headers: { 'Content-Type': 'application/json', ...opts.headers },
    });
    if (res.status === 401) { window.location.href = '/'; return null; }
    return res;
}

async function fetchOpportunities(params = {}) {
    const qs = new URLSearchParams(params).toString();
    const res = await api(`/api/opportunities?${qs}`);
    if (!res) return [];
    const data = await res.json();
    allOpportunities = data.opportunities || [];
    return allOpportunities;
}

async function fetchStats() {
    const res = await api('/api/stats');
    if (!res) return {};
    return res.json();
}

async function fetchArchive() {
    const res = await api('/api/archive');
    if (!res) return [];
    const data = await res.json();
    return data.archive || [];
}

async function fetchTeaming(naics) {
    const res = await api(`/api/teaming/${naics}`);
    if (!res) return [];
    const data = await res.json();
    return data.leads || [];
}

async function fetchScoringConfig() {
    const res = await api('/api/config/scoring');
    if (!res) return null;
    return res.json();
}

async function saveScoringConfig(data) {
    return api('/api/config/scoring', { method: 'PUT', body: JSON.stringify(data) });
}

async function rescoreAll() {
    return api('/api/rescore', { method: 'POST' });
}

async function updateOpportunity(id, data) {
    return api(`/api/opportunities/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}

async function archiveOpportunity(id) {
    return api(`/api/opportunities/${id}/archive`, { method: 'POST' });
}

async function triggerScan() {
    return api('/api/scan', { method: 'POST' });
}

// --- Score badge ---
function scoreBadge(score, status) {
    if (status === 'SKIP') {
        return `<span class="score-badge score-skip">SKIP</span>`;
    }
    const cls = score >= 65 ? 'score-review' : score >= 45 ? 'score-maybe' : 'score-low';
    return `<span class="score-badge ${cls}">${score}</span>`;
}

function goNogoBadge(val) {
    if (!val) return '';
    const cls = val === 'GO' ? 'tag tag-go' : 'tag tag-nogo';
    return `<span class="${cls}">${esc(val)}</span>`;
}

function categoryBadge(category) {
    if (!category || category === 'uncategorized') return '<span class="tag" style="background:rgba(107,114,128,0.15);color:#9ca3af;border-color:#374151">uncategorized</span>';
    const isEng = category === 'engineering';
    const bg = isEng ? 'rgba(59,130,246,0.15)' : 'rgba(245,158,11,0.15)';
    const color = isEng ? '#60a5fa' : '#fbbf24';
    const border = isEng ? '#1d4ed8' : '#92400e';
    return `<span class="tag" style="background:${bg};color:${color};border-color:${border}">${esc(category)}</span>`;
}

// Count opportunities by category for tab badges
function _categoryCounts(opps) {
    return {
        all: opps.length,
        engineering: opps.filter(o => o.category === 'engineering').length,
        general: opps.filter(o => o.category === 'general').length,
    };
}

function renderCategoryTabs(opps) {
    const counts = _categoryCounts(opps);
    const tabs = [
        { key: 'all', label: 'All' },
        { key: 'engineering', label: 'Engineering' },
        { key: 'general', label: 'General' },
    ];
    return '<div class="category-tabs" style="display:flex;gap:8px;margin-bottom:12px;">' +
        tabs.map(t => {
            const active = activeCategoryTab === t.key;
            const isEng = t.key === 'engineering';
            const isGen = t.key === 'general';
            const accentColor = isEng ? '#3b82f6' : isGen ? '#f59e0b' : 'var(--accent)';
            const border = active ? `2px solid ${accentColor}` : '2px solid transparent';
            const bg = active ? `rgba(${isEng ? '59,130,246' : isGen ? '245,158,11' : '99,102,241'},0.12)` : 'transparent';
            return `<button onclick="setCategoryTab('${t.key}')" style="padding:5px 14px;border-radius:6px;border:${border};background:${bg};color:var(--text);cursor:pointer;font-size:13px;">
                ${esc(t.label)} <span style="color:var(--text-dim);font-size:11px;">(${counts[t.key]})</span>
            </button>`;
        }).join('') + '</div>';
}

function setCategoryTab(tab) {
    activeCategoryTab = tab;
    // Update URL hash for deep linking
    const base = '#/';
    if (tab === 'all') {
        history.replaceState(null, '', base + 'opportunities');
    } else {
        history.replaceState(null, '', base + tab);
    }
    // Re-render current filter
    filterOpps();
}

function _applyCategoryFilter(opps) {
    if (activeCategoryTab === 'all') return opps;
    return opps.filter(o => o.category === activeCategoryTab);
}

// --- Rendering ---
function renderOpportunities(opps) {
    if (!opps.length) return '<div class="spinner">No opportunities found</div>';
    return '<div class="opp-list">' + opps.map(o => {
        const summary = o.brief_summary || o.ai_summary || truncate(o.description, 180);
        const info = o.extracted_info || {};
        const deadline = o.response_deadline ? formatDeadline(o.response_deadline) : null;
        const isSkip = o.status === 'SKIP';

        // SKIP banner
        const skipBanner = isSkip && o.disqualifier_reason
            ? `<div style="margin-top:6px;padding:4px 8px;background:rgba(239,68,68,0.1);border-left:3px solid var(--red);border-radius:2px;font-size:0.8rem;color:var(--red);">&#9888; ${esc(o.disqualifier_reason)}</div>`
            : '';

        // Warning count badge
        const warnCount = (o.score_breakdown && o.score_breakdown.warnings || []).length;
        const warnBadge = warnCount > 0
            ? `<span class="tag tag-warn">&#9888; ${warnCount} warning${warnCount > 1 ? 's' : ''}</span>`
            : '';

        return `
        <div class="opp-card${isSkip ? ' opp-skip' : ''}" onclick="showDetail('${o.id}')">
            <div class="header">
                <div style="flex:1">
                    <div class="title" style="${isSkip ? 'opacity:0.6' : ''}">${esc(o.title)}</div>
                    <div class="meta">${esc(o.agency)} &bull; ${esc(o.source)}${deadline ? ` &bull; <span style="color:${deadline.urgent ? 'var(--orange)' : 'var(--text-dim)'}">Due: ${deadline.text}</span>` : ''}</div>
                    ${skipBanner}
                    ${!isSkip && summary ? `<div class="summary">${esc(summary)}</div>` : ''}
                    <div class="tags">
                        ${categoryBadge(o.category)}
                        ${o.set_aside ? `<span class="tag">${esc(o.set_aside)}</span>` : ''}
                        ${o.naics_code ? `<span class="tag">NAICS ${esc(o.naics_code)}</span>` : ''}
                        ${o.status && o.status !== 'new' && o.status !== 'SKIP' ? `<span class="tag tag-status">${esc(o.status)}</span>` : ''}
                        ${goNogoBadge(o.ai_go_no_go)}
                        ${warnBadge}
                        ${o.ai_summary && !o.ai_go_no_go ? `<span class="tag tag-ai">AI analyzed</span>` : ''}
                    </div>
                </div>
                ${scoreBadge(o.score, o.status)}
            </div>
        </div>`;
    }).join('') + '</div>';
}

function truncate(str, len) {
    if (!str) return '';
    if (str.length <= len) return str;
    return str.substring(0, len).replace(/\s+\S*$/, '') + '...';
}

function formatDeadline(dateStr) {
    if (!dateStr) return null;
    try {
        const d = new Date(dateStr);
        if (isNaN(d)) return { text: dateStr, urgent: false };
        const now = new Date();
        const diff = Math.ceil((d - now) / (1000 * 60 * 60 * 24));
        const text = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        return { text: diff <= 7 ? `${text} (${diff}d)` : text, urgent: diff <= 7 && diff >= 0 };
    } catch {
        return { text: dateStr, urgent: false };
    }
}

function renderDetail(o) {
    const info = o.extracted_info || {};
    const summary = o.brief_summary || truncate(o.description, 300);
    const isSkip = o.status === 'SKIP';
    const warnings = (o.score_breakdown && o.score_breakdown.warnings) || [];

    // SKIP disqualifier banner
    const skipBanner = isSkip
        ? `<div style="padding:12px 16px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);border-radius:8px;margin-bottom:16px;">
               <strong style="color:var(--red);">&#9888; AUTO-SKIPPED</strong>
               <span style="color:var(--red);margin-left:8px;">${esc(o.disqualifier_reason || 'Hard disqualifier triggered')}</span>
           </div>`
        : '';

    // Warning badges
    const warnBanner = warnings.length
        ? `<div style="margin-bottom:12px">${warnings.map(w => `<span class="tag tag-warn">&#9888; ${esc(w)}</span>`).join(' ')}</div>`
        : '';

    // AI GO/NO-GO section
    let aiSection = '';
    if (o.ai_go_no_go) {
        const gngColor = o.ai_go_no_go === 'GO' ? 'var(--green)' : 'var(--red)';
        const confPct = Math.round((o.ai_confidence || 0) * 100);
        const teamingNote = o.ai_teaming_needed
            ? `<span class="tag tag-warn" style="margin-left:8px;">Teaming needed</span>` : '';
        aiSection = `
        <div class="ai-section">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
                <h4 style="margin:0">Claude AI Assessment</h4>
                <span style="font-size:1.1rem;font-weight:700;color:${gngColor};">${esc(o.ai_go_no_go)}</span>
                <span style="color:var(--text-dim);font-size:0.85rem;">${confPct}% confidence</span>
                ${teamingNote}
                ${o.ai_effort_hours ? `<span style="color:var(--text-dim);font-size:0.85rem;">~${o.ai_effort_hours}h effort</span>` : ''}
            </div>
            ${o.ai_summary ? `<p style="margin-bottom:8px"><strong>Summary:</strong> ${esc(o.ai_summary)}</p>` : ''}
            ${o.ai_feasibility ? `<p style="margin-bottom:8px"><strong>Feasibility:</strong> <span style="color:${gngColor}">${esc(o.ai_feasibility)}</span></p>` : ''}
            ${o.ai_requirements ? `<div style="margin-bottom:8px"><strong>Requirements:</strong><pre style="margin-top:4px;white-space:pre-wrap;font-size:0.85rem;color:var(--text-dim)">${esc(o.ai_requirements)}</pre></div>` : ''}
            ${o.ai_red_flags ? `<div style="margin-bottom:8px"><strong style="color:var(--red)">Dealbreakers:</strong><pre style="margin-top:4px;white-space:pre-wrap;font-size:0.85rem;color:var(--red)">${esc(o.ai_red_flags)}</pre></div>` : ''}
            ${o.ai_warnings_list && o.ai_warnings_list.length ? `<div style="margin-bottom:8px"><strong style="color:var(--yellow)">Warnings:</strong> ${o.ai_warnings_list.map(w => `<span class="tag tag-warn">${esc(w)}</span>`).join(' ')}</div>` : ''}
            ${o.ai_recommendation ? `<p><strong>Recommended Action:</strong> ${esc(o.ai_recommendation)}</p>` : ''}
        </div>`;
    } else if (o.ai_summary) {
        // Legacy format
        aiSection = `
        <div class="ai-section">
            <h4>Claude AI Analysis</h4>
            <p><strong>Summary:</strong> ${esc(o.ai_summary)}</p>
            ${o.ai_requirements ? `<p><strong>Requirements:</strong> ${esc(o.ai_requirements)}</p>` : ''}
            ${o.ai_feasibility ? `<p><strong>Feasibility:</strong> ${esc(o.ai_feasibility)}</p>` : ''}
            ${o.ai_red_flags ? `<p><strong>Red Flags:</strong> ${esc(o.ai_red_flags)}</p>` : ''}
            ${o.ai_recommendation ? `<p><strong>Recommendation:</strong> ${esc(o.ai_recommendation)}</p>` : ''}
        </div>`;
    }

    return `
        <button class="btn-sm secondary" onclick="loadView('opportunities')">&larr; Back</button>
        <div class="opp-detail" style="margin-top:12px">
            ${skipBanner}
            <div class="header" style="display:flex;justify-content:space-between;align-items:center;">
                <h2>${esc(o.title)}</h2>
                ${scoreBadge(o.score, o.status)}
            </div>

            ${warnBanner}

            ${summary && !isSkip ? `
            <div class="quick-summary">
                <strong>Quick Summary:</strong> ${esc(summary)}
            </div>` : ''}

            <div class="detail-grid">
                <div class="field"><div class="label">Agency</div><div class="value">${esc(o.agency)}</div></div>
                <div class="field"><div class="label">Source</div><div class="value">${esc(o.source)}</div></div>
                <div class="field"><div class="label">Category</div><div class="value">${categoryBadge(o.category)}</div></div>
                <div class="field"><div class="label">NAICS</div><div class="value">${esc(o.naics_code || 'N/A')}</div></div>
                <div class="field"><div class="label">Set-Aside</div><div class="value">${esc(o.set_aside || 'None')}</div></div>
                <div class="field"><div class="label">Posted</div><div class="value">${esc(o.posted_date || 'N/A')}</div></div>
                <div class="field"><div class="label">Deadline</div><div class="value">${esc(o.response_deadline || 'N/A')}</div></div>
                <div class="field"><div class="label">Contact</div><div class="value">${esc(o.contact || 'N/A')}</div></div>
                <div class="field"><div class="label">Location</div><div class="value">${esc(o.place_of_performance || 'N/A')}</div></div>
                ${info.amounts && info.amounts.length ? `<div class="field"><div class="label">Amounts Mentioned</div><div class="value">${info.amounts.map(a => esc(a)).join(', ')}</div></div>` : ''}
            </div>

            <div class="field"><div class="label">URL</div><div class="value"><a href="${esc(o.url)}" target="_blank" style="color:var(--accent)">${esc(o.url)}</a></div></div>

            ${aiSection}

            <div style="margin-top:12px;">
                <div class="label">Full Description</div>
                <p style="margin-top:4px;color:var(--text-dim);white-space:pre-wrap;">${esc(o.description || 'No description available')}</p>
            </div>

            ${o.flags && o.flags.length ? `<div style="margin-top:12px"><strong>Flags:</strong> ${o.flags.map(f => `<span class="tag">${esc(f)}</span>`).join(' ')}</div>` : ''}

            <div style="margin-top:16px;display:flex;align-items:center;gap:8px;">
                <label>Status:</label>
                <select class="status-select" onchange="changeStatus('${o.id}', this.value)">
                    ${['new','reviewing','bid','no-bid','won','lost'].map(s => `<option value="${s}" ${o.status===s?'selected':''}>${s}</option>`).join('')}
                </select>
                <button class="btn-sm secondary" onclick="doArchive('${o.id}')">Archive</button>
            </div>

            <div style="margin-top:12px;">
                <label>Notes:</label>
                <textarea class="notes-area" id="notes-${o.id}" onblur="saveNotes('${o.id}')">${esc(o.notes || '')}</textarea>
            </div>

            <div style="margin-top:12px">
                <h4>Score Breakdown</h4>
                ${renderBreakdown(o.score_breakdown)}
            </div>
        </div>
    `;
}

function renderBreakdown(bd) {
    if (!bd || !Object.keys(bd).length) return '<p style="color:var(--text-dim)">No breakdown available</p>';

    const CAT_DEFS = [
        { key: 'entry_barrier',     label: 'Entry Barrier', max: 40, color: '#3b82f6' },
        { key: 'scope_simplicity',  label: 'Scope',         max: 25, color: '#22c55e' },
        { key: 'competition_level', label: 'Competition',   max: 20, color: '#f97316' },
        { key: 'skill_match',       label: 'Skills',        max: 15, color: '#a855f7' },
    ];

    // Determine if new format
    const isNewFormat = CAT_DEFS.some(c => bd[c.key] && typeof bd[c.key] === 'object' && 'points' in bd[c.key]);

    if (!isNewFormat) {
        // Legacy flat format
        return '<div style="margin-top:8px">' + Object.entries(bd).map(([k, v]) => {
            if (k === 'rationale' || k === 'disqualifiers' || k === 'warnings') return '';
            const pts = (v && v.points) || 0;
            const color = pts > 0 ? 'var(--green)' : pts < 0 ? 'var(--red)' : 'var(--text-dim)';
            return `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)">
                <span>${esc(k.replace(/_/g, ' '))}</span>
                <span style="color:${color};font-weight:600">${pts > 0 ? '+' : ''}${pts}</span>
            </div>`;
        }).join('') + '</div>';
    }

    // New 4-category format
    // Visual bar
    let barHtml = '<div style="display:flex;gap:2px;height:20px;border-radius:4px;overflow:hidden;margin-bottom:6px;">';
    for (const cat of CAT_DEFS) {
        const catData = bd[cat.key] || {};
        const pts = Math.max(0, catData.points || 0);
        const filledPct = (pts / 100 * 100).toFixed(1);
        const emptyPct  = ((cat.max - pts) / 100 * 100).toFixed(1);
        if (pts > 0) {
            barHtml += `<div style="width:${filledPct}%;background:${cat.color};display:flex;align-items:center;justify-content:center;" title="${cat.label}: ${pts}/${cat.max}">
                <span style="font-size:9px;color:white;white-space:nowrap;">${pts}</span></div>`;
        }
        if (parseFloat(emptyPct) > 0) {
            barHtml += `<div style="width:${emptyPct}%;background:${cat.color}33;" title="${cat.label}: ${pts}/${cat.max}"></div>`;
        }
    }
    barHtml += '</div>';

    // Legend
    const legendHtml = '<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:10px;font-size:11px;">' +
        CAT_DEFS.map(cat => {
            const pts = (bd[cat.key] || {}).points || 0;
            return `<span style="display:flex;align-items:center;gap:3px;">
                <span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${cat.color}"></span>
                ${esc(cat.label)}: <strong>${pts}/${cat.max}</strong></span>`;
        }).join('') + '</div>';

    // Per-category details
    let detailsHtml = '';
    for (const cat of CAT_DEFS) {
        const catData = bd[cat.key] || {};
        const details = (catData.details || []).filter(d => d.points !== 0);
        if (!details.length) continue;
        detailsHtml += `<div style="margin-bottom:8px;">
            <div style="font-size:10px;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:3px;border-bottom:1px solid var(--border);padding-bottom:2px;">
                ${esc(cat.label)} &mdash; ${catData.points}/${cat.max}
            </div>`;
        for (const d of details) {
            const dp = d.points;
            const color = dp > 0 ? 'var(--green)' : 'var(--red)';
            const matchText = d.matches && d.matches.length ? ` <span style="color:var(--text-dim)">(${d.matches.join(', ')})</span>` : '';
            detailsHtml += `<div style="display:flex;justify-content:space-between;padding:2px 0 2px 6px;border-left:2px solid ${color}33;margin-bottom:1px">
                <span style="font-size:11px">${esc(d.label)}${matchText}</span>
                <span style="font-size:11px;font-weight:600;color:${color};margin-left:8px">${dp > 0 ? '+' : ''}${dp}</span>
            </div>`;
        }
        detailsHtml += '</div>';
    }

    // Rationale
    const rationaleHtml = bd.rationale
        ? `<div style="margin-top:8px;padding:8px;background:var(--bg);border-radius:4px;font-size:11px;color:var(--text-dim);font-style:italic;">${esc(bd.rationale)}</div>`
        : '';

    return barHtml + legendHtml + detailsHtml + rationaleHtml;
}

function renderStats(stats) {
    return `
        <h2 style="margin-bottom:16px">Statistics</h2>
        <div class="stats-bar">
            <div class="stat-card"><div class="label">Total</div><div class="value">${stats.total || 0}</div></div>
            <div class="stat-card"><div class="label">REVIEW (65+)</div><div class="value" style="color:var(--green)">${stats.high_score_count || 0}</div></div>
            <div class="stat-card"><div class="label">Avg Score</div><div class="value">${stats.avg_score || 0}</div></div>
        </div>
        <div class="detail-grid" style="margin-top:20px">
            <div>
                <h3>By Source</h3>
                ${Object.entries(stats.by_source || {}).map(([k,v]) => `<div style="padding:4px 0">${esc(k)}: <strong>${v}</strong></div>`).join('')}
            </div>
            <div>
                <h3>By Status</h3>
                ${Object.entries(stats.by_status || {}).map(([k,v]) => {
                    const color = k==='REVIEW' ? 'var(--green)' : k==='SKIP' ? 'var(--red)' : k==='MAYBE' ? 'var(--yellow)' : 'var(--text)';
                    return `<div style="padding:4px 0">${esc(k)}: <strong style="color:${color}">${v}</strong></div>`;
                }).join('')}
            </div>
        </div>
    `;
}

function renderTeaming() {
    return `
        <h2 style="margin-bottom:16px">Teaming Leads</h2>
        <div class="toolbar">
            <input type="text" id="teamingNaics" placeholder="Enter NAICS code (e.g. 541512)" value="541512">
            <button class="btn-sm" onclick="loadTeaming()">Search</button>
        </div>
        <div id="teamingResults"><div class="spinner">Enter a NAICS code and click Search</div></div>
    `;
}

function renderTeamingResults(leads) {
    if (!leads.length) return '<div class="spinner">No teaming leads found</div>';
    return leads.map(l => `
        <div class="teaming-card">
            <div class="name">${esc(l.name)}</div>
            <div class="info">
                Awards: $${(l.amount || 0).toLocaleString()} &bull; Count: ${l.count || 0}
                ${l.state ? ` &bull; ${esc(l.state)}` : ''}
                ${l.cage_code ? ` &bull; CAGE: ${esc(l.cage_code)}` : ''}
            </div>
        </div>
    `).join('');
}

function renderArchive(items) {
    if (!items.length) return '<h2>Archive</h2><div class="spinner">No archived opportunities</div>';
    return '<h2 style="margin-bottom:16px">Archive</h2>' + renderOpportunities(items);
}

function renderSettings(config) {
    const rules = config.scoring_rules?.rules || [];
    const keywords = config.keywords || {};
    const naics = config.naics_codes || [];
    const setAsides = config.set_asides || [];

    return `
        <h2 style="margin-bottom:16px">Scoring Settings</h2>
        <p style="color:var(--text-dim);margin-bottom:20px;">Adjust how opportunities are scored. Higher scores = better matches for your profile.</p>

        <div class="settings-section">
            <h3>Target NAICS Codes</h3>
            <textarea class="keywords-input" id="naicsCodes">${naics.join(', ')}</textarea>
        </div>

        <div class="settings-actions">
            <button class="btn-sm" onclick="saveSettings()">Save Changes</button>
            <button class="btn-sm secondary" onclick="saveAndRescore()">Save & Re-score All</button>
            <span id="saveStatus" style="margin-left:12px;color:var(--green);display:none;">Saved!</span>
        </div>

        <div class="settings-section" style="margin-top:30px;padding-top:20px;border-top:1px solid var(--border);">
            <h3>How Scoring Works</h3>
            <div class="scoring-explainer">
                <p>Each opportunity is scored 0–100 across 4 categories, with hard disqualifiers checked first:</p>
                <ul>
                    <li><strong>Entry Barrier (max 40 pts):</strong> SBIR/STTR, eligible set-aside, no past performance req., contract value, facility requirements</li>
                    <li><strong>Scope Simplicity (max 25 pts):</strong> Study/prototype deliverable, single-person scope, bounded deliverables, short PoP</li>
                    <li><strong>Competition Level (max 20 pts):</strong> SBIR pool, SB set-aside, not a recompete, niche topic</li>
                    <li><strong>Skill Match (max 15 pts):</strong> Tier 1 direct match (mechatronics, 3D printing, PCB…), Tier 2 adjacent (data analysis, tech writing…)</li>
                </ul>
                <p><strong>Status thresholds:</strong> REVIEW (65+) &bull; MAYBE (45–64) &bull; LOW (&lt;45) &bull; SKIP (hard disqualifier)</p>
                <p><strong>Hard disqualifiers → SKIP:</strong> Security clearance, ineligible set-aside (SDVOSB/8a/HUBZone/WOSB), ITAR, value &gt;$2M, classified work, weapons, OEM lock-in, 5+ FTE required, specialized facility</p>
                <p><strong>AI enrichment:</strong> Opportunities scoring 50+ get a Claude GO/NO-GO assessment (skips SKIP-status opps).</p>
            </div>
        </div>
    `;
}

let currentScoringConfig = null;

async function saveSettings() {
    const config = gatherSettingsFromUI();
    const res = await saveScoringConfig(config);
    if (res && res.ok) {
        document.getElementById('saveStatus').style.display = 'inline';
        setTimeout(() => document.getElementById('saveStatus').style.display = 'none', 2000);
    } else {
        alert('Failed to save settings');
    }
}

async function saveAndRescore() {
    await saveSettings();
    const status = document.getElementById('saveStatus');
    status.textContent = 'Re-scoring...';
    status.style.display = 'inline';
    const res = await rescoreAll();
    if (res && res.ok) {
        const data = await res.json();
        status.textContent = `Re-scored ${data.count} opportunities!`;
        setTimeout(() => status.style.display = 'none', 3000);
    } else {
        status.textContent = 'Re-score failed';
        status.style.color = 'var(--red)';
    }
}

function gatherSettingsFromUI() {
    const config = {};
    config.naics_codes = parseList(document.getElementById('naicsCodes')?.value);
    return config;
}

function parseList(str) {
    if (!str) return [];
    return str.split(',').map(s => s.trim()).filter(s => s.length > 0);
}

// --- Actions ---
async function showDetail(id) {
    const opp = allOpportunities.find(o => o.id === id);
    if (opp) document.getElementById('mainContent').innerHTML = renderDetail(opp);
}

async function changeStatus(id, status) {
    await updateOpportunity(id, { status });
    const opp = allOpportunities.find(o => o.id === id);
    if (opp) opp.status = status;
}

async function saveNotes(id) {
    const el = document.getElementById(`notes-${id}`);
    if (el) await updateOpportunity(id, { notes: el.value });
}

async function doArchive(id) {
    if (!confirm('Archive this opportunity?')) return;
    await archiveOpportunity(id);
    loadView('opportunities');
}

async function doScan() {
    await triggerScan();
    alert('Scan started in background. Refresh in a moment.');
}

async function loadTeaming() {
    const naics = document.getElementById('teamingNaics').value;
    if (!naics) return;
    document.getElementById('teamingResults').innerHTML = '<div class="spinner">Searching...</div>';
    const leads = await fetchTeaming(naics);
    document.getElementById('teamingResults').innerHTML = renderTeamingResults(leads);
}

// --- View loader ---
async function loadView(view) {
    currentView = view;
    const mc = document.getElementById('mainContent');
    mc.innerHTML = '<div class="spinner">Loading...</div>';

    document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === view));

    if (view === 'opportunities') {
        const opps = await fetchOpportunities();
        // Restore active tab from URL hash
        const hash = window.location.hash;
        if (hash === '#/engineering') activeCategoryTab = 'engineering';
        else if (hash === '#/general') activeCategoryTab = 'general';
        else activeCategoryTab = 'all';

        mc.innerHTML = `
            <div id="categoryTabsContainer">${renderCategoryTabs(opps)}</div>
            <div class="toolbar">
                <input type="text" id="searchInput" placeholder="Search opportunities..." oninput="filterOpps()">
                <select id="sourceFilter" onchange="filterOpps()">
                    <option value="">All Sources</option>
                    <option value="SAM.gov">SAM.gov</option>
                    <option value="SBIR.gov">SBIR.gov</option>
                    <option value="Grants.gov">Grants.gov</option>
                    <option value="SubNet">SubNet</option>
                </select>
                <select id="statusFilter" onchange="filterOpps()">
                    <option value="">All Status</option>
                    <option value="REVIEW">REVIEW (65+)</option>
                    <option value="MAYBE">MAYBE (45–64)</option>
                    <option value="LOW">LOW (&lt;45)</option>
                    <option value="SKIP">SKIP (disqualified)</option>
                    <option value="reviewing">reviewing</option>
                    <option value="bid">bid</option>
                    <option value="no-bid">no-bid</option>
                </select>
                <select id="sortSelect" onchange="filterOpps()">
                    <option value="score">Sort: Score</option>
                    <option value="date">Sort: Date</option>
                    <option value="deadline">Sort: Deadline</option>
                    <option value="title">Sort: Title</option>
                </select>
                <button class="btn-sm" onclick="doScan()">Run Scan</button>
                <a href="/api/export/csv" class="btn-sm secondary" style="text-decoration:none;text-align:center">Export CSV</a>
            </div>
            <div id="oppList">${renderOpportunities(_applyCategoryFilter(opps))}</div>
        `;
    } else if (view === 'teaming') {
        mc.innerHTML = renderTeaming();
    } else if (view === 'archive') {
        const items = await fetchArchive();
        mc.innerHTML = renderArchive(items);
    } else if (view === 'stats') {
        const stats = await fetchStats();
        mc.innerHTML = renderStats(stats);
    } else if (view === 'settings') {
        currentScoringConfig = await fetchScoringConfig();
        mc.innerHTML = renderSettings(currentScoringConfig);
    }
}

async function filterOpps() {
    const params = {};
    const s    = document.getElementById('searchInput')?.value;
    const src  = document.getElementById('sourceFilter')?.value;
    const st   = document.getElementById('statusFilter')?.value;
    const sort = document.getElementById('sortSelect')?.value;
    if (s)    params.search = s;
    if (src)  params.source = src;
    if (st)   params.status = st;
    if (sort) params.sort   = sort;
    params.dir = 'desc';

    const opps = await fetchOpportunities(params);

    // Refresh tab counts + active state whenever filter changes
    const tabsContainer = document.getElementById('categoryTabsContainer');
    if (tabsContainer) tabsContainer.innerHTML = renderCategoryTabs(opps);

    document.getElementById('oppList').innerHTML = renderOpportunities(_applyCategoryFilter(opps));
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

// --- Init ---
document.querySelectorAll('.nav-item[data-view]').forEach(n =>
    n.addEventListener('click', () => loadView(n.dataset.view))
);
document.getElementById('logoutBtn').addEventListener('click', async () => {
    await api('/api/logout', { method: 'POST' });
    window.location.href = '/';
});

loadView('opportunities');
