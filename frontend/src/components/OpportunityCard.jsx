import { useEffect, useState } from 'react'
import { api } from '../lib/api'

const URGENCY_COLORS = { red: '#ef4444', yellow: '#eab308', green: '#22c55e', normal: '#8888a0' }
const NOTICE_TYPE_LABELS = {
  solicitation: 'Solicitation',
  presolicitation: 'Pre-Sol',
  sources_sought: 'Sources Sought',
  award: 'Award',
  combined: 'Combined',
}

export default function OpportunityCard({ card, style, isTop }) {
  const [summary, setSummary] = useState(card.ai_summary)

  // Fetch AI summary on-demand if missing, but only for the top card
  useEffect(() => {
    if (!summary && isTop && card.id) {
      api.generateSummary(card.id)
        .then(res => setSummary(res.summary))
        .catch(() => {})
    }
  }, [card.id, isTop, summary])

  const urgencyColor = URGENCY_COLORS[card.urgency] || URGENCY_COLORS.normal
  const displayText = summary || card.description_preview || 'No description available.'
  const noticeLabel = NOTICE_TYPE_LABELS[card.notice_type] || card.notice_type || 'Opportunity'

  return (
    <div style={{ ...styles.card, ...style }}>
      {/* Agency header */}
      <div style={styles.agencyRow}>
        <div style={styles.agencyIcon}>
          {(card.agency || 'U').charAt(0).toUpperCase()}
        </div>
        <div style={styles.agencyInfo}>
          <p style={styles.agencyName}>{card.agency || 'Unknown Agency'}</p>
          <p style={styles.subAgency}>{card.notice_type ? noticeLabel : ''}</p>
        </div>
        {card.value_display && (
          <div style={styles.valueBadge}>{card.value_display}</div>
        )}
      </div>

      {/* Title */}
      <h3 style={styles.title}>{card.title}</h3>

      {/* Summary / description */}
      <p style={styles.summary}>{displayText}</p>

      {/* Badges row */}
      <div style={styles.badges}>
        {card.naics_code && <Badge label={card.naics_code} />}
        {card.set_aside_type && card.set_aside_type !== 'NONE' && (
          <Badge label={card.set_aside_type} color="#6366f1" />
        )}
        {card.pop_state && <Badge label={card.pop_state} />}
        {card.has_attachments && <Badge label="Docs attached" />}
      </div>

      {/* Footer */}
      <div style={styles.footer}>
        <div style={styles.deadlineRow}>
          <div style={{ ...styles.deadlineDot, background: urgencyColor }} />
          <span style={{ ...styles.deadlineText, color: urgencyColor }}>
            {card.days_left === null
              ? 'No deadline'
              : card.days_left <= 0
              ? 'Closing today'
              : card.days_left === 1
              ? '1 day left'
              : `${card.days_left} days left`}
          </span>
        </div>
        <a
          href={card.sam_url}
          target="_blank"
          rel="noreferrer"
          style={styles.samLink}
          onClick={e => e.stopPropagation()}
        >
          View on SAM.gov ↗
        </a>
      </div>

      {/* Score indicator (subtle) */}
      {card.score != null && (
        <div style={styles.scoreBar}>
          <div style={{ ...styles.scoreFill, width: `${card.score}%` }} />
        </div>
      )}
    </div>
  )
}

function Badge({ label, color }) {
  return (
    <span style={{
      ...styles.badge,
      background: color ? color + '22' : 'var(--surface2)',
      color: color || 'var(--muted)',
      border: `1px solid ${color ? color + '44' : 'var(--border)'}`,
    }}>
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
    padding: '24px',
    display: 'flex',
    flexDirection: 'column',
    gap: '14px',
    position: 'absolute',
    userSelect: 'none',
    overflow: 'hidden',
  },
  agencyRow: { display: 'flex', alignItems: 'center', gap: '12px' },
  agencyIcon: {
    width: '40px',
    height: '40px',
    borderRadius: '10px',
    background: 'var(--primary)',
    color: '#fff',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: '700',
    fontSize: '16px',
    flexShrink: 0,
  },
  agencyInfo: { flex: 1, minWidth: 0 },
  agencyName: { fontSize: '13px', fontWeight: '600', color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
  subAgency: { fontSize: '11px', color: 'var(--muted)', marginTop: '1px' },
  valueBadge: {
    background: '#22c55e22',
    color: '#22c55e',
    border: '1px solid #22c55e44',
    borderRadius: '8px',
    padding: '4px 10px',
    fontSize: '13px',
    fontWeight: '600',
    whiteSpace: 'nowrap',
  },
  title: {
    fontSize: '17px',
    fontWeight: '600',
    color: 'var(--text)',
    lineHeight: '1.35',
    display: '-webkit-box',
    WebkitLineClamp: 3,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  },
  summary: {
    fontSize: '13px',
    color: 'var(--muted)',
    lineHeight: '1.6',
    flex: 1,
    display: '-webkit-box',
    WebkitLineClamp: 5,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  },
  badges: { display: 'flex', flexWrap: 'wrap', gap: '6px' },
  badge: {
    padding: '3px 9px',
    borderRadius: '20px',
    fontSize: '11px',
    fontWeight: '500',
  },
  footer: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 'auto' },
  deadlineRow: { display: 'flex', alignItems: 'center', gap: '6px' },
  deadlineDot: { width: '7px', height: '7px', borderRadius: '50%' },
  deadlineText: { fontSize: '12px', fontWeight: '600' },
  samLink: { fontSize: '11px', color: 'var(--muted)' },
  scoreBar: { height: '2px', background: 'var(--border)', borderRadius: '1px', marginTop: '-6px' },
  scoreFill: { height: '100%', background: 'var(--primary)', borderRadius: '1px', opacity: 0.5 },
}
