import { useState } from 'react'
import { supabase } from '../lib/supabase'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSignup, setIsSignup] = useState(false)
  const [companyName, setCompanyName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setMessage('')
    setLoading(true)

    try {
      if (isSignup) {
        // 1. Create auth user
        const { data: authData, error: authError } = await supabase.auth.signUp({ email, password })
        if (authError) throw authError

        const userId = authData.user?.id
        if (!userId) throw new Error('Signup failed — no user returned')

        // 2. Create company record
        const { data: company, error: companyError } = await supabase
          .from('companies')
          .insert({ name: companyName, onboarding_complete: false, onboarding_step: 1 })
          .select()
          .single()
        if (companyError) throw companyError

        // 3. Create user record linked to company
        const { error: userError } = await supabase
          .from('users')
          .insert({ id: userId, company_id: company.id, email, role: 'admin' })
        if (userError) throw userError

        setMessage('Account created! Check your email to confirm, then sign in.')
      } else {
        const { error: signInError } = await supabase.auth.signInWithPassword({ email, password })
        if (signInError) throw signInError
        // App.jsx auth listener will redirect
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.logo}>
          <span style={styles.logoIcon}>⚡</span>
          <span style={styles.logoText}>GovScroll</span>
        </div>
        <p style={styles.tagline}>Federal contracts, feed-style.</p>

        <form onSubmit={handleSubmit} style={styles.form}>
          {isSignup && (
            <div style={styles.field}>
              <label style={styles.label}>Company name</label>
              <input
                type="text"
                placeholder="Acme Defense Solutions"
                value={companyName}
                onChange={e => setCompanyName(e.target.value)}
                required
              />
            </div>
          )}
          <div style={styles.field}>
            <label style={styles.label}>Email</label>
            <input
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
          </div>
          <div style={styles.field}>
            <label style={styles.label}>Password</label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          {error && <p style={styles.error}>{error}</p>}
          {message && <p style={styles.success}>{message}</p>}

          <button type="submit" style={styles.btn} disabled={loading}>
            {loading ? 'Working...' : isSignup ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <p style={styles.toggle}>
          {isSignup ? 'Already have an account? ' : "Don't have an account? "}
          <button style={styles.link} onClick={() => { setIsSignup(!isSignup); setError(''); setMessage('') }}>
            {isSignup ? 'Sign in' : 'Sign up'}
          </button>
        </p>
      </div>
    </div>
  )
}

const styles = {
  page: {
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '24px',
  },
  card: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '40px',
    width: '100%',
    maxWidth: '420px',
    textAlign: 'center',
  },
  logo: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginBottom: '8px' },
  logoIcon: { fontSize: '28px' },
  logoText: { fontSize: '24px', fontWeight: '700', color: 'var(--text)' },
  tagline: { color: 'var(--muted)', marginBottom: '32px', fontSize: '14px' },
  form: { display: 'flex', flexDirection: 'column', gap: '16px', textAlign: 'left' },
  field: { display: 'flex', flexDirection: 'column', gap: '6px' },
  label: { fontSize: '13px', color: 'var(--muted)', fontWeight: '500' },
  error: { color: 'var(--red)', fontSize: '13px', textAlign: 'center' },
  success: { color: 'var(--green)', fontSize: '13px', textAlign: 'center' },
  btn: {
    background: 'var(--primary)',
    color: '#fff',
    padding: '13px',
    borderRadius: '10px',
    fontWeight: '600',
    fontSize: '15px',
    marginTop: '4px',
    transition: 'background 0.15s',
  },
  toggle: { marginTop: '20px', fontSize: '13px', color: 'var(--muted)' },
  link: { background: 'none', color: 'var(--primary)', fontWeight: '600', fontSize: '13px' },
}
