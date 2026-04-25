import { useEffect, useState, useRef, useImperativeHandle, forwardRef } from 'react'
import { api } from '../lib/api'

const URGENCY_COLORS = { red: '#ef4444', yellow: '#eab308', green: '#22c55e', normal: '#8888a0' }

const NOTICE_TYPE_LABELS = {
  solicitation: 'Solicitation',
  presolicitation: 'Pre-Solicitation',
  sources_sought: 'Sources Sought',
  combined: 'Combined Synopsis',
  special: 'Special Notice',
}

const SET_ASIDE_LABELS = {
  SBA: 'Small Business',
  '8AN': '8(a)',
  '8A': '8(a)',
  SDVOSBC: 'SDVOSB',
  SDVOSBR: 'SDVOSB',
  WOSB: 'WOSB',
  EDWOSB: 'EDWOSB',
  HZC: 'HUBZone',
  HZS: 'HUBZone',
}

const FLAG_COLORS = {
  clearance: { bg: '#ef444415', fg: '#ef4444', border: '#ef444430' },
  cert:      { bg: '#f9731615', fg: '#f97316', border: '#f9731630' },
  vehicle:   { bg: '#06b6d415', fg: '#06b6d4', border: '#06b6d430' },
  sole:      { bg: '#eab30815', fg: '#eab308', border: '#eab30830' },
}
const FLAG_ICONS = { clearance: '🔒', cert: '📋', vehicle: '🔗', sole: '⚠️' }

