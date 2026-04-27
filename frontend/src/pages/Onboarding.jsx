import { useState, useEffect } from 'react'
import { supabase } from '../lib/supabase'
import { db } from '../lib/api'

async function signOut() {
  await supabase.auth.signOut()
}

const STEPS = ['Company basics', 'What you pursue', 'Capabilities', 'Exclusions']

function readDraft(userId) {
  try {
    return JSON.parse(localStorage.getItem(`govscroll_onboarding_${userId}`) || 'null')
  } catch { return null }
}

const SET_ASIDES = [
  { value: 'small_business', label: 'Small Business' },
  { value: '8a', label: '8(a)' },
  { value: 'sdvosb', label: 'SDVOSB' },
  { value: 'wosb', label: 'WOSB' },
  { value: 'hubzone', label: 'HUBZone' },
]

export default function Onboarding({ user, company, onComplete }) {
  const draftKey = `govscroll_onboarding_${user?.id}`

  const [step, setStep] = useState((company?.onboarding_step || 1) - 1)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [currentCompany, setCurrentCompany] = useState(company)

  // All form state is initialized from localStorage draft first, then company prop.
  // This survives iOS Safari tab eviction and any other page reload mid-onboarding.
  const [companyNameInput, setCompanyNameInput] = useState(() => {
    const d = readDraft(user?.id); return d?.companyNameInput ?? company?.name ?? ''
  })
  const [contractMin, setContractMin] = useState(() => {
    const d = readDraft(user?.id); return d?.contractMin ?? (company?.contract_min != null ? String(company.contract_min) : '')
  })
  const [contractMax, setContractMax] = useState(() => {
    const d = readDraft(user?.id); return d?.contractMax ?? (company?.contract_max != null ? String(company.contract_max) : '')
  })
  const [primeSubPref, setPrimeSubPref] = useState(() => {
    const d = readDraft(user?.id); return d?.primeSubPref ?? company?.prime_sub_preference ?? 'both'
  })
  const [clearance, setClearance] = useState(() => {
    const d = readDraft(user?.id); return d?.clearance ?? company?.clearance_level ?? 'none'
  })
  const [selectedSetAsides, setSelectedSetAsides] = useState(() => {
    const d = readDraft(user?.id); return d?.selectedSetAsides ?? company?.set_aside_eligibility ?? []
  })
  const [naicsInput, setNaicsInput] = useState('')
  const [naicsList, setNaicsList] = useState(() => {
    const d = readDraft(user?.id); return d?.naicsList ?? []
  })
  const [capStatement, setCapStatement] = useState(() => {
    const d = readDraft(user?.id); return d?.capStatement ?? company?.capabilities_statement ?? ''
  })
  const [keywordInput, setKeywordInput] = useState('')
  const [keywords, setKeywords] = useState(() => {
    const d = readDraft(user?.id); return d?.keywords ?? []
  })
  const [excludeKeywordInput, setExcludeKeywordInput] = useState('')
  const [excludeKeywords, setExcludeKeywords] = useState(() => {
    const d = readDraft(user?.id); return d?.excludeKeywords ?? []
  })

  // Persist entire draft to localStorage on every field change
  useEffect(() => {
    try {
      localStorage.setItem(draftKey, JSON.stringify({
        companyNameInput, contractMin, contractMax, primeSubPref, clearance,
        selectedSetAsides, naicsList, capStatement, keywords, excludeKeywords,
      }))
    } catch {}
  }, [companyNameInput, contractMin, contractMax, primeSubPref, clearance,
      selectedSetAsides, naicsList, capStatement, keywords, excludeKeywords])

  function toggleSetAside(val) {
    setSelectedSetAsides(prev =>
      prev.includes(val) ? prev.filter(v => v !== val) : [...prev, val]
    )
  }

  function addNaics() {
    const code = naicsInput.trim().replace(/\D/g, '')
    if (code && !naicsList.find(n => n.code === code)) {
      setNaicsList(prev => [...prev, { code, description: '' }])
      setNaicsInput('')
    }
  }

  function addKeyword(isExclusion = false) {
    const kw = (isExclusion ? excludeKeywordInput : keywordInput).trim().toLowerCase()
    if (!kw) return
    if (isExclusion) {
      setExcludeKeywords(prev => [...prev, kw])
      setExcludeKeywordInput('')
    } else {
      setKeywords(prev => [...prev, kw])
      setKeywordInput('')
    }
  }

  async function saveStep(nextStep) {
    setSaving(true)
    setError('')
    try {
      // If no company yet, register first via backend
      let companyId = currentCompany?.id
      if (!companyId) {
        if (!companyNameInput.trim()) throw new Error('Please enter your company name.')
        const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:5001'
        const res = await fetch(`${apiUrl}/api/v2/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: user.id, email: user.email, company_name: companyNameInput.trim() }),
        })
        const result = await res.json()
        if (!res.ok) throw new Error(result.error || 'Failed to create company')
        setCurrentCompany(result.company)
        companyId = result.company.id
      }
      if (step === 0) {
        const min = contractMin !== '' ? Number(contractMin) : null
        const max = contractMax !== '' ? Number(contractMax) : null
        if (contractMin !== '' && isNaN(min)) throw new Error('Minimum contract value must be a number.')
        if (contractMax !== '' && isNaN(max)) throw new Error('Maximum contract value must be a number.')
        if (min !== null && max !== null && min > max) throw new Error('Minimum cannot be greater than maximum.')
        const { error: e } = await db.saveCompany(companyId, {
          contract_min: min,
          contract_max: max,
          prime_sub_preference: primeSubPref,
          clearance_level: clearance,
          set_aside_eligibility: selectedSetAsides,
          onboarding_step: 2,
        })
        if (e) throw new Error(e.message)
      } else if (step === 1) {
        const { error: e1 } = await db.saveNaics(companyId, naicsList)
        if (e1) throw new Error(e1.message)
        const { error: e2 } = await db.saveCompany(companyId, { onboarding_step: 3 })
        if (e2) throw new Error(e2.message)
      } else if (step === 2) {
        // Keywords saved in step 3 alongside exclusions — only save capStatement here
        const { error: e } = await db.saveCompany(companyId, { capabilities_statement: capStatement, onboarding_step: 4 })
        if (e) throw new Error(e.message)
      } else if (step === 3) {
        // Save all keywords (regular + exclusion) in one shot to avoid double-save race
        const allKeywords = [
          ...keywords.map(k => ({ keyword: k, is_exclusion: false })),
          ...excludeKeywords.map(k => ({ keyword: k, is_exclusion: true })),
        ]
        const { error: e1 } = await db.saveKeywords(companyId, allKeywords)
        if (e1) throw new Error(e1.message)
        const { error: e2 } = await db.saveCompany(companyId, { onboarding_complete: true, onboarding_step: 4 })
        if (e2) throw new Error(e2.message)
        localStorage.removeItem(draftKey)
        onComplete()
        return
      }
      setStep(nextStep)
    } catch (err) {
      console.error('Save error:', err)
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const progress = ((step + 1) / STEPS.length) * 100

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        {/* Header */}
        <div style={styles.header}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <h2 style={{ color: 'var(--text)', fontSize: '20px' }}>Set up your profile</h2>
              <p style={{ color: 'var(--muted)', fontSize: '13px', marginTop: '4px' }}>
                Step {step + 1} of {STEPS.length} — {STEPS[step]}
              </p>
            </div>
            <button onClick={signOut} style={{ background: 'none', color: 'var(--muted)', fontSize: '12px', padding: '4px 0' }}>
              Sign out
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div style={styles.progressTrack}>
          <div style={{ ...styles.progressFill, width: `${progress}%` }} />
        </div>

        {/* Step content */}
        <div style={styles.body}>
          {step === 0 && (
            <div style={styles.fields}>
              {!currentCompany?.id && (
                <Row label="Company name">
                  <input
                    type="text"
                    placeholder="Acme Defense Solutions"
                    value={companyNameInput}
                    onChange={e => setCompanyNameInput(e.target.value)}
                    required
                  />
                </Row>
              )}
              <Row label="Contract size range">
                <div style={styles.rangeRow}>
                  <input type="number" placeholder="Min $" value={contractMin} onChange={e => setContractMin(e.target.value)} />
                  <span style={{ color: 'var(--muted)' }}>—</span>
                  <input type="number" placeholder="Max $" value={contractMax} onChange={e => setContractMax(e.target.value)} />
                </div>
              </Row>
              <Row label="You typically pursue as">
                <SegmentedControl
                  options={[{ value: 'prime', label: 'Prime' }, { value: 'sub', label: 'Sub' }, { value: 'both', label: 'Both' }]}
                  value={primeSubPref}
                  onChange={setPrimeSubPref}
                />
              </Row>
              <Row label="Clearance level">
                <select value={clearance} onChange={e => setClearance(e.target.value)}>
                  <option value="none">None</option>
                  <option value="secret">Secret</option>
                  <option value="ts">Top Secret</option>
                  <option value="tssci">TS/SCI</option>
                </select>
              </Row>
              <Row label="Set-aside eligibility (select all that apply)">
                <div style={styles.chips}>
                  {SET_ASIDES.map(sa => (
                    <Chip
                      key={sa.value}
                      label={sa.label}
                      active={selectedSetAsides.includes(sa.value)}
                      onClick={() => toggleSetAside(sa.value)}
                    />
                  ))}
                </div>
              </Row>
            </div>
          )}

          {step === 1 && (
            <div style={styles.fields}>
              <Row label="NAICS codes you work under">
                <div style={styles.inputRow}>
                  <input
                    placeholder="e.g. 541511"
                    value={naicsInput}
                    onChange={e => setNaicsInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addNaics())}
                  />
                  <button style={styles.addBtn} onClick={addNaics}>Add</button>
                </div>
                <div style={styles.chips}>
                  {naicsList.map(n => (
                    <Chip key={n.code} label={n.code} active onRemove={() => setNaicsList(prev => prev.filter(x => x.code !== n.code))} />
                  ))}
                </div>
                {naicsList.length === 0 && (
                  <p style={{ color: 'var(--muted)', fontSize: '13px' }}>Add your primary and secondary NAICS codes. The first one added is treated as primary.</p>
                )}
              </Row>
            </div>
          )}

          {step === 2 && (
            <div style={styles.fields}>
              <Row label="Paste your capabilities statement (optional)">
                <textarea
                  rows={5}
                  placeholder="Paste your capabilities statement here. We'll extract keywords automatically..."
                  value={capStatement}
                  onChange={e => setCapStatement(e.target.value)}
                  style={{ resize: 'vertical' }}
                />
              </Row>
              <Row label="Capability keywords (terms you want to match)">
                <div style={styles.inputRow}>
                  <input
                    placeholder="e.g. cloud migration"
                    value={keywordInput}
                    onChange={e => setKeywordInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addKeyword(false))}
                  />
                  <button style={styles.addBtn} onClick={() => addKeyword(false)}>Add</button>
                </div>
                <div style={styles.chips}>
                  {keywords.map(k => (
                    <Chip key={k} label={k} active onRemove={() => setKeywords(prev => prev.filter(x => x !== k))} />
                  ))}
                </div>
              </Row>
            </div>
          )}

          {step === 3 && (
            <div style={styles.fields}>
              <p style={{ color: 'var(--muted)', fontSize: '13px', lineHeight: '1.6' }}>
                Exclusion keywords downrank opportunities matching these terms. Use this for work you cannot or will not pursue.
              </p>
              <Row label="Exclusion keywords">
                <div style={styles.inputRow}>
                  <input
                    placeholder="e.g. janitorial, construction"
                    value={excludeKeywordInput}
                    onChange={e => setExcludeKeywordInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addKeyword(true))}
                  />
                  <button style={styles.addBtn} onClick={() => addKeyword(true)}>Add</button>
                </div>
                <div style={styles.chips}>
                  {excludeKeywords.map(k => (
                    <Chip key={k} label={k} active color="var(--red)" onRemove={() => setExcludeKeywords(prev => prev.filter(x => x !== k))} />
                  ))}
                </div>
              </Row>
            </div>
          )}
        </div>

        {/* Error display */}
        {error && (
          <div style={{ padding: '0 28px 8px', color: 'var(--red)', fontSize: '13px' }}>
            {error}
          </div>
        )}

        {/* Navigation */}
        <div style={styles.footer}>
          {step > 0 && (
            <button style={styles.backBtn} onClick={() => setStep(s => s - 1)}>Back</button>
          )}
          <button
            style={{ ...styles.nextBtn, marginLeft: step === 0 ? 'auto' : 0 }}
            onClick={() => saveStep(step + 1)}
            disabled={saving}
          >
            {saving ? 'Saving...' : step === STEPS.length - 1 ? 'Launch my feed →' : 'Continue →'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Small reusable components

function Row({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <label style={{ fontSize: '13px', color: 'var(--muted)', fontWeight: '500' }}>{label}</label>
      {children}
    </div>
  )
}

function SegmentedControl({ options, value, onChange }) {
  return (
    <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: '10px', padding: '3px' }}>
      {options.map(o => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          style={{
            flex: 1,
            padding: '8px',
            borderRadius: '8px',
            fontSize: '13px',
            fontWeight: '500',
            background: value === o.value ? 'var(--primary)' : 'transparent',
            color: value === o.value ? '#fff' : 'var(--muted)',
            transition: 'all 0.15s',
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Chip({ label, active, onClick, onRemove, color }) {
  return (
    <span
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        padding: '5px 10px',
        borderRadius: '20px',
        fontSize: '12px',
        fontWeight: '500',
        background: active ? (color || 'var(--primary)') + '22' : 'var(--surface2)',
        color: active ? (color || 'var(--primary)') : 'var(--muted)',
        border: `1px solid ${active ? (color || 'var(--primary)') + '44' : 'var(--border)'}`,
        cursor: onClick || onRemove ? 'pointer' : 'default',
      }}
    >
      {label}
      {onRemove && (
        <span onClick={e => { e.stopPropagation(); onRemove() }} style={{ marginLeft: '2px', opacity: 0.7 }}>×</span>
      )}
    </span>
  )
}

const styles = {
  page: {
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '24px',
  },
  card: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    width: '100%',
    maxWidth: '520px',
    overflow: 'hidden',
  },
  header: { padding: '28px 28px 16px' },
  progressTrack: { height: '3px', background: 'var(--surface2)' },
  progressFill: { height: '100%', background: 'var(--primary)', transition: 'width 0.3s' },
  body: { padding: '24px 28px' },
  fields: { display: 'flex', flexDirection: 'column', gap: '20px' },
  footer: { padding: '16px 28px 24px', display: 'flex', gap: '10px' },
  rangeRow: { display: 'flex', gap: '8px', alignItems: 'center' },
  inputRow: { display: 'flex', gap: '8px' },
  chips: { display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '4px' },
  addBtn: {
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    color: 'var(--text)',
    borderRadius: '10px',
    padding: '0 16px',
    fontSize: '13px',
    whiteSpace: 'nowrap',
  },
  backBtn: {
    background: 'var(--surface2)',
    color: 'var(--text)',
    borderRadius: '10px',
    padding: '12px 20px',
    fontSize: '14px',
    fontWeight: '500',
  },
  nextBtn: {
    background: 'var(--primary)',
    color: '#fff',
    borderRadius: '10px',
    padding: '12px 24px',
    fontSize: '14px',
    fontWeight: '600',
    flex: 1,
  },
}
