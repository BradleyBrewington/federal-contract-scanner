import { useEffect, useState } from 'react'
import { api } from '../lib/api'

const NOTICE_LABELS = {
  solicitation: 'Solicitation',
  presolicitation: 'Pre-Solicitation',
  sources_sought: 'Sources Sought',
  award: 'Award Notice',
  combined: 'Combined Synopsis',
  modification: 'Modification',
  justification: 'Justification',
}

export default function DetailModal({ card, onClose, onPass, onSave }) {
  const [detail, setDetail] = useState(null)
  const [summary, setSummary] = useState(card.ai_summary)
  const [loadingDetail, setLoadingDetail] = useState(true)

  // Fetch full detail record
  useEffect(() => {
    api.getOpportunity(card.id)
      .then(data => setDetail(data))
      .catch(() => {})
      .finally(() => setLoadingDetail(false))
  }, [card.id])

  // Generate summary if missing
  useEffect(() => {
    if (!summary && card.id) {
      api.generateSummary(card.id)
        .then(res => setSummary(res.summary))
        .catch(() => {})
    }
  }, [card.id, summary])

  const o = detail || card
  const noticeLabel = NOTICE_LABELS[o.notice_type] || o.notice_type || 'Opportunity'
  const rawDesc = o.description || ''
  const descIsUrl = rawDesc.trim().startsWith('http')
  const displayDesc = descIsUrl ? '' : rawDesc

  // Close on backdrop click
  function handleBackdrop(e) {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div style={styles.backdrop} onClick={handleBackdrop}>
      <div style={styles.sheet}>
        {/* Handle bar */}
        <div style={styles.handle} />

        {/* Header */}
        <div style={styles.header}>
          <div style={styles.agencyRow}>
            <div style={styles.agencyIcon}>
              {(o.agency || 'U').charAt(0).toUpperCase()}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={styles.agencyName}>{o.agency || 'Unknown Agency'}</p>
              {o.sub_agency && <p style={styles.subAgency}>{o.sub_agency}</p>}
            </div>
            <button onClick={onClose} style={styles.closeBtn}>✕</button>
          </div>
          <h2 style={styles.title}>{o.title}</h2>
        </div>

        {/* Scrollable body */}
        <div style={styles.body}>
          {/* AI Summary */}
          {summary && (
            <Section label="AI Summary">
              <p style={styles.summaryText}>{summary}</p>
            </Section>
          )}

          {/* Key details grid */}
          <Section label="Details">
            <div style={styles.grid}>
              <Kv label="Notice type" value={noticeLabel} />
              {o.naics_code && <Kv label="NAICS" value={o.naics_code} />}
              {o.psc_code && <Kv label="PSC" value={o.psc_code} />}
              {o.solicitation_number && <Kv label="Solicitation #" value={o.solicitation_number} />}
              {(o.value_display || o.value_max) && (
                <Kv label="Est. value" value={o.value_display || `$${Number(o.value_max).toLocaleString()}`} />
              )}
              {o.set_aside_type && o.set_aside_type !== 'NONE' && (
                <Kv label="Set-aside" value={o.set_aside_type} />
              )}
              {(o.pop_city || o.pop_state) && (
                <Kv label="Place of performance" value={[o.pop_city, o.pop_state].filter(Boolean).join(', ')} />
              )}
              {o.response_deadline && (
                <Kv
                  label="Response deadline"
                  value={new Date(o.response_deadline).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                  highlight={o.days_left != null && o.days_left <= 7}
                />
              )}
              {o.posted_date && (
                <Kv
                  label="Posted"
                  value={new Date(o.posted_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                />
              )}
            </div>
          </Section>

          {/* Description */}
          {loadingDetail && !displayDesc && (
            <Section label="Description">
              <p style={styles.muted}>Loading...</p>
            </Section>
          )}
          {displayDesc && (
            <Section label="Description">
              <p style={styles.descText}>{displayDesc}</p>
            </Section>
          )}
          {!loadingDetail && !displayDesc && (
            <Section label="Description">
              <p style={styles.muted}>
                Full description available on SAM.gov.{' '}
                <a href={o.sam_url || `https://sam.gov/opp/${o.notice_id}/view`} target="_blank" rel="noreferrer" style={styles.link}>
                  View opportunity ↗
                </a>
              </p>
            </Section>
          )}

          {/* Attachments */}
          {o.attachments && o.attachments !== '[]' && (() => {
            try {
              const atts = JSON.parse(o.attachments)
              if (atts.length > 0) return (
                <Section label={`Attachments (${atts.length})`}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {atts.map((att, i) => (
                      <a key={i} href={att.url} target="_blank" rel="noreferrer" style={styles.attachment}>
                        📎 {att.filename || att.url}
                      </a>
                    ))}
                  </div>
                </Section>
              )
            } catch {}
            return null
          })()}

          {/* SAM.gov link */}
          <a
            href={o.sam_url || `https://sam.gov/opp/${o.notice_id}/view`}
            target="_blank"
            rel="noreferrer"
            style={styles.samBtn}
          >
            View full listing on SAM.gov ↗
          </a>
        </div>

        {/* Action buttons */}
        <div style={styles.footer}>
          <button style={styles.passBtn} onClick={onPass}>✕ Pass</button>
          <button style={styles.saveBtn} onClick={onSave}>✓ Save to pipeline</button>
        </div>
      </div>
    </div>
  )
}

function Section({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <p style={{ fontSize: '11px', fontWeight: '600', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </p>
      {children}
    </div>
  )
}

function Kv({ label, value, highlight }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      <p style={{ fontSize: '11px', color: 'var(--muted)' }}>{label}</p>
      <p style={{ fontSize: '13px', fontWeight: '500', color: highlight ? '#ef4444' : 'var(--text)' }}>{value}</p>
    </div>
  )
}

const styles = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.6)',
    zIndex: 100,
    display: 'flex',
    alignItems: 'flex-end',
    justifyContent: 'center',
  },
  sheet: {
    background: 'var(--surface)',
    borderRadius: '20px 20px 0 0',
    width: '100%',
    maxWidth: '520px',
    maxHeight: '88vh',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  handle: {
    width: '36px',
    height: '4px',
    background: 'var(--border)',
    borderRadius: '2px',
    margin: '12px auto 0',
    flexShrink: 0,
  },
  header: {
    padding: '16px 20px 12px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },
  agencyRow: { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' },
  agencyIcon: {
    width: '36px',
    height: '36px',
    borderRadius: '8px',
    background: 'var(--primary)',
    color: '#fff',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: '700',
    fontSize: '15px',
    flexShrink: 0,
  },
  agencyName: { fontSize: '13px', fontWeight: '600', color: 'var(--text)' },
  subAgency: { fontSize: '11px', color: 'var(--muted)', marginTop: '1px' },
  closeBtn: {
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: '50%',
    width: '28px',
    height: '28px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '12px',
    color: 'var(--muted)',
    cursor: 'pointer',
    flexShrink: 0,
  },
  title: {
    fontSize: '16px',
    fontWeight: '600',
    color: 'var(--text)',
    lineHeight: '1.4',
  },
  body: {
    overflowY: 'auto',
    padding: '20px',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
    flex: 1,
  },
  summaryText: {
    fontSize: '14px',
    color: 'var(--text)',
    lineHeight: '1.6',
    background: 'var(--primary)11',
    border: '1px solid var(--primary)33',
    borderRadius: '10px',
    padding: '12px',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '12px',
  },
  descText: {
    fontSize: '13px',
    color: 'var(--muted)',
    lineHeight: '1.7',
    whiteSpace: 'pre-wrap',
  },
  muted: { fontSize: '13px', color: 'var(--muted)' },
  link: { color: 'var(--primary)', fontWeight: '500' },
  attachment: {
    fontSize: '12px',
    color: 'var(--primary)',
    textDecoration: 'none',
    padding: '6px 10px',
    background: 'var(--surface2)',
    borderRadius: '8px',
    border: '1px solid var(--border)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  samBtn: {
    display: 'block',
    textAlign: 'center',
    padding: '12px',
    background: 'var(--surface2)',
    border: '1px solid var(--border)',
    borderRadius: '10px',
    fontSize: '13px',
    fontWeight: '500',
    color: 'var(--primary)',
    textDecoration: 'none',
  },
  footer: {
    padding: '12px 20px 20px',
    display: 'flex',
    gap: '10px',
    borderTop: '1px solid var(--border)',
    flexShrink: 0,
  },
  passBtn: {
    flex: 1,
    padding: '12px',
    borderRadius: '10px',
    background: '#ef444422',
    color: '#ef4444',
    border: '1px solid #ef444444',
    fontWeight: '600',
    fontSize: '14px',
  },
  saveBtn: {
    flex: 2,
    padding: '12px',
    borderRadius: '10px',
    background: 'var(--primary)',
    color: '#fff',
    border: 'none',
    fontWeight: '600',
    fontSize: '14px',
  },
}