const OpportunityCard = forwardRef(function OpportunityCard(
  { card, style, isTop, preload, onExpand, onSave },
  ref
) {
  const [aiScope, setAiScope] = useState(card.ai_summary)

  // Refs to the two overlay DOM nodes — mutated directly, zero re-renders
  const overlayRef = useRef(null)
  const stampRef   = useRef(null)

  // Expose setHint(dir) so Feed can drive feedback without touching React state
  useImperativeHandle(ref, () => ({
    setHint(dir) {
      const overlay = overlayRef.current
      const stamp   = stampRef.current
      if (!overlay || !stamp) return

      if (!dir) {
        overlay.style.opacity = '0'
        stamp.style.opacity   = '0'
        return
      }

      const isRight = dir === 'right'
      overlay.style.background = isRight ? 'rgba(34,197,94,0.13)' : 'rgba(239,68,68,0.13)'
      overlay.style.opacity    = '1'

      stamp.textContent        = isRight ? 'BID' : 'PASS'
      stamp.style.color        = isRight ? '#22c55e' : '#ef4444'
      stamp.style.borderColor  = isRight ? '#22c55e' : '#ef4444'
      stamp.style.transform    = `scale(1.05) rotate(${isRight ? 12 : -12}deg)`
      stamp.style.right        = isRight ? '20px' : 'auto'
      stamp.style.left         = isRight ? 'auto' : '20px'
      stamp.style.opacity      = '1'
    },
  }), [])

  // Pre-warm AI scope description for top 3 cards
  useEffect(() => {
    if (!aiScope && preload && card.id) {
      api.generateSummary(card.id)
        .then(res => { if (res?.summary) setAiScope(res.summary) })
        .catch(() => {})
    }
  }, [card.id, preload, aiScope])

  const urgencyColor = URGENCY_COLORS[card.urgency] || URGENCY_COLORS.normal
  const noticeLabel = NOTICE_TYPE_LABELS[card.notice_type] || card.notice_type || ''
  const setAsideLabel = card.set_aside_type && card.set_aside_type !== 'NONE'
    ? (SET_ASIDE_LABELS[card.set_aside_type] || card.set_aside_type)
    : null
  const flags = card.flags || []
  const scope = card.parsed_scope || {}

  // FIT row: set-aside + NAICS label
  const fitParts = []
  if (setAsideLabel) fitParts.push(setAsideLabel + ' Set-Aside')
  if (card.naics_code) {
    const naicsLabel = card.naics_title
      ? `NAICS ${card.naics_code} · ${card.naics_title}`
      : `NAICS ${card.naics_code}`
    fitParts.push(naicsLabel)
  } else if (card.industry_label) {
    fitParts.push(card.industry_label)
  }

  // SCOPE row: DLA qty+item, else AI description
  let scopeText = null
  if (scope.qty_display) {
    scopeText = scope.item_name
      ? `${scope.qty_display} ${scope.item_name}`
      : scope.qty_display
  } else if (aiScope) {
    scopeText = aiScope
  }

  // EFFORT row: delivery timeline + complexity
  const effortParts = []
  if (scope.delivery_display) effortParts.push(scope.delivery_display)
  if (card.complexity) effortParts.push(`${card.complexity} complexity`)

  // BUYER row: sub-agency + location
  const buyerName = card.sub_agency || card.agency || ''
  const buyerParts = [buyerName, card.location].filter(Boolean)

  // DEADLINE
  const deadlineText = card.days_left === null || card.days_left === undefined
    ? 'No deadline posted'
    : card.days_left <= 0
    ? 'Closing today'
    : card.days_left === 1
    ? '1 day left'
    : `${card.days_left} days left`

  return (
    <div style={{ ...styles.card, ...style }}>

      {/* Swipe color wash — driven via ref, never triggers re-render */}
      <div ref={overlayRef} style={styles.swipeOverlay} />

      {/* BID / PASS stamp — driven via ref */}
      <div ref={stampRef} style={styles.swipeStamp} />

      {/* Header: who is buying + value */}
      <div style={styles.agencyRow}>
        <div style={styles.agencyIcon}>
          {(card.agency || 'U').charAt(0).toUpperCase()}
        </div>
        <div style={styles.agencyInfo}>
          <p style={styles.agencyName}>{card.sub_agency || card.agency || 'Unknown Agency'}</p>
          {card.sub_agency && <p style={styles.agencyParent}>{card.agency}</p>}
        </div>
        {card.value_display && (
          <div style={styles.valueBadge}>{card.value_display}</div>
        )}
      </div>

      {/* Title */}
      <h3 style={styles.titleText}>{card.title}</h3>

      {/* Disqualifier + notice type pills */}
      <div style={styles.pillRow}>
        {noticeLabel && <Pill label={noticeLabel} color="blue" />}
        {flags.map((f, i) => (
          <span key={i} style={{
            ...styles.pill,
            background: (FLAG_COLORS[f.type] || FLAG_COLORS.cert).bg,
            color: (FLAG_COLORS[f.type] || FLAG_COLORS.cert).fg,
            border: `1px solid ${(FLAG_COLORS[f.type] || FLAG_COLORS.cert).border}`,
          }}>
            {FLAG_ICONS[f.type]} {f.label}
          </span>
        ))}
      </div>

      {/* Labeled data rows */}
      <div style={styles.dataRows}>
        {fitParts.length > 0 && (
          <DataRow label="Fit" value={fitParts.join(' · ')} />
        )}
        {scopeText && (
          <DataRow label="Scope" value={scopeText} lines={3} />
        )}
        {buyerParts.length > 0 && (
          <DataRow label="Buyer" value={buyerParts.join(' · ')} />
        )}
        {effortParts.length > 0 && (
          <DataRow label="Effort" value={effortParts.join(' · ')} />
        )}
        {scope.approved_source && (
          <DataRow label="Source" value={scope.approved_source} muted />
        )}
      </div>

      {/* Save button — sits in dead space above footer, only shown when onSave provided */}
      {onSave && (
        <button
          onClick={e => { e.stopPropagation(); onSave() }}
          style={styles.saveBtn}
        >
          ✓ Save to Pipeline
        </button>
      )}

      {/* Footer: deadline + details link */}
      <div style={styles.footer}>
        <div style={styles.deadlineRow}>
          <div style={{ ...styles.deadlineDot, background: urgencyColor }} />
          <span style={{ ...styles.deadlineText, color: urgencyColor }}>
            {deadlineText}
            {card.days_left_derived && ' *'}
          </span>
        </div>
        <div style={styles.footerActions}>
          {onExpand && (
            <button onClick={e => { e.stopPropagation(); onExpand() }} style={styles.detailsBtn}>
              Details
            </button>
          )}
          <a
            href={card.sam_url}
            target="_blank"
            rel="noreferrer"
            style={styles.samLink}
            onClick={e => e.stopPropagation()}
          >
            SAM.gov ↗
          </a>
        </div>
      </div>

      {/* Score bar */}
      {card.score != null && (
        <div style={styles.scoreBar}>
          <div style={{ ...styles.scoreFill, width: `${card.score}%` }} />
        </div>
      )}
    </div>
  )
})

export default OpportunityCard

function DataRow({ label, value, muted, lines = 2 }) {
  return (
    <div style={styles.dataRow}>
      <span style={styles.dataLabel}>{label}</span>
      <span style={{ ...styles.dataValue, WebkitLineClamp: lines, color: muted ? 'var(--muted)' : 'var(--text)' }}>
        {value}
      </span>
    </div>
  )
}

