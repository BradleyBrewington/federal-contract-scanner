import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { supabase } from '../lib/supabase'

export default function Login() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [isSignup, setIsSignup] = useState(searchParams.get('mode') === 'signup')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  // Redirect if already authenticated
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) navigate('/app', { replace: true })
    })
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setMessage('')
    setLoading(true)

    try {
      if (isSignup) {
        const { data: authData, error: authError } = await supabase.auth.signUp({ email, password })
        if (authError) throw authError

        const userId = authData.user?.id
        if (!userId) throw new Error('Signup failed — no user returned')

        const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:5001'
        const res = await fetch(`${apiUrl}/api/v2/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, email, company_name: companyName }),
        })
        const result = await res.json()
        if (!res.ok) throw new Error(result.error || 'Failed to create company profile')

        setMessage('Account created! Taking you to setup...')
        setTimeout(() => navigate('/app', { replace: true }), 800)
      } else {
        const { error: signInError } = await supabase.auth.signInWithPassword({ email, password })
        if (signInError) throw signInError
        navigate('/app', { replace: true })
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={s.page}>
      {/* Minimal nav — same look as landing */}
      <nav style={s.nav}>
        <Link to="/" style={s.logo}>
          <span style={s.logoIcon}>⚡</span>
          <span style={s.logoText}>GovScroll</span>
        </Link>
        <Link to="/" style={s.backLink}>← Back</Link>
      </nav>

      {/* Form */}
      <div style={s.body}>
        <div style={s.card}>
          <h2 style={s.heading}>{isSignup ? 'Create your account' : 'Welcome back'}</h2>
          <p style={s.sub}>{isSignup ? 'Start finding contracts in under two minutes.' : 'Sign in to your GovScroll account.'}</p>

          <form onSubmit={handleSubmit} style={s.form}>
            {isSignup && (
              <div style={s.field}>
                <label style={s.label}>Company name</label>
                <input
                  type="text"
                  placeholder="Acme Defense Solutions"
                  value={companyName}
                  onChange={e => setCompanyName(e.target.value)}
                  required
                />
              </div>
            )}
            <div style={s.field}>
              <label style={s.label}>Email</label>
              <input
                type="email"
                placeholder="you@company.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
              />
            </div>
            <div style={s.field}>
              <label style={s.label}>Password</label>
              <input
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>

            {error && <p style={s.error}>{error}</p>}
            {message && <p style={s.success}>{message}</p>}

            <button type="submit" style={s.btn} disabled={loading}>
              {loading ? 'Working...' : isSignup ? 'Create account' : 'Sign in'}
            </button>
          </form>

          <p style={s.toggle}>
            {isSignup ? 'Already have an account? ' : "Don't have an account? "}
            <button style={s.link} onClick={() => { setIsSignup(!isSignup); setError(''); setMessage('') }}>
              {isSignup ? 'Sign in' : 'Sign up free'}
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}

const s = {
  page: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--bg)',
    overflowY: 'auto',
  },
  nav: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 32px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface)',
    flexShrink: 0,
  },
  logo: {
    display: 'flex', alignItems: 'center', gap: '8px',
    textDecoration: 'none', color: 'var(--text)',
  },
  logoIcon: { fontSize: '20px' },
  logoText: { fontSize: '18px', fontWeight: '700', color: 'var(--text)' },
  backLink: {
    fontSize: '13px', color: 'var(--muted)',
    textDecoration: 'none', fontWeight: '500',
  },
  body: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '40px 24px',
  },
  card: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: '16px',
    padding: '40px',
    width: '100%',
    maxWidth: '420px',
  },
  heading: { fontSize: '22px', fontWeight: '700', color: 'var(--text)', marginBottom: '6px' },
  sub: { fontSize: '14px', color: 'var(--muted)', marginBottom: '28px', lineHeight: '1.5' },
  form: { display: 'flex', flexDirection: 'column', gap: '16px' },
  field: { display: 'flex', flexDirection: 'column', gap: '6px' },
  label: { fontSize: '13px', color: 'var(--muted)', fontWeight: '500' },
  error: { color: 'var(--red)', fontSize: '13px', textAlign: 'center' },
  success: { color: 'var(--green)', fontSize: '13px', textAlign: 'center' },
  btn: {
    background: 'var(--primary)',
    color: '#fff',
    padding: '13px',
    borderRadius: '10px',
    fontWeight: '700',
    fontSize: '15px',
    marginTop: '4px',
    border: 'none',
    cursor: 'pointer',
    letterSpacing: '-0.01em',
  },
  toggle: { marginTop: '20px', fontSize: '13px', color: 'var(--muted)', textAlign: 'center' },
  link: {
    background: 'none', border: 'none',
    color: 'var(--primary)', fontWeight: '600', fontSize: '13px',
    cursor: 'pointer',
  },
}
