import { useState, useEffect, useRef, useCallback } from 'react'
import TinderCard from 'react-tinder-card'
import OpportunityCard from '../components/OpportunityCard'
import DetailModal from '../components/DetailModal'
import SavedList from '../components/SavedList'
import BookmarksList from '../components/BookmarksList'
import { api, db } from '../lib/api'

const SWIPE_HISTORY_MAX = 3
const SESSION_SWIPE_KEY = 'govscroll_swipe_count'
const SESSION_CARDS_TS_KEY = 'govscroll_cards_ts'
const QUEUE_MAX_AGE_MS = 4 * 60 * 60 * 1000

// Bump this when card payload schema changes to auto-invalidate old caches
const CARD_SCHEMA_VERSION = 6
const SESSION_CARDS_KEY = `govscroll_cards_v${CARD_SCHEMA_VERSION}`

const SAVE_ANIM_MS = 360  // Duration of the shrink-and-sink animation

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
  const savedCards = useRef(readSavedCards())
  const [cards, setCards] = useState(savedCards.current || [])
  const [loading, setLoading] = useState(!savedCards.current)
  const [exhausted, setExhausted] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [swipeCount, setSwipeCount] = useState(
    () => parseInt(sessionStorage.getItem(SESSION_SWIPE_KEY) || '0', 10)
  )
  const [expandedCard, setExpandedCard] = useState(null)
  const [swipeHistory, setSwipeHistory] = useState([])
  const [savingCardId, setSavingCardId] = useState(null)  // triggers shrink-and-sink anim
  const [view, setView] = useState('feed')                // 'feed' | 'liked' | 'bookmarks'
  const [savedCount, setSavedCount] = useState(0)
  const [bookmarkCount, setBookmarkCount] = useState(0)

  const cardRefs     = useRef([])  // TinderCard refs (for programmatic swipe)
  const cardHintRefs = useRef([])  // OpportunityCard refs (for imperative setHint)
  const swipeStartTime = useRef(null)

  const currentIndex = cards.length - 1

  useEffect(() => {
    sessionStorage.setItem(SESSION_SWIPE_KEY, String(swipeCount))
  }, [swipeCount])

  useEffect(() => {
    if (!user?.id) return
    db.getTodaySwipeCount(user.id)
      .then(count => setSwipeCount(count))
      .catch(() => {})
  }, [user?.id])

  // Load liked + bookmark counts for tab badges
  useEffect(() => {
    if (!company?.id) return
    db.getPipeline(company.id)
      .then(({ data }) => setSavedCount((data || []).length))
      .catch(() => {})
    db.getBookmarks(company.id)
      .then(({ data }) => setBookmarkCount((data || []).length))
      .catch(() => {})
  }, [company?.id])

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

  useEffect(() => {
    if (!savedCards.current || savedCards.current.length <= 6) {
      loadFeed()
    }
  }, [loadFeed])

  useEffect(() => {
    swipeStartTime.current = Date.now()
  }, [currentIndex])

  // Gesture swipe (left only for pass — right gesture still works but button is primary for save)
  const onSwipe = useCallback(async (direction, card) => {
    const dwellMs = swipeStartTime.current ? Date.now() - swipeStartTime.current : null

    setSwipeCount(prev => prev + 1)
    setSwipeHistory(prev => [...prev.slice(-(SWIPE_HISTORY_MAX - 1)), { card, direction }])
    setCards(prev => prev.filter(c => c.id !== card.id))

    if (cards.length - 1 <= 6 && !exhausted) loadFeed()

    db.recordSwipe({
      userId: user.id,
      companyId: company.id,
      opportunityId: card.id,
      direction,
      dwellMs,
      expanded: false,
    }).catch(err => console.error('Swipe record failed:', err))

    if (direction === 'right') {
      setSavedCount(prev => prev + 1)
      db.addToPipeline({
        companyId: company.id,
        opportunityId: card.id,
        userId: user.id,
      }).catch(err => console.error('Pipeline add failed:', err))
    }
  }, [user, company, cards.length, exhausted, loadFeed])

  // Button-triggered save — plays shrink-and-sink animation before removing card
  const handleSave = useCallback((card) => {
    const dwellMs = swipeStartTime.current ? Date.now() - swipeStartTime.current : null

    setSavingCardId(card.id)

    setTimeout(() => {
      setSavingCardId(null)
      setSwipeCount(prev => prev + 1)
      setSavedCount(prev => prev + 1)
      setSwipeHistory(prev => [...prev.slice(-(SWIPE_HISTORY_MAX - 1)), { card, direction: 'right' }])
      setCards(prev => prev.filter(c => c.id !== card.id))

      if (cards.length - 1 <= 6 && !exhausted) loadFeed()

      db.recordSwipe({
        userId: user.id,
        companyId: company.id,
        opportunityId: card.id,
        direction: 'right',
        dwellMs,
        expanded: false,
      }).catch(err => console.error('Save swipe record failed:', err))

      db.addToPipeline({
        companyId: company.id,
        opportunityId: card.id,
        userId: user.id,
      }).catch(err => console.error('Pipeline add failed:', err))
    }, SAVE_ANIM_MS)
  }, [user, company, cards.length, exhausted, loadFeed])

  const swipe = useCallback(async (direction) => {
    const ref = cardRefs.current[currentIndex]
    if (ref) await ref.swipe(direction)
  }, [currentIndex])

  const handleUndo = useCallback(() => {
    if (swipeHistory.length === 0) return
    const last = swipeHistory[swipeHistory.length - 1]
    setSwipeHistory(prev => prev.slice(0, -1))
    setCards(prev => [...prev, last.card])
    setSwipeCount(prev => Math.max(0, prev - 1))

    db.deleteSwipe({ userId: user.id, opportunityId: last.card.id })
      .catch(err => console.error('Undo swipe delete failed:', err))

    if (last.direction === 'right') {
      setSavedCount(prev => Math.max(0, prev - 1))
      db.removeFromPipeline({ companyId: company.id, opportunityId: last.card.id })
        .catch(err => console.error('Undo pipeline remove failed:', err))
    }
  }, [swipeHistory, user.id, company.id])

  const handleBookmark = useCallback(() => {
    const card = cards[currentIndex]
    if (!card) return
    setCards(prev => prev.filter(c => c.id !== card.id))
    setBookmarkCount(prev => prev + 1)
    db.addBookmark({
      companyId: company.id,
      opportunityId: card.id,
      userId: user.id,
    }).catch(err => console.error('Bookmark failed:', err))
  }, [cards, currentIndex, company.id, user.id])

  // Keyboard navigation: ← / J = pass, → / L = save, Z = undo
  useEffect(() => {
    if (view !== 'feed') return
    const handler = (e) => {
      if (expandedCard) return
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      if (e.key === 'ArrowLeft'  || e.key === 'j') swipe('left')
      if (e.key === 'ArrowRight' || e.key === 'l') swipe('right')
      if (e.key === 'z') handleUndo()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [view, expandedCard, swipe, handleUndo])

  const handleExpand = useCallback((card) => {
    setExpandedCard(card)
    db.recordDetailView({
      userId: user.id,
      companyId: company.id,
      opportunityId: card.id,
    }).catch(() => {})
  }, [user.id, company.id])

  const handleRemoveFromSaved = useCallback(() => {
    setSavedCount(prev => Math.max(0, prev - 1))
  }, [])

  const handleRemoveFromBookmarks = useCallback(() => {
    setBookmarkCount(prev => Math.max(0, prev - 1))
  }, [])

  // ── Empty/error states ────────────────────────────────────────────────────

  if (loading && cards.length === 0 && view === 'feed') {
    return (
      <div style={styles.pageShell}>
        <div style={styles.centered}>
          <div style={styles.spinner} />
          <p style={{ color: 'var(--muted)', marginTop: '16px', fontSize: '14px' }}>Loading your feed...</p>
        </div>
        <BottomNav view={view} setView={setView} savedCount={savedCount} bookmarkCount={bookmarkCount} />
      </div>
    )
  }

  if (loadError && cards.length === 0 && view === 'feed') {
    return (
      <div style={styles.pageShell}>
        <div style={styles.centered}>
          <p style={{ fontSize: '32px' }}>⚠️</p>
          <h3 style={{ color: 'var(--text)', margin: '12px 0 8px' }}>Could not reach the server</h3>
          <p style={{ color: 'var(--muted)', fontSize: '13px', textAlign: 'center', maxWidth: '280px', lineHeight: '1.6' }}>
            Make sure the Flask API is running on port 5001, then retry.
          </p>
          <button style={styles.refreshBtn} onClick={loadFeed}>Retry</button>
        </div>
        <BottomNav view={view} setView={setView} savedCount={savedCount} bookmarkCount={bookmarkCount} />
      </div>
    )
  }

  if (exhausted && cards.length === 0 && view === 'feed') {
    return (
      <div style={styles.pageShell}>
        <div style={styles.centered}>
          <p style={{ fontSize: '40px' }}>🎉</p>
          <h3 style={{ color: 'var(--text)', margin: '12px 0 8px' }}>You're all caught up</h3>
          <p style={{ color: 'var(--muted)', fontSize: '14px' }}>Check back tomorrow for new opportunities.</p>
          <button style={styles.refreshBtn} onClick={loadFeed}>Refresh feed</button>
        </div>
        <BottomNav view={view} setView={setView} savedCount={savedCount} bookmarkCount={bookmarkCount} />
      </div>
    )
  }

  return (
    <div style={styles.pageShell}>

      {view === 'feed' ? (
        <>
          {/* feedContent holds header + deck — pageShell's overflow:hidden clips swipe animations */}
          <div style={styles.feedContent}>

            {/* Header */}
            <div style={styles.header}>
              <h2 style={styles.headerTitle}>Your Feed</h2>
              <div style={styles.swipeCount}>{swipeCount} reviewed today</div>
            </div>


            {/* Card stack */}
            <div style={styles.deck}>
              {cards.map((card, index) => {
                const isSaving = card.id === savingCardId
                return (
                  <TinderCard
                    key={card.id}
                    ref={el => cardRefs.current[index] = el}
                    onSwipe={(dir) => onSwipe(dir, card)}
                    onSwipeRequirementFulfilled={(dir) => {
                      if (index === currentIndex)
                        cardHintRefs.current[index]?.setHint(dir)
                    }}
                    onSwipeRequirementUnfulfilled={() => {
                      cardHintRefs.current[currentIndex]?.setHint(null)
                    }}
                    preventSwipe={['up', 'down']}
                    swipeRequirementType="position"
                    swipeThreshold={80}
                  >
                    <OpportunityCard
                      ref={el => cardHintRefs.current[index] = el}
                      card={card}
                      isTop={index === currentIndex}
                      preload={index >= currentIndex - 2}
                      onExpand={() => handleExpand(card)}
                      onSave={() => handleSave(card)}
                      style={{
                        transform: isSaving
                          ? 'scale(0.78) translateY(72px)'
                          : index === currentIndex
                          ? 'scale(1)'
                          : index === currentIndex - 1
                          ? 'scale(0.96) translateY(12px)'
                          : 'scale(0.92) translateY(24px)',
                        opacity: isSaving ? 0
                          : index < currentIndex - 2 ? 0 : 1,
                        zIndex: isSaving ? 50 : index,
                        transition: isSaving
                          ? `transform ${SAVE_ANIM_MS}ms cubic-bezier(0.4, 0, 1, 1), opacity ${SAVE_ANIM_MS * 0.8}ms ease`
                          : 'transform 0.2s ease, opacity 0.2s ease',
                      }}
                    />
                  </TinderCard>
                )
              })}
            </div>
          </div>

          {/* Actions live OUTSIDE feedContent so overflow:hidden never clips them */}
          <div style={styles.actions}>
            <ActionBtn
              onClick={handleUndo}
              color="#8888a0"
              label="Undo"
              disabled={swipeHistory.length === 0}
            >↩</ActionBtn>
            <ActionBtn onClick={handleBookmark} color="#6366f1" label="Bookmark">🔖</ActionBtn>
          </div>

          <p style={styles.hint} className="feed-hint">← / J pass &nbsp;·&nbsp; → / L save &nbsp;·&nbsp; Z undo</p>
        </>
      ) : view === 'liked' ? (
        <SavedList
          company={company}
          onRemove={handleRemoveFromSaved}
        />
      ) : (
        <BookmarksList
          company={company}
          onRemove={handleRemoveFromBookmarks}
        />
      )}

      <BottomNav view={view} setView={setView} savedCount={savedCount} bookmarkCount={bookmarkCount} />

      {/* Detail modal */}
      {expandedCard && (
        <DetailModal
          card={expandedCard}
          onClose={() => setExpandedCard(null)}
          onPass={() => { swipe('left'); setExpandedCard(null) }}
          onSave={() => { handleSave(expandedCard); setExpandedCard(null) }}
        />
      )}
    </div>
  )
}

function BottomNav({ view, setView, savedCount, bookmarkCount }) {
  return (
    <div style={styles.bottomNav}>
      <button
        onClick={() => setView('feed')}
        style={{ ...styles.navTab, ...(view === 'feed' ? styles.navTabActive : {}) }}
      >
        Feed
      </button>
      <button
        onClick={() => setView('liked')}
        style={{ ...styles.navTab, ...(view === 'liked' ? styles.navTabActive : {}) }}
      >
        Liked{savedCount > 0 ? ` (${savedCount})` : ''}
      </button>
      <button
        onClick={() => setView('bookmarks')}
        style={{ ...styles.navTab, ...(view === 'bookmarks' ? styles.navTabActive : {}) }}
      >
        Bookmarks{bookmarkCount > 0 ? ` (${bookmarkCount})` : ''}
      </button>
    </div>
  )
}

function ActionBtn({ onClick, color, label, disabled, children }) {
  return (
    <button
      onClick={onClick}
      title={label}
      disabled={disabled}
      style={{
        width: '52px', height: '52px',
        borderRadius: '50%',
        background: disabled ? 'var(--surface2)' : color + '22',
        color: disabled ? 'var(--border)' : color,
        border: `2px solid ${disabled ? 'var(--border)' : color + '44'}`,
        fontSize: '18px', fontWeight: '700',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        transition: 'all 0.15s',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {children}
    </button>
  )
}

const styles = {
  pageShell: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  feedContent: {
    position: 'relative',
    flex: 1,
    minHeight: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '20px 20px 0',
    gap: '16px',
    // No overflow:hidden here — pageShell clips swipe animations at viewport edge.
    // overflow:hidden on feedContent was clipping the card footer/Details button.
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
    fontSize: '12px', color: 'var(--muted)',
    background: 'var(--surface)', padding: '4px 10px',
    borderRadius: '20px', border: '1px solid var(--border)',
  },
  deck: {
    position: 'relative',
    width: 'var(--card-width)',
    height: 'var(--card-height)',
    flexShrink: 0,
  },
  actions: {
    display: 'flex',
    gap: '20px',
    alignItems: 'center',
  },
  hint: {
    fontSize: '11px', color: 'var(--border)', paddingBottom: '8px',
  },

  // Bottom nav
  bottomNav: {
    flexShrink: 0,
    display: 'flex',
    borderTop: '1px solid var(--border)',
    background: 'var(--surface)',
  },
  navTab: {
    flex: 1,
    padding: '14px',
    fontSize: '14px', fontWeight: '600',
    background: 'none', border: 'none',
    color: 'var(--muted)', cursor: 'pointer',
    borderTop: '2px solid transparent',
    transition: 'color 0.15s',
  },
  navTabActive: {
    color: 'var(--primary)',
    borderTop: '2px solid var(--primary)',
  },

  // Shared states
  centered: {
    flex: 1,
    display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center',
    gap: '8px', padding: '24px',
  },
  spinner: {
    width: '32px', height: '32px',
    border: '3px solid var(--border)',
    borderTop: '3px solid var(--primary)',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  refreshBtn: {
    marginTop: '16px',
    background: 'var(--primary)', color: '#fff',
    borderRadius: '10px', padding: '10px 20px',
    fontSize: '14px', fontWeight: '600', border: 'none', cursor: 'pointer',
  },
}
