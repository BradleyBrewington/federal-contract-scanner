import { useEffect, useState } from 'react'
import { supabase } from './lib/supabase'
import Login from './pages/Login'
import Onboarding from './pages/Onboarding'
import Feed from './pages/Feed'

export default function App() {
  const [session, setSession] = useState(undefined)  // undefined = loading
  const [user, setUser] = useState(null)
  const [company, setCompany] = useState(null)
  const [loading, setLoading] = useState(true)

  // Listen to auth state changes
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
      if (session) loadUserData(session.user.id)
      else setLoading(false)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session)
      if (session) loadUserData(session.user.id)
      else { setUser(null); setCompany(null); setLoading(false) }
    })

    return () => subscription.unsubscribe()
  }, [])

  async function loadUserData(userId) {
    setLoading(true)
    try {
      const { data: userData } = await supabase
        .from('users')
        .select('*, companies(*)')
        .eq('id', userId)
        .single()

      if (userData) {
        setUser(userData)
        setCompany(userData.companies)
      }
    } catch (err) {
      console.error('Failed to load user data:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleSignOut() {
    await supabase.auth.signOut()
  }

  function handleOnboardingComplete() {
    // Reload company data to pick up onboarding_complete = true
    if (session) loadUserData(session.user.id)
  }

  // Still loading auth state
  if (session === undefined || loading) {
    return (
      <div style={loadingStyles.page}>
        <div style={loadingStyles.spinner} />
      </div>
    )
  }

  // Not logged in
  if (!session) return <Login />

  // Logged in but onboarding not complete
  if (!company?.onboarding_complete) {
    return <Onboarding user={user} company={company} onComplete={handleOnboardingComplete} />
  }

  // Fully onboarded — show the feed
  return (
    <div style={appStyles.shell}>
      {/* Nav */}
      <nav style={appStyles.nav}>
        <div style={appStyles.navLogo}>
          <span>⚡</span>
          <span style={appStyles.navLogoText}>GovScroll</span>
        </div>
        <div style={appStyles.navRight}>
          <span style={appStyles.companyName}>{company?.name}</span>
          <button style={appStyles.signOutBtn} onClick={handleSignOut}>Sign out</button>
        </div>
      </nav>

      {/* Onboarding nudge if profile is incomplete */}
      {company && !company.onboarding_complete && (
        <div style={appStyles.nudge}>
          Your feed is partially tuned.{' '}
          <button style={appStyles.nudgeLink} onClick={() => setCompany(c => ({ ...c, onboarding_complete: false }))}>
            Finish setup →
          </button>
        </div>
      )}

      {/* Main content */}
      <main style={appStyles.main}>
        <Feed user={user} company={company} />
      </main>
    </div>
  )
}

const loadingStyles = {
  page: {
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  spinner: {
    width: '36px',
    height: '36px',
    border: '3px solid #2a2a3d',
    borderTop: '3px solid #6366f1',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
}

const appStyles = {
  shell: { height: '100%', display: 'flex', flexDirection: 'column' },
  nav: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 20px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface)',
    flexShrink: 0,
  },
  navLogo: { display: 'flex', alignItems: 'center', gap: '6px', fontSize: '18px', fontWeight: '700' },
  navLogoText: { color: 'var(--text)' },
  navRight: { display: 'flex', alignItems: 'center', gap: '14px' },
  companyName: { fontSize: '13px', color: 'var(--muted)' },
  signOutBtn: {
    background: 'var(--surface2)',
    color: 'var(--muted)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '6px 12px',
    fontSize: '12px',
  },
  nudge: {
    background: '#6366f122',
    borderBottom: '1px solid #6366f144',
    padding: '10px 20px',
    fontSize: '13px',
    color: 'var(--text)',
    textAlign: 'center',
  },
  nudgeLink: { background: 'none', color: 'var(--primary)', fontWeight: '600', fontSize: '13px' },
  main: { flex: 1, overflow: 'hidden' },
}
