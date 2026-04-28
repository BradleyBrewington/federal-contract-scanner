import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import Onboarding from './Onboarding'
import Feed from './Feed'
import ProfileModal from '../components/ProfileModal'

export default function AppShell() {
  const navigate = useNavigate()
  const [session, setSession] = useState(undefined)  // undefined = loading
  const [user, setUser] = useState(null)
  const [company, setCompany] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showProfile, setShowProfile] = useState(false)

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
      if (session) loadUserData(session.user.id, session.user)
      else { setLoading(false); navigate('/') }
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session)
      if (session) loadUserData(session.user.id, session.user)
      else { setUser(null); setCompany(null); setLoading(false); navigate('/') }
    })

    return () => subscription.unsubscribe()
  }, [])

  async function loadUserData(userId, authUser = null) {
    setLoading(true)
    try {
      const { data: userData } = await supabase
        .from('users')
        .select('*, companies(*)')
        .eq('id', userId)
        .maybeSingle()

      if (userData) {
        setUser(userData)
        setCompany(userData.companies)
      } else {
        setUser(authUser)
        setCompany(null)
      }
    } catch (err) {
      console.error('Failed to load user data:', err)
      setUser(authUser)
    } finally {
      setLoading(false)
    }
  }

  async function handleSignOut() {
    await supabase.auth.signOut()
    // navigate('/') handled by auth state change listener
  }

  function handleOnboardingComplete() {
    if (session) loadUserData(session.user.id)
  }

  if (session === undefined || loading) {
    return (
      <div style={s.loadingPage}>
        <div style={s.spinner} />
      </div>
    )
  }

  if (!session) return null  // navigating to '/' via listener

  if (!company?.onboarding_complete) {
    return <Onboarding user={user} company={company} onComplete={handleOnboardingComplete} />
  }

  return (
    <div style={s.shell}>
      <nav style={s.nav}>
        <div style={s.navLogo}>
          <span>⚡</span>
          <span style={s.navLogoText}>GovScroll</span>
        </div>
        <div style={s.navRight}>
          <button style={s.companyBtn} onClick={() => setShowProfile(true)}>{company?.name}</button>
          <button style={s.signOutBtn} onClick={handleSignOut}>Sign out</button>
        </div>
      </nav>

      <main style={s.main}>
        <Feed user={user} company={company} />
      </main>

      {showProfile && (
        <ProfileModal company={company} onClose={() => setShowProfile(false)} />
      )}
    </div>
  )
}

const s = {
  loadingPage: {
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  spinner: {
    width: '36px', height: '36px',
    border: '3px solid var(--surface2)',
    borderTop: '3px solid var(--primary)',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
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
  companyBtn: {
    background: 'none', border: 'none',
    fontSize: '13px', color: 'var(--muted)',
    cursor: 'pointer', padding: '6px 8px',
    borderRadius: '6px',
  },
  signOutBtn: {
    background: 'var(--surface2)',
    color: 'var(--muted)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '6px 12px',
    fontSize: '12px',
  },
  main: { flex: 1, overflow: 'hidden' },
}
