import { useState, useEffect, useRef, useCallback } from 'react'
import TinderCard from 'react-tinder-card'
import OpportunityCard from '../components/OpportunityCard'
import DetailModal from '../components/DetailModal'
import { api, db } from '../lib/api'

export default function Feed({ user, company }) {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [exhausted, setExhausted] = useState(false)
  const [lastSwipe, setLastSwipe] = useState(null)  // { direction, title }
  const [swipeCount, setSwipeCount] = useState(0)
  const [expandedCard, setExpandedCard] = useState(null)
  const cardRefs = useRef([])
  const swipeStartTime = useRef(null)

  // Top card is always the last element in the array
  const currentIndex = cards.length - 1

  const loadFeed = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getFeed(20)
      if (data.exhausted || !data.cards?.length) {
        setExhausted(true)
      } else {
        setCards(prev => {
          // Append new cards, avoiding duplicates
          const existingIds = new Set(prev.map(c => c.id))
          const fresh = data.cards.filter(c => !existingIds.has(c.id))
          return [...fresh, ...prev]
        })
      }
    } catch (err) {
      console.error('Feed load failed:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadFeed()
  }, [loadFeed])

  // Track dwell time — starts when a card becomes the top card
  useEffect(() => {
    swipeStartTime.current = Date.now()
  }, [currentIndex])

  const onSwipe = useCallback(async (direction, card) => {
    const dwellMs = swipeStartTime.current ? Date.now() - swipeStartTime.current : null

    setLastSwipe({ direction, title: card.title })
    setSwipeCount(prev => prev + 1)

    // Remove card from deck — this advances to the next card
    setCards(prev => prev.filter(c => c.id !== card.id))

    // Load more when running low (cards.length - 1 = deck size after this swipe)
    if (cards.length - 1 <= 3 && !exhausted) {
      loadFeed()
    }

    // Record swipe in Supabase
    db.recordSwipe({
      userId: user.id,
      companyId: company.id,
      opportunityId: card.id,
      direction,
      dwellMs,
      expanded: false,
    }).catch(err => console.error('Swipe record failed:', err))

    // If swiped right, also add to pipeline
    if (direction === 'right') {
      db.addToPipeline({
        companyId: company.id,
        opportunityId: card.id,
        userId: user.id,
      }).catch(err => console.error('Pipeline add failed:', err))
    }
  }, [user, company, cards.length, exhausted, loadFeed])

  // Programmatic swipe via buttons
  const swipe = async (direction) => {
    const ref = cardRefs.current[currentIndex]
    if (ref) await ref.swipe(direction)
  }

  if (loading && cards.length === 0) {
    return (
      <div style={styles.centered}>
        <div style={styles.spinner} />
        <p style={{ color: 'var(--muted)', marginTop: '16px', fontSize: '14px' }}>Loading your feed...</p>
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
              onExpand={() => setExpandedCard(card)}
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
          onClick={() => setExpandedCard(cards[currentIndex])}
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
    animation: 'none',
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
