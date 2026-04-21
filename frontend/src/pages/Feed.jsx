import { useState, useEffect, useRef, useCallback } from 'react'
import TinderCard from 'react-tinder-card'
import OpportunityCard from '../components/OpportunityCard'
import DetailModal from '../components/DetailModal'
import { api, db } from '../lib/api'

const SESSION_SWIPE_KEY = 'govscroll_swipe_count'
const SESSION_CARDS_TS_KEY = 'govscroll_cards_ts'
const QUEUE_MAX_AGE_MS = 4 * 60 * 60 * 1000  // 4 hours — stale after this

// Bump this when card payload schema changes to auto-invalidate old caches
const CARD_SCHEMA_VERSION = 4
const SESSION_CARDS_KEY = `govscroll_cards_v${CARD_SCHEMA_VERSION}`

function readSavedCards() {
  try {
    const ts = parseInt(sessionStorage.getItem(SESSION_CARDS_TS_KEY) || '0', 10)
    if (Date.now() - ts < QUEUE_MAX_AGE_MS) {
      const raw = sessionStorage.getItem(SESSION_CARDS_KEY)
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed) && parsed.length > 0) return parsed
      }
    }
  } catch {}
  return null
}

export default function Feed({ user, company }) {
  // Restore card queue from sessionStorage on mount (survives tab discard)
  const savedCards = useRef(readSavedCards())
  const [cards, setCards] = useState(savedCards.current || [])
  const [loading, setLoading] = useState(!savedCards.current)
  const [exhausted, setExhausted] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [lastSwipe, setLastSwipe] = useState(null)
  const [swipeCount, setSwipeCount] = useState(
    () => parseInt(sessionStorage.getItem(SESSION_SWIPE_KEY) || '0', 10)
  )
  const [expandedCard, setExpandedCard] = useState(null)
  const cardRefs = useRef([])
  const swipeStartTime = useRef(null)

  // Top card is always the last element in the array
  const currentIndex = cards.length - 1

  // Persist swipe count to sessionStorage whenever it changes
  useEffect(() => {
    sessionStorage.setItem(SESSION_SWIPE_KEY, String(swipeCount))
  }, [swipeCount])

  // Load accurate swipe count from Supabase on mount
  useEffect(() => {
    if (!user?.id) return
    db.getTodaySwipeCount(user.id)
      .then(count => setSwipeCount(count))
      .catch(() => {})
  }, [user?.id])

  // Persist card queue to sessionStorage after every change so tab restores work
  useEffect(() => {
    if (cards.length > 0) {
      try {
        sessionStorage.setItem(SESSION_CARDS_KEY, JSON.stringify(cards))
        sessionStorage.setItem(SESSION_CARDS_TS_KEY, String(Date.now()))
      } catch {}
    }
  }, [cards])

  const loadFeed = useCallback(async () => {
    setLoading(true)
    setLoadError(false)
    try {
      const data = await api.getFeed(30)
      if (data.exhausted || !data.cards?.length) {
        setExhausted(true)
      } else {
        setExhausted(false)
        setCards(prev => {
          const existingIds = new Set(prev.map(c => c.id))
          const fresh = data.cards.filter(c => !existingIds.has(c.id))
          return [...fresh, ...prev]
        })
      }
    } catch (err) {
      console.error('Feed load failed:', err)
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  // On mount: skip load if we restored a healthy queue, otherwise load from API.
  // Also load if the restored queue is running low.
  useEffect(() => {
    if (!savedCards.current || savedCards.current.length <= 6) {
      loadFeed()
    }
  }, [loadFeed])

  // Track dwell time — starts when a new card becomes the top card
  useEffect(() => {
    swipeStartTime.current = Date.now()
  }, [currentIndex])

  const onSwipe = useCallback(async (direction, card) => {
    const dwellMs = swipeStartTime.current ? Date.now() - swipeStartTime.current : null

    setLastSwipe({ direction, title: card.title })
    setSwipeCount(prev => prev + 1)

    // Remove card from deck
    setCards(prev => prev.filter(c => c.id !== card.id))

    // Refill when running low
    if (cards.length - 1 <= 6 && !exhausted) {
      loadFeed()
    }

    db.recordSwipe({
      userId: user.id,
      companyId: company.id,
      opportunityId: card.id,
      direction,
      dwellMs,
      expanded: false,
    }).catch(err => console.error('Swipe record failed:', err))

    if (direction === 'right') {
      db.addToPipeline({
        companyId: company.id,
        opportunityId: card.id,
        userId: user.id,
      }).catch(err => console.error('Pipeline add failed:', err))
    }
  }, [user, company, cards.length, exhausted, loadFeed])

  const swipe = async (direction) => {
    const ref = cardRefs.current[currentIndex]
    if (ref) await ref.swipe(direction)
  }

  // Record detail view as an interest signal, then open the modal
  const handleExpand = useCallback((card) => {
    setExpandedCard(card)
    db.recordDetailView({
      userId: user.id,
      companyId: company.id,
      opportunityId: card.id,
    }).catch(() => {})
  }, [user.id, company.id])

  if (loading && cards.length === 0) {
    return (
      <div style={styles.centered}>
        <div style={styles.spinner} />
        <p style={{ color: 'var(--muted)', marginTop: '16px', fontSize: '14px' }}>Loading your feed...</p>
      </div>
    )
  }

  if (loadError && cards.length === 0) {
    return (
      <div style={styles.centered}>
        <p style={{ fontSize: '32px' }}>⚠️</p>
        <h3 style={{ color: 'var(--text)', margin: '12px 0 8px' }}>Could not reach the server</h3>
        <p style={{ color: 'var(--muted)', fontSize: '13px', textAlign: 'center', maxWidth: '280px', lineHeight: '1.6' }}>
          Make sure the Flask API is running on port 5001, then retry.
        </p>
        <button style={styles.refreshBtn} onClick={loadFeed}>Retry</button>
      </div>
    )
  }

  if (exhausted && cards.length === 0) {
    return (
      <div style={styles.centered}>
        <p style={{ fontSize: '40px' }}>🎉</p>
        <h3 style={{ color: 'var(--text)', margin: '12px 0 8px' }}>You're all caught up</h3>
        <p style={{ color: 'var(--muted)', fontSize: '14px' }}>Check back tomorrow for new opportunities.</p>
        <button style={styles.refreshBtn} onClick={loadFeed}>Refresh feed</button>
      </div>
    )
  }

  return (
    <div style={styles.page}>
      {/* Header */}
      <div style={styles.header}>
        <h2 style={styles.headerTitle}>Your Feed</h2>
        <div style={styles.swipeCount}>{swipeCount} reviewed today</div>
      </div>

      {/* Swipe feedback flash */}
      {lastSwipe && (
        <div style={{
          ...styles.swipeFeedback,
          background: lastSwipe.direction === 'right' ? '#22c55e22' : '#ef444422',
          color: lastSwipe.direction === 'right' ? '#22c55e' : '#ef4444',
          borderColor: lastSwipe.direction === 'right' ? '#22c55e44' : '#ef444444',
        }}>
          {lastSwipe.direction === 'right' ? '✓ Added to pipeline' : '✕ Passed'}
        </div>
      )}

      {/* Card stack */}
      <div style={styles.deck}>
        {cards.map((card, index) => (
          <TinderCard
            key={card.id}
            ref={el => cardRefs.current[index] = el}
            onSwipe={(dir) => onSwipe(dir, card)}
            preventSwipe={['up', 'down']}
            swipeRequirementType="position"
            swipeThreshold={80}
          >
            <OpportunityCard
              card={card}
              isTop={index === currentIndex}
              preload={index >= currentIndex - 2}
              onExpand={() => handleExpand(card)}
              style={{
                transform: index === currentIndex
                  ? 'scale(1)'
                  : index === currentIndex - 1
                  ? 'scale(0.96) translateY(12px)'
                  : 'scale(0.92) translateY(24px)',
                opacity: index < currentIndex - 2 ? 0 : 1,
                zIndex: index,
                transition: 'transform 0.2s ease, opacity 0.2s ease',
              }}
            />
          </TinderCard>
        ))}
      </div>

      {/* Action buttons */}
      <div style={styles.actions}>
        <ActionBtn onClick={() => swipe('left')} color="#ef4444" label="Pass">✕</ActionBtn>
        <ActionBtn
          onClick={() => cards[currentIndex] && handleExpand(cards[currentIndex])}
          color="#6366f1"
          label="Details"
        >
          ⓘ
        </ActionBtn>
        <ActionBtn onClick={() => swipe('right')} color="#22c55e" label="Save" large>✓</ActionBtn>
      </div>

      {/* Keyboard hint */}
      <p style={styles.hint}>← Pass &nbsp;&nbsp; Save →</p>

      {/* Detail modal */}
      {expandedCard && (
        <DetailModal
          card={expandedCard}
          onClose={() => setExpandedCard(null)}
          onPass={() => { swipe('left'); setExpandedCard(null) }}
          onSave={() => { swipe('right'); setExpandedCard(null) }}
        />
      )}
    </div>
  )
}

function ActionBtn({ onClick, color, label, large, children }) {
  return (
    <button
      onClick={onClick}
      title={label}
      style={{
        width: large ? '64px' : '52px',
        height: large ? '64px' : '52px',
        borderRadius: '50%',
        background: color + '22',
        color,
        border: `2px solid ${color}44`,
        fontSize: large ? '22px' : '18px',
        fontWeight: '700',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'all 0.15s',
      }}
    >
      {children}
    </button>
  )
}

const styles = {
  page: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '20px 20px 0',
    gap: '16px',
    overflow: 'hidden',
  },
  header: {
    width: '100%',
    maxWidth: 'var(--card-width)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerTitle: { fontSize: '20px', fontWeight: '700', color: 'var(--text)' },
  swipeCount: {
    fontSize: '12px',
    color: 'var(--muted)',
    background: 'var(--surface)',
    padding: '4px 10px',
    borderRadius: '20px',
    border: '1px solid var(--border)',
  },
  swipeFeedback: {
    fontSize: '13px',
    fontWeight: '600',
    padding: '6px 14px',
    borderRadius: '20px',
    border: '1px solid',
  },
  deck: {
    position: 'relative',
    width: 'var(--card-width)',
    height: 'var(--card-height)',
    flexShrink: 0,
  },
  actions: {
    display: 'flex',
    gap: '24px',
    alignItems: 'center',
    paddingTop: '8px',
  },
  hint: {
    fontSize: '11px',
    color: 'var(--border)',
    paddingBottom: '16px',
  },
  centered: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    padding: '24px',
  },
  spinner: {
    width: '32px',
    height: '32px',
    border: '3px solid var(--border)',
    borderTop: '3px solid var(--primary)',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  refreshBtn: {
    marginTop: '16px',
    background: 'var(--primary)',
    color: '#fff',
    borderRadius: '10px',
    padding: '10px 20px',
    fontSize: '14px',
    fontWeight: '600',
  },
}
