import { useState } from 'react'

const NOTICE_LABELS = {
  solicitation: 'Solicitation',
  presolicitation: 'Pre-Solicitation',
  sources_sought: 'Sources Sought',
  combined: 'Combined Synopsis',
  special: 'Special Notice',
}

const SET_ASIDE_LABELS = {
  SBA: 'Small Business', '8AN': '8(a)', '8A': '8(a)',
  SDVOSBC: 'SDVOSB', SDVOSBR: 'SDVOSB',
  WOSB: 'WOSB', EDWOSB: 'EDWOSB',
  HZC: 'HUBZone', HZS: 'HUBZone',
}

function unwrapDescription(text) {
  if (!text) return text
  if (text.trimStart().startsWith('{')) {
    try {
      const obj = JSON.parse(text)
      return obj.description || obj.text || obj.content || null
    } catch {}
  }
  return text
}

export default function DetailModal({ card, onClose, onPass, onSave }) {
  const [copied, setCopied] = useState(false)

  function handleShare() {
    const url = card.sam_url || `https://sam.gov/opp/${card.notice_id}/view`
    if (navigator.share) {
      const agency = card.sub_agency || card.agency || ''
      navigator.share({
        title: card.title || 'Government Contract Opportunity',
        text: agency ? `${agency} — ${card.title}` : card.title,
        url,
      }).catch(() => {})
    } else {
      navigator.clipboard.writeText(url).then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }).catch(() => {})
    }
  }

  const scope = card.parsed_scope || {}
  const hasScope = scope.qty_display || scope.delivery_display || scope.nsn || scope.approved_source
  const descriptionText = unwrapDescription(card.description_text)
  const noticeLabel = NOTICE_LABELS[card.notice_type] || card.notice_type || 'Opportunity'
  const setAsideLabel = card.set_aside_type && card.set_aside_type !== 'NONE'
    ? (SET_ASIDE_LABELS[card.set_aside_type] || card.set_aside_type)
    : null

  const deadlineText = card.days_left === null || card.days_left === undefined
    ? 'No deadline posted'
    : card.days_left <= 0 ? 'Closing today'
    : card.days_left === 1 ? '1 day left'
    : `${card.days_left} days left`

  function handleBackdrop(e) {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div style={styles.backdrop} onClick={handleBackdrop}>
      <div style={styles.sheet}>
        <div style={styles.handle} />

        {/* Header */}
        <div style={styles.header}>
          <div style={styles.agencyRow}>
            <div style={styles.agencyIcon}>
              {(card.agency || 'U').charAt(0).toUpperCase()}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={styles.agencyName}>{card.sub_agency || card.agency || 'Unknown Agency'}</p>
              {card.sub_agency && <p style={styles.subAgency}>{card.agency}</p>}
            </div>
            <button onClick={handleShare} style={styles.shareBtn} title="Share">
              {copied ? '✓' : '↑'}
            </button>
            <button onClick={onClose} style={styles.closeBtn}>✕</button>
          </div>
          <h2 style={styles.title}>{card.title}</h2>
        </div>

        <div style={styles.body}>

          {/* Structured scope — DLA supply contracts */}
          {hasScope && (
            <Section label="Scope">
              <div style={styles.scopeGrid}>
                {scope.nsn && <ScopeRow label="NSN" value={scope.nsn} />}
                {scope.qty_display && (
                  <ScopeRow
                    label="Quantity"
                    value={scope.item_name ? `${scope.qty_display} — ${scope.item_name}` : scope.qty_display}
                  />
                )}
                {scope.delivery_display && <ScopeRow label="Delivery" value={scope.delivery_display} />}
                {scope.approved_source && <ScopeRow label="Approved source" value={scope.approved_source} />}
              </div>
            </Section>
          )}

          {/* Raw description text — when available as text (not a URL) */}
          {descriptionText && (
            <Section label="Description">
              {descriptionText.split('\n\n').map((para, i) => (
                <p key={i} style={styles.descText}>{para}</p>
              ))}
            </Section>
          )}

          {/* No description available */}
          {!descriptionText && !hasScope && (
            <div style={styles.noDesc}>
              <p style={styles.noDescText}>
                Full description available on SAM.gov.
              </p>
            </div>
          )}

          {/* Contract metadata */}
          <Section label="Contract Details">
            <div style={styles.grid}>
              <Kv label="Notice type" value={noticeLabel} />
              {card.naics_code && (
                <Kv label="NAICS" value={card.naics_code} sub={card.naics_title} />
              )}
              {card.psc_code && (
                <Kv label="PSC" value={card.psc_code} sub={card.psc_title} />
              )}
              {card.value_display && (
                <Kv label="Est. value" value={card.value_display} />
              )}
              {setAsideLabel && (
                <Kv label="Set-aside" value={setAsideLabel} />
              )}
              {card.location && (
                <Kv label="Place of performance" value={card.location} />
              )}
              {(card.days_left != null) && (
                <Kv
                  label="Deadline"
                  value={deadlineText}
                  sub={card.days_left_derived ? 'Extracted from description text' : null}
                  highlight={card.days_left <= 7}
                />
              )}
              {card.response_deadline && (
                <Kv
                  label="Due date"
                  value={new Date(card.response_deadline).toLocaleDateString('en-US', {
                    month: 'short', day: 'numeric', year: 'numeric',
                  })}
                />
              )}
              {card.posted_date && (
                <Kv
                  label="Posted"
                  value={new Date(card.posted_date).toLocaleDateString('en-US', {
                    month: 'short', day: 'numeric', year: 'numeric',
                  })}
                />
              )}
            </div>
          </Section>

          {/* Attachments */}
          {card.attachments && card.attachments !== '[]' && (() => {
            try {
              const atts = JSON.parse(card.attachments)
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

          <a
            href={card.sam_url || `https://sam.gov/opp/${card.notice_id}/view`}
            target="_blank"
            rel="noreferrer"
            style={styles.samBtn}
            onClick={e => e.stopPropagation()}
          >
            View full listing on SAM.gov ↗
          </a>
        </div>

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
      <p style={styles.sectionLabel}>{label}</p>
      {children}
    </div>
  )
}

function ScopeRow({ label, value }) {
  return (
    <div style={styles.scopeRow}>
      <span style={styles.scopeLabel}>{label}</span>
      <span style={styles.scopeValue}>{value}</span>
    </div>
  )
}

function Kv({ label, value, sub, highlight }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      <p style={styles.kvLabel}>{label}</p>
      <p style={{ ...styles.kvValue, color: highlight ? '#ef4444' : 'var(--text)' }}>{value}</p>
      {sub && <p style={styles.kvSub}>{sub}</p>}
    </div>
  )
}

const styles = {
  backdrop: {
    position: 'fixed', inset: 0,
    background: 'rgba(0,0,0,0.6)', zIndex: 100,
    display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
  },
  sheet: {
    background: 'var(--surface)',
    borderRadius: '20px 20px 0 0',
    width: '100%', maxWidth: '520px', maxHeight: '82svh',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  handle: {
    width: '36px', height: '4px', background: 'var(--border)',
    borderRadius: '2px', margin: '12px auto 0', flexShrink: 0,
  },
  header: {
    padding: '16px 20px 14px',
    borderBottom: '1px solid var(--border)', flexShrink: 0,
  },
  agencyRow: { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' },
  agencyIcon: {
    width: '36px', height: '36px', borderRadius: '8px',
    background: 'var(--primary)', color: '#fff',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontWeight: '700', fontSize: '15px', flexShrink: 0,
  },
  agencyName: { fontSize: '13px', fontWeight: '600', color: 'var(--text)' },
  subAgency: { fontSize: '11px', color: 'var(--muted)', marginTop: '1px' },
  shareBtn: {
    background: 'none', border: '1px solid var(--border)',
    borderRadius: '50%', width: '44px', height: '44px',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: '16px', color: 'var(--primary)', cursor: 'pointer', flexShrink: 0,
  },
  closeBtn: {
    background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: '50%', width: '44px', height: '44px',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: '14px', color: 'var(--muted)', cursor: 'pointer', flexShrink: 0,
  },
  title: { fontSize: '16px', fontWeight: '700', color: 'var(--text)', lineHeight: '1.4' },

  body: {
    overflowY: 'auto', padding: '20px',
    display: 'flex', flexDirection: 'column', gap: '20px', flex: 1,
  },

  // Structured scope
  scopeGrid: { display: 'flex', flexDirection: 'column', gap: '8px' },
  scopeRow: { display: 'flex', gap: '12px', alignItems: 'baseline' },
  scopeLabel: {
    fontSize: '11px', fontWeight: '600', color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '0.05em',
    whiteSpace: 'nowrap', minWidth: '90px',
  },
  scopeValue: { fontSize: '13px', color: 'var(--text)', fontWeight: '500' },

  // Description text — one <p> per paragraph, no pre-wrap needed
  descText: {
    fontSize: '13px', color: 'var(--text)', lineHeight: '1.7', marginBottom: '8px',
  },

  // No description fallback
  noDesc: {
    background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: '10px', padding: '16px',
  },
  noDescText: { fontSize: '13px', color: 'var(--muted)', lineHeight: '1.6' },

  // Metadata grid
  sectionLabel: {
    fontSize: '11px', fontWeight: '600', color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '0.06em',
  },
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' },
  kvLabel: { fontSize: '11px', color: 'var(--muted)' },
  kvValue: { fontSize: '13px', fontWeight: '500' },
  kvSub: { fontSize: '11px', color: 'var(--muted)', marginTop: '1px' },

  // Attachments
  attachment: {
    fontSize: '12px', color: 'var(--primary)', textDecoration: 'none',
    padding: '6px 10px', background: 'var(--surface2)',
    borderRadius: '8px', border: '1px solid var(--border)',
    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  },

  // SAM link
  samBtn: {
    display: 'block', textAlign: 'center', padding: '12px',
    background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: '10px', fontSize: '13px', fontWeight: '500',
    color: 'var(--primary)', textDecoration: 'none',
  },

  // Footer
  footer: {
    padding: '12px 20px 20px', display: 'flex', gap: '10px',
    borderTop: '1px solid var(--border)', flexShrink: 0,
  },
  passBtn: {
    flex: 1, padding: '12px', borderRadius: '10px',
    background: '#ef444422', color: '#ef4444',
    border: '1px solid #ef444444', fontWeight: '600', fontSize: '14px', cursor: 'pointer',
  },
  saveBtn: {
    flex: 2, padding: '12px', borderRadius: '10px',
    background: 'var(--primary)', color: '#fff',
    border: 'none', fontWeight: '600', fontSize: '14px', cursor: 'pointer',
  },
}