function Pill({ label, color }) {
  const c = color === 'purple'
    ? { bg: '#8b5cf615', fg: '#8b5cf6', border: '#8b5cf630' }
    : { bg: '#6366f115', fg: '#6366f1', border: '#6366f130' }
  return (
    <span style={{ ...styles.pill, background: c.bg, color: c.fg, border: `1px solid ${c.border}` }}>
      {label}
    </span>
  )
}

const styles = {
  card: {
    width: 'var(--card-width)',
    height: 'var(--card-height)',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '18px 20px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    position: 'absolute',
    userSelect: 'none',
    overflow: 'hidden',
  },

  // Header
  agencyRow: { display: 'flex', alignItems: 'center', gap: '10px' },
  agencyIcon: {
    width: '34px', height: '34px', borderRadius: '9px',
    background: 'var(--primary)', color: '#fff',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontWeight: '700', fontSize: '14px', flexShrink: 0,
  },
  agencyInfo: { flex: 1, minWidth: 0 },
  agencyName: {
    fontSize: '12px', fontWeight: '600', color: 'var(--text)',
    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  },
  agencyParent: { fontSize: '10px', color: 'var(--muted)', marginTop: '1px' },
  valueBadge: {
    background: '#22c55e15', color: '#22c55e', border: '1px solid #22c55e30',
    borderRadius: '8px', padding: '3px 8px', fontSize: '12px',
    fontWeight: '600', whiteSpace: 'nowrap', flexShrink: 0,
  },

  // Title
  titleText: {
    fontSize: '15px', fontWeight: '700', color: 'var(--text)',
    lineHeight: '1.3',
    display: '-webkit-box', WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical', overflow: 'hidden',
    wordBreak: 'break-word',
  },

  // Pills
  pillRow: { display: 'flex', gap: '5px', flexWrap: 'wrap' },
  pill: {
    padding: '3px 8px', borderRadius: '20px',
    fontSize: '11px', fontWeight: '600', whiteSpace: 'nowrap',
  },

  // Data rows
  dataRows: { display: 'flex', flexDirection: 'column', gap: '5px' },
  dataRow: { display: 'flex', gap: '8px', alignItems: 'baseline' },
  dataLabel: {
    fontSize: '10px', fontWeight: '700', color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '0.05em',
    whiteSpace: 'nowrap', flexShrink: 0, width: '42px',
  },
  dataValue: {
    fontSize: '12px', fontWeight: '500', lineHeight: '1.4',
    display: '-webkit-box', WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical', overflow: 'hidden',
  },

  // Save button — fills dead space between data rows and footer
  saveBtn: {
    marginTop: 'auto',
    padding: '10px',
    background: 'var(--primary)',
    color: '#fff',
    border: 'none',
    borderRadius: '10px',
    fontSize: '13px',
    fontWeight: '600',
    cursor: 'pointer',
    width: '100%',
  },

  // Footer
  footer: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  },
  deadlineRow: { display: 'flex', alignItems: 'center', gap: '6px' },
  deadlineDot: { width: '7px', height: '7px', borderRadius: '50%', flexShrink: 0 },
  deadlineText: { fontSize: '12px', fontWeight: '600' },
  footerActions: { display: 'flex', gap: '10px', alignItems: 'center' },
  detailsBtn: {
    fontSize: '11px', color: 'var(--primary)', background: 'none',
    border: 'none', padding: 0, cursor: 'pointer', fontWeight: '600',
  },
  samLink: { fontSize: '11px', color: 'var(--muted)' },

  // Score bar
  scoreBar: { height: '2px', background: 'var(--border)', borderRadius: '1px', marginTop: '-4px' },
  scoreFill: { height: '100%', background: 'var(--primary)', borderRadius: '1px', opacity: 0.4 },

  // Swipe feedback — always in DOM, shown/hidden via direct style mutation (no re-render)
  swipeOverlay: {
    position: 'absolute', inset: 0,
    borderRadius: 'var(--radius)',
    pointerEvents: 'none',
    opacity: 0,
    transition: 'opacity 150ms ease',
    zIndex: 10,
  },
  swipeStamp: {
    position: 'absolute', top: '22px',
    pointerEvents: 'none',
    fontSize: '22px', fontWeight: '800', letterSpacing: '0.08em',
    border: '3px solid transparent',
    borderRadius: '6px',
    padding: '3px 10px',
    opacity: 0,
    transition: 'opacity 150ms ease, transform 150ms ease',
    zIndex: 11,
  },
}
