import { useState, useEffect } from 'react'
import { db } from '../lib/api'

function csvCell(val) {
  if (val === null || val === undefined) return ''
  const str = String(val)
  if (str.includes(',') || str.includes('"') || str.includes('\n') || str.includes('\r')) {
    return '"' + str.replace(/"/g, '""') + '"'
  }
  return str
}

function exportCsv(items) {
  const headers = [
    'Title', 'Agency', 'Sub-Agency', 'Notice ID', 'Notice Type',
    'NAICS Code', 'Set-Aside', 'Est. Value', 'Deadline', 'Posted Date',
    'Place of Performance', 'Pipeline Stage', 'SAM.gov URL',
  ]
  const rows = items.map(item => {
    const opp = item.opportunities || {}
    const samUrl = opp.notice_id ? `https://sam.gov/opp/${opp.notice_id}/view` : ''
    const deadline = opp.response_deadline
      ? new Date(opp.response_deadline).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
      : ''
    const posted = opp.posted_date
      ? new Date(opp.posted_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
      : ''
    const pop = [opp.pop_city, opp.pop_state].filter(Boolean).join(', ')
    const val = opp.value_max ? valueDisplay(opp.value_max) : ''
    const setAside = opp.set_aside_type && opp.set_aside_type !== 'NONE'
      ? (SET_ASIDE_LABELS[opp.set_aside_type] || opp.set_aside_type)
      : ''
    return [
      opp.title || '', opp.agency || '', opp.sub_agency || '',
      opp.notice_id || '', opp.notice_type || '', opp.naics_code || '',
      setAside, val, deadline, posted, pop,
      item.stage || 'watching', samUrl,
    ].map(csvCell).join(',')
  })
  const csv = [headers.map(csvCell).join(','), ...rows].join('\r\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `govscroll-liked-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

const SET_ASIDE_LABELS = {
  SBA: 'Small Business', '8AN': '8(a)', '8A': '8(a)',
  SDVOSBC: 'SDVOSB', SDVOSBR: 'SDVOSB',
  WOSB: 'WOSB', EDWOSB: 'EDWOSB',
  HZC: 'HUBZone', HZS: 'HUBZone',
}

function daysLeft(deadline) {
  if (!deadline) return null
  return Math.ceil((new Date(deadline) - new Date()) / (1000 * 60 * 60 * 24))
}

function valueDisplay(max) {
  if (!max) return null
  const v = parseFloat(max)
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`
  return `$${v}`
}

export default function SavedList({ company, onRemove }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [copiedId, setCopiedId] = useState(null)

  function handleShare(opp, itemId) {
    const url = opp.notice_id ? `https://sam.gov/opp/${opp.notice_id}/view` : 'https://sam.gov'
    if (navigator.share) {
      const agency = opp.sub_agency || opp.agency || ''
      navigator.share({
        title: opp.title || 'Government Contract Opportunity',
        text: agency ? `${agency} — ${opp.title}` : opp.title,
        url,
      }).catch(() => {})
    } else {
      navigator.clipboard.writeText(url).then(() => {
        setCopiedId(itemId)
        setTimeout(() => setCopiedId(null), 2000)
      }).catch(() => {})
    }
  }

  useEffect(() => {
    if (!company?.id) return
    db.getPipeline(company.id)
      .then(({ data }) => setItems(data || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [company?.id])

  const handleRemove = (item) => {
    setItems(prev => prev.filter(i => i.id !== item.id))
    onRemove?.(item.opportunity_id)
    db.removeFromPipeline({ companyId: company.id, opportunityId: item.opportunity_id })
      .catch(console.error)
  }

  if (loading) {
    return (
      <div style={styles.centered}>
        <div style={styles.spinner} />
      </div>
    )
  }

  if (!items.length) {
    return (
      <div style={styles.centered}>
        <p style={{ fontSize: '36px' }}>👍</p>
        <h3 style={styles.emptyTitle}>Nothing liked yet</h3>
        <p style={styles.emptyText}>Swipe right or tap Save on a card to add opportunities here.</p>
      </div>
    )
  }

  return (
    <div style={styles.list}>
      <div style={styles.listHeader}>
        <p style={styles.countLabel}>{items.length} saved</p>
        <button onClick={() => exportCsv(items)} style={styles.exportBtn}>
          Export CSV
        </button>
      </div>
      {items.map(item => {
        const opp = item.opportunities
        if (!opp) return null

        const days = daysLeft(opp.response_deadline)
        const deadlineText = days === null ? 'No deadline'
          : days <= 0 ? 'Closing today'
          : days === 1 ? '1 day left'
          : `${days} days left`
        const deadlineColor = days !== null && days <= 7 ? '#ef4444'
          : days !== null && days <= 21 ? '#eab308'
          : '#22c55e'

        const setAside = opp.set_aside_type && opp.set_aside_type !== 'NONE'
          ? (SET_ASIDE_LABELS[opp.set_aside_type] || opp.set_aside_type)
          : null
        const val = valueDisplay(opp.value_max)
        const samUrl = opp.notice_id
          ? `https://sam.gov/opp/${opp.notice_id}/view`
          : null

        return (
          <div key={item.id} style={styles.item}>
            <div style={styles.itemHeader}>
              <div style={styles.agencyIcon}>
                {(opp.agency || 'U').charAt(0).toUpperCase()}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={styles.agencyName}>{opp.sub_agency || opp.agency || 'Unknown Agency'}</p>
                {opp.sub_agency && <p style={styles.agencyParent}>{opp.agency}</p>}
              </div>
              {val && <span style={styles.valueBadge}>{val}</span>}
            </div>

            <p style={styles.itemTitle}>{opp.title}</p>

            <div style={styles.tags}>
              {opp.naics_code && (
                <span style={styles.tag}>NAICS {opp.naics_code}</span>
              )}
              {setAside && (
                <span style={styles.tag}>{setAside}</span>
              )}
            </div>

            <div style={styles.itemFooter}>
              <span style={{ ...styles.deadline, color: deadlineColor }}>
                ● {deadlineText}
              </span>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                {samUrl && (
                  <a href={samUrl} target="_blank" rel="noreferrer" style={styles.samLink}>
                    SAM.gov ↗
                  </a>
                )}
                <button onClick={() => handleShare(opp, item.id)} style={styles.actionBtn}>
                  {copiedId === item.id ? 'Copied!' : 'Share'}
                </button>
                <button onClick={() => handleRemove(item)} style={styles.removeBtn}>
                  Remove
                </button>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

const styles = {
  centered: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    padding: '24px',
  },
  spinner: {
    width: '28px', height: '28px',
    border: '3px solid var(--border)',
    borderTop: '3px solid var(--primary)',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  emptyTitle: { fontSize: '16px', fontWeight: '700', color: 'var(--text)', margin: '8px 0 4px' },
  emptyText: { fontSize: '13px', color: 'var(--muted)', textAlign: 'center', lineHeight: '1.6' },

  list: {
    flex: 1,
    overflowY: 'auto',
    width: '100%',
    maxWidth: '560px',
    padding: '16px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    alignSelf: 'center',
  },
  listHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: '2px',
  },
  countLabel: {
    fontSize: '11px', fontWeight: '600', color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '0.06em',
  },
  exportBtn: {
    fontSize: '11px', fontWeight: '600', color: 'var(--primary)',
    background: 'none', border: '1px solid var(--primary)',
    borderRadius: '8px', padding: '4px 10px', cursor: 'pointer',
  },

  item: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: '14px',
    padding: '14px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  itemHeader: { display: 'flex', alignItems: 'center', gap: '10px' },
  agencyIcon: {
    width: '30px', height: '30px', borderRadius: '7px',
    background: 'var(--primary)', color: '#fff',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontWeight: '700', fontSize: '13px', flexShrink: 0,
  },
  agencyName: { fontSize: '12px', fontWeight: '600', color: 'var(--text)' },
  agencyParent: { fontSize: '10px', color: 'var(--muted)', marginTop: '1px' },
  valueBadge: {
    background: '#22c55e15', color: '#22c55e', border: '1px solid #22c55e30',
    borderRadius: '8px', padding: '2px 8px', fontSize: '11px',
    fontWeight: '600', whiteSpace: 'nowrap', flexShrink: 0,
  },
  itemTitle: {
    fontSize: '14px', fontWeight: '600', color: 'var(--text)', lineHeight: '1.35',
  },
  tags: { display: 'flex', gap: '6px', flexWrap: 'wrap' },
  tag: {
    fontSize: '11px', fontWeight: '500', color: 'var(--muted)',
    background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: '6px', padding: '2px 8px',
  },
  itemFooter: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginTop: '2px',
  },
  deadline: { fontSize: '12px', fontWeight: '600' },
  samLink: { fontSize: '11px', color: 'var(--primary)', textDecoration: 'none', fontWeight: '500' },
  actionBtn: {
    fontSize: '11px', color: 'var(--primary)', background: 'none',
    border: 'none', cursor: 'pointer', padding: 0, fontWeight: '500',
  },
  removeBtn: {
    fontSize: '11px', color: 'var(--muted)', background: 'none',
    border: 'none', cursor: 'pointer', padding: 0, fontWeight: '500',
  },
}
