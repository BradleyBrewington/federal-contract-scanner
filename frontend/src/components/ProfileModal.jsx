import { useState, useEffect, useCallback } from 'react'
import { api, db } from '../lib/api'

export default function ProfileModal({ company, onClose }) {
  const [loading, setLoading] = useState(true)
  const [naicsList, setNaicsList] = useState([])
  const [keywords, setKeywords] = useState([])
  const [contractMin, setContractMin] = useState('')
  const [contractMax, setContractMax] = useState('')
  const [capabilities, setCapabilities] = useState('')

  const [newNaics, setNewNaics] = useState('')
  const [newNaicsDesc, setNewNaicsDesc] = useState('')
  const [newKeyword, setNewKeyword] = useState('')
  const [newKeywordExclusion, setNewKeywordExclusion] = useState(false)

  const [analyzing, setAnalyzing] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [analyzeError, setAnalyzeError] = useState('')

  const [savingSize, setSavingSize] = useState(false)
  const [savingCaps, setSavingCaps] = useState(false)
  const [sizeSaved, setSizeSaved] = useState(false)
  const [capsSaved, setCapsSaved] = useState(false)

  useEffect(() => {
    // Pre-fill from company prop immediately (no network needed)
    setContractMin(company.contract_min != null ? String(company.contract_min) : '')
    setContractMax(company.contract_max != null ? String(company.contract_max) : '')
    setCapabilities(company.capabilities_statement || '')

    // Fetch NAICS + keywords directly from Supabase (no Flask round trip)
    db.getCompanyProfile(company.id).then(data => {
      setNaicsList(data.naics || [])
      setKeywords(data.keywords || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [company.id])

  // ── NAICS ──────────────────────────────────────────────────────────────────

  const saveNaicsToDb = useCallback(async (updated) => {
    await db.saveNaics(company.id, updated.map(n => ({
      code: n.naics_code,
      description: n.description || '',
    })))
  }, [company.id])

  async function handleAddNaics() {
    const code = newNaics.trim().replace(/\D/g, '')
    if (code.length !== 6) return
    if (naicsList.find(n => n.naics_code === code)) { setNewNaics(''); return }
    const updated = [...naicsList, { naics_code: code, description: newNaicsDesc.trim(), is_primary: naicsList.length === 0 }]
    setNaicsList(updated)
    setNewNaics('')
    setNewNaicsDesc('')
    await saveNaicsToDb(updated)
  }

  async function handleRemoveNaics(code) {
    const updated = naicsList.filter(n => n.naics_code !== code)
    setNaicsList(updated)
    await saveNaicsToDb(updated)
  }

  async function handleAddSuggestion(s) {
    if (naicsList.find(n => n.naics_code === s.code)) {
      setSuggestions(prev => prev.filter(x => x.code !== s.code))
      return
    }
    const updated = [...naicsList, { naics_code: s.code, description: s.description, is_primary: false }]
    setNaicsList(updated)
    setSuggestions(prev => prev.filter(x => x.code !== s.code))
    await saveNaicsToDb(updated)
  }

  async function handleAddAllSuggestions() {
    const newOnes = suggestions.filter(s => !naicsList.find(n => n.naics_code === s.code))
    const updated = [...naicsList, ...newOnes.map(s => ({ naics_code: s.code, description: s.description, is_primary: false }))]
    setNaicsList(updated)
    setSuggestions([])
    await saveNaicsToDb(updated)
  }

  // ── Keywords ───────────────────────────────────────────────────────────────

  async function handleAddKeyword() {
    const kw = newKeyword.trim().toLowerCase()
    if (!kw || keywords.find(k => k.keyword === kw)) { setNewKeyword(''); return }
    const updated = [...keywords, { keyword: kw, is_exclusion: newKeywordExclusion }]
    setKeywords(updated)
    setNewKeyword('')
    await db.saveKeywords(company.id, updated)
  }

  async function handleRemoveKeyword(kw) {
    const updated = keywords.filter(k => k.keyword !== kw)
    setKeywords(updated)
    await db.saveKeywords(company.id, updated)
  }

  // ── Contract size ──────────────────────────────────────────────────────────

  async function handleSaveSize() {
    setSavingSize(true)
    await db.saveCompany(company.id, {
      contract_min: contractMin ? parseFloat(contractMin) : null,
      contract_max: contractMax ? parseFloat(contractMax) : null,
    })
    setSavingSize(false)
    setSizeSaved(true)
    setTimeout(() => setSizeSaved(false), 2000)
  }

  // ── Capabilities ───────────────────────────────────────────────────────────

  async function handleSaveCapabilities() {
    setSavingCaps(true)
    await db.saveCompany(company.id, { capabilities_statement: capabilities })
    setSavingCaps(false)
    setCapsSaved(true)
    setTimeout(() => setCapsSaved(false), 2000)
  }

  async function handleAnalyze() {
    if (!capabilities.trim()) return
    setAnalyzing(true)
    setSuggestions([])
    setAnalyzeError('')
    try {
      const result = await api.analyzeCapabilities(capabilities)
      setSuggestions(result.suggestions || [])
      if (!result.suggestions?.length) setAnalyzeError('No suggestions returned. Try adding more detail to your description.')
    } catch (err) {
      setAnalyzeError('Analysis failed. Check that the backend is running and the Anthropic API key is valid.')
    } finally {
      setAnalyzing(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const positiveKeywords = keywords.filter(k => !k.is_exclusion)
  const exclusionKeywords = keywords.filter(k => k.is_exclusion)

  return (
    <div style={s.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={s.sheet}>
        {/* Header */}
        <div style={s.header}>
          <span style={s.headerTitle}>Company Profile</span>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>

        {loading ? (
          <div style={s.loadingWrap}><div style={s.spinner} /></div>
        ) : (
          <div style={s.body}>

            {/* ── Contract Size ─────────────────────────────────────────── */}
            <Section title="Contract Size Target">
              <div style={s.row}>
                <div style={s.inputGroup}>
                  <label style={s.label}>Min ($)</label>
                  <input
                    style={s.input}
                    type="number"
                    placeholder="e.g. 100000"
                    value={contractMin}
                    onChange={e => setContractMin(e.target.value)}
                  />
                </div>
                <div style={s.inputGroup}>
                  <label style={s.label}>Max ($)</label>
                  <input
                    style={s.input}
                    type="number"
                    placeholder="e.g. 5000000"
                    value={contractMax}
                    onChange={e => setContractMax(e.target.value)}
                  />
                </div>
              </div>
              <SaveBtn onClick={handleSaveSize} saving={savingSize} saved={sizeSaved} />
            </Section>

            {/* ── NAICS Codes ───────────────────────────────────────────── */}
            <Section title="NAICS Codes">
              {naicsList.length === 0 && (
                <p style={s.empty}>No NAICS codes added yet.</p>
              )}
              <div style={s.tagList}>
                {naicsList.map(n => (
                  <div key={n.naics_code} style={s.naicsTag}>
                    <span style={s.naicsCode}>{n.naics_code}</span>
                    {n.description && <span style={s.naicsDesc}>{n.description}</span>}
                    <button style={s.removeBtn} onClick={() => handleRemoveNaics(n.naics_code)}>✕</button>
                  </div>
                ))}
              </div>
              <div style={s.addRow}>
                <input
                  style={{ ...s.input, width: '110px' }}
                  placeholder="6-digit code"
                  value={newNaics}
                  maxLength={6}
                  onChange={e => setNewNaics(e.target.value.replace(/\D/g, ''))}
                  onKeyDown={e => e.key === 'Enter' && handleAddNaics()}
                />
                <input
                  style={{ ...s.input, flex: 1 }}
                  placeholder="Description (optional)"
                  value={newNaicsDesc}
                  onChange={e => setNewNaicsDesc(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddNaics()}
                />
                <button style={s.addBtn} onClick={handleAddNaics}>Add</button>
              </div>
            </Section>

            {/* ── Keywords ─────────────────────────────────────────────── */}
            <Section title="Keywords">
              {positiveKeywords.length > 0 && (
                <>
                  <p style={s.subLabel}>Target</p>
                  <div style={s.tagList}>
                    {positiveKeywords.map(k => (
                      <div key={k.keyword} style={s.kwTag}>
                        <span>{k.keyword}</span>
                        <button style={s.removeBtn} onClick={() => handleRemoveKeyword(k.keyword)}>✕</button>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {exclusionKeywords.length > 0 && (
                <>
                  <p style={{ ...s.subLabel, color: '#ef4444', marginTop: '10px' }}>Exclusions</p>
                  <div style={s.tagList}>
                    {exclusionKeywords.map(k => (
                      <div key={k.keyword} style={{ ...s.kwTag, borderColor: '#ef444433', color: '#ef4444' }}>
                        <span>{k.keyword}</span>
                        <button style={s.removeBtn} onClick={() => handleRemoveKeyword(k.keyword)}>✕</button>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {keywords.length === 0 && <p style={s.empty}>No keywords added yet.</p>}
              <div style={s.addRow}>
                <input
                  style={{ ...s.input, flex: 1 }}
                  placeholder="Add keyword"
                  value={newKeyword}
                  onChange={e => setNewKeyword(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddKeyword()}
                />
                <label style={s.toggleLabel}>
                  <input
                    type="checkbox"
                    checked={newKeywordExclusion}
                    onChange={e => setNewKeywordExclusion(e.target.checked)}
                    style={{ marginRight: '5px' }}
                  />
                  Exclude
                </label>
                <button style={s.addBtn} onClick={handleAddKeyword}>Add</button>
              </div>
            </Section>

            {/* ── Capabilities Statement ────────────────────────────────── */}
            <Section title="Capabilities Statement">
              <p style={s.helpText}>
                Paste your company's capabilities statement. Use "Analyze" to get AI-suggested NAICS codes — these will be added to your profile and improve your feed.
              </p>
              <textarea
                style={s.textarea}
                placeholder="Describe your company's core capabilities, past performance areas, technical expertise..."
                value={capabilities}
                onChange={e => setCapabilities(e.target.value)}
                rows={6}
              />
              <div style={s.capsActions}>
                <SaveBtn onClick={handleSaveCapabilities} saving={savingCaps} saved={capsSaved} label="Save" />
                <button
                  style={{ ...s.analyzeBtn, opacity: analyzing || !capabilities.trim() ? 0.5 : 1 }}
                  onClick={handleAnalyze}
                  disabled={analyzing || !capabilities.trim()}
                >
                  {analyzing ? 'Analyzing...' : 'Analyze with AI'}
                </button>
              </div>

              {analyzeError && <p style={s.errorText}>{analyzeError}</p>}

              {suggestions.length > 0 && (
                <div style={s.suggestionsBox}>
                  <div style={s.suggestionsHeader}>
                    <span style={s.suggestionsTitle}>Suggested NAICS Codes</span>
                    <button style={s.addAllBtn} onClick={handleAddAllSuggestions}>+ Add All</button>
                  </div>
                  {suggestions.map(s2 => (
                    <div key={s2.code} style={s.suggestionRow}>
                      <div style={s.suggestionInfo}>
                        <span style={s.naicsCode}>{s2.code}</span>
                        <span style={s.naicsDesc}>{s2.description}</span>
                        {s2.reason && <span style={s.suggestionReason}>{s2.reason}</span>}
                      </div>
                      <button
                        style={{
                          ...s.addSuggBtn,
                          ...(naicsList.find(n => n.naics_code === s2.code) ? s.addSuggBtnAdded : {}),
                        }}
                        onClick={() => handleAddSuggestion(s2)}
                        disabled={!!naicsList.find(n => n.naics_code === s2.code)}
                      >
                        {naicsList.find(n => n.naics_code === s2.code) ? 'Added' : '+ Add'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </Section>

          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div style={sec.wrap}>
      <h3 style={sec.title}>{title}</h3>
      {children}
    </div>
  )
}

function SaveBtn({ onClick, saving, saved, label = 'Save' }) {
  return (
    <button
      style={{ ...s.saveBtn, ...(saved ? s.saveBtnSaved : {}) }}
      onClick={onClick}
      disabled={saving}
    >
      {saving ? 'Saving...' : saved ? 'Saved ✓' : label}
    </button>
  )
}

const sec = {
  wrap: {
    borderBottom: '1px solid var(--border)',
    paddingBottom: '20px',
    marginBottom: '4px',
  },
  title: {
    fontSize: '12px',
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: 'var(--muted)',
    marginBottom: '12px',
  },
}

const s = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.6)',
    zIndex: 200,
    display: 'flex',
    alignItems: 'flex-end',
  },
  sheet: {
    width: '100%',
    maxHeight: '82svh',
    background: 'var(--surface)',
    borderRadius: '16px 16px 0 0',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 20px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },
  headerTitle: { fontSize: '16px', fontWeight: '700', color: 'var(--text)' },
  closeBtn: {
    background: 'none', border: 'none',
    color: 'var(--muted)', fontSize: '18px',
    padding: '4px 8px', cursor: 'pointer',
    minWidth: '44px', minHeight: '44px',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  loadingWrap: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    padding: '48px',
  },
  spinner: {
    width: '28px', height: '28px',
    border: '3px solid var(--border)',
    borderTop: '3px solid var(--primary)',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  body: {
    overflowY: 'auto',
    flex: 1,
    padding: '20px',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
  },
  row: { display: 'flex', gap: '12px' },
  inputGroup: { display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 },
  label: { fontSize: '11px', color: 'var(--muted)', fontWeight: '600' },
  input: {
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '8px 10px',
    color: 'var(--text)',
    fontSize: '13px',
    outline: 'none',
    minHeight: '36px',
  },
  textarea: {
    width: '100%',
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '10px',
    color: 'var(--text)',
    fontSize: '13px',
    outline: 'none',
    resize: 'vertical',
    fontFamily: 'inherit',
    lineHeight: '1.5',
    boxSizing: 'border-box',
  },
  addRow: { display: 'flex', gap: '8px', alignItems: 'center', marginTop: '10px' },
  addBtn: {
    background: 'var(--primary)',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    padding: '8px 14px',
    fontSize: '13px',
    fontWeight: '600',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  saveBtn: {
    background: 'var(--surface2)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '8px 16px',
    fontSize: '13px',
    fontWeight: '600',
    cursor: 'pointer',
    transition: 'background 0.2s',
  },
  saveBtnSaved: {
    background: '#22c55e22',
    color: '#22c55e',
    borderColor: '#22c55e44',
  },
  tagList: { display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '4px' },
  naicsTag: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '6px 10px',
  },
  naicsCode: { fontSize: '13px', fontWeight: '700', color: 'var(--primary)' },
  naicsDesc: { fontSize: '12px', color: 'var(--muted)' },
  kwTag: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: '20px',
    padding: '4px 10px',
    fontSize: '13px',
    color: 'var(--text)',
  },
  removeBtn: {
    background: 'none', border: 'none',
    color: 'var(--muted)', fontSize: '11px',
    cursor: 'pointer', padding: '2px',
    lineHeight: 1,
  },
  subLabel: {
    fontSize: '11px', fontWeight: '600',
    color: 'var(--muted)', marginBottom: '6px',
    textTransform: 'uppercase', letterSpacing: '0.05em',
  },
  toggleLabel: {
    fontSize: '12px', color: 'var(--muted)',
    display: 'flex', alignItems: 'center',
    whiteSpace: 'nowrap', cursor: 'pointer',
  },
  empty: { fontSize: '13px', color: 'var(--muted)', marginBottom: '8px' },
  helpText: {
    fontSize: '12px', color: 'var(--muted)',
    lineHeight: '1.5', marginBottom: '10px',
  },
  capsActions: { display: 'flex', gap: '10px', marginTop: '10px' },
  analyzeBtn: {
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    padding: '8px 16px',
    fontSize: '13px',
    fontWeight: '600',
    cursor: 'pointer',
    transition: 'opacity 0.15s',
  },
  errorText: { fontSize: '12px', color: '#ef4444', marginTop: '8px' },
  suggestionsBox: {
    marginTop: '16px',
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: '10px',
    overflow: 'hidden',
  },
  suggestionsHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '10px 14px',
    borderBottom: '1px solid var(--border)',
  },
  suggestionsTitle: { fontSize: '12px', fontWeight: '700', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em' },
  addAllBtn: {
    background: 'var(--primary)',
    color: '#fff', border: 'none',
    borderRadius: '6px',
    padding: '4px 10px',
    fontSize: '12px', fontWeight: '600',
    cursor: 'pointer',
  },
  suggestionRow: {
    display: 'flex', alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
    padding: '10px 14px',
    borderBottom: '1px solid var(--border)',
  },
  suggestionInfo: { display: 'flex', flexDirection: 'column', gap: '2px', flex: 1, minWidth: 0 },
  suggestionReason: { fontSize: '11px', color: 'var(--muted)', lineHeight: '1.4' },
  addSuggBtn: {
    background: 'var(--primary)',
    color: '#fff', border: 'none',
    borderRadius: '6px',
    padding: '5px 12px',
    fontSize: '12px', fontWeight: '600',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    flexShrink: 0,
  },
  addSuggBtnAdded: {
    background: 'var(--surface)',
    color: 'var(--muted)',
    cursor: 'default',
  },
}
