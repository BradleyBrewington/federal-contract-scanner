import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'

function useMobile() {
  const [mobile, setMobile] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const fn = () => setMobile(window.innerWidth < 768)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return mobile
}

// ─── Demo media ────────────────────────────────────────────────────────────────
// Drop demo.mp4 into /public to replace the placeholder automatically.

function DemoMedia({ mobile }) {
  const [videoReady, setVideoReady] = useState(false)

  return (
    <div style={{
      width: '100%',
      maxWidth: mobile ? '100%' : '520px',
      flexShrink: 0,
      borderRadius: '16px',
      overflow: 'hidden',
      border: '1px solid var(--border)',
      background: 'var(--surface)',
      boxShadow: '0 24px 80px rgba(0,0,0,0.5)',
      aspectRatio: '16/9',
      position: 'relative',
    }}>
      <video
        autoPlay loop muted playsInline
        onCanPlay={() => setVideoReady(true)}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: videoReady ? 'block' : 'none' }}
      >
        <source src="/demo.mp4" type="video/mp4" />
      </video>

      {/* Placeholder — shows until video is ready */}
      {!videoReady && <AppPreview />}
    </div>
  )
}

function AppPreview() {
  return (
    <div style={{ width: '100%', height: '100%', background: 'var(--bg)', display: 'flex', flexDirection: 'column', padding: '16px', gap: '10px' }}>
      {/* Mini nav */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text)' }}>⚡ GovScroll</span>
        <span style={{ fontSize: '10px', color: 'var(--muted)', background: 'var(--surface)', padding: '2px 8px', borderRadius: '10px', border: '1px solid var(--border)' }}>14 reviewed today</span>
      </div>

      {/* Stacked cards */}
      <div style={{ flex: 1, position: 'relative' }}>
        {/* Back card */}
        <div style={{ position: 'absolute', inset: '8px 12px 0', background: 'var(--surface2)', borderRadius: '10px', border: '1px solid var(--border)', transform: 'scale(0.96) translateY(6px)', transformOrigin: 'bottom center' }} />
        {/* Front card */}
        <div style={{ position: 'relative', background: 'var(--surface)', borderRadius: '10px', border: '1px solid var(--border)', padding: '14px', height: '100%' }}>
          <div style={{ fontSize: '9px', fontWeight: '700', color: 'var(--muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '6px' }}>Dept. of Defense · 541512</div>
          <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text)', lineHeight: '1.3', marginBottom: '10px' }}>Cybersecurity Operations Support Services</div>

          <div style={{ display: 'flex', gap: '6px', marginBottom: '10px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '9px', fontWeight: '700', color: '#a5b4fc', background: 'rgba(99,102,241,0.12)', border: '1px solid rgba(99,102,241,0.25)', borderRadius: '4px', padding: '2px 6px' }}>Score 91</span>
            <span style={{ fontSize: '9px', color: '#22c55e', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: '4px', padding: '2px 6px' }}>Small Business</span>
            <span style={{ fontSize: '9px', color: 'var(--muted)', background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: '4px', padding: '2px 6px' }}>14 days left</span>
          </div>

          {/* Score bar */}
          <div style={{ height: '3px', background: 'var(--surface2)', borderRadius: '2px', marginBottom: '10px' }}>
            <div style={{ width: '91%', height: '100%', background: 'linear-gradient(90deg, var(--primary), #a5b4fc)', borderRadius: '2px' }} />
          </div>

          <div style={{ fontSize: '10px', color: 'var(--muted)', lineHeight: '1.5' }}>
            Services to support ongoing cybersecurity operations, including threat monitoring, incident response, and vulnerability assessments...
          </div>
        </div>
      </div>

      {/* Swipe actions */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: '16px', paddingBottom: '4px' }}>
        <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'rgba(239,68,68,0.12)', border: '2px solid rgba(239,68,68,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px', color: '#ef4444' }}>✕</div>
        <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'rgba(99,102,241,0.12)', border: '2px solid rgba(99,102,241,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px', color: '#a5b4fc' }}>🔖</div>
        <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'rgba(34,197,94,0.12)', border: '2px solid rgba(34,197,94,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px', color: '#22c55e' }}>✓</div>
      </div>
    </div>
  )
}

// ─── Sections ──────────────────────────────────────────────────────────────────

function Nav() {
  return (
    <nav style={n.nav}>
      <Link to="/" style={n.logo}>
        <span style={n.icon}>⚡</span>
        <span style={n.wordmark}>GovScroll</span>
      </Link>
      <Link to="/login" style={n.signIn}>Sign in →</Link>
    </nav>
  )
}

const n = {
  nav: {
    position: 'sticky', top: 0, zIndex: 50,
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '0 32px',
    height: '64px',
    background: 'rgba(10,10,15,0.85)',
    backdropFilter: 'blur(12px)',
    borderBottom: '1px solid var(--border)',
  },
  logo: { display: 'flex', alignItems: 'center', gap: '8px', textDecoration: 'none' },
  icon: { fontSize: '22px' },
  wordmark: { fontSize: '18px', fontWeight: '700', color: 'var(--text)', letterSpacing: '-0.02em' },
  signIn: {
    fontSize: '13px', fontWeight: '600',
    color: 'var(--muted)', textDecoration: 'none',
    padding: '8px 16px',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    background: 'var(--surface)',
    transition: 'color 0.15s',
  },
}

function Hero({ mobile }) {
  const navigate = useNavigate()
  return (
    <section style={{ position: 'relative', overflow: 'hidden', padding: mobile ? '72px 24px 64px' : '120px 48px 100px' }}>
      {/* Background glow */}
      <div style={{ position: 'absolute', top: '-100px', left: '30%', width: '700px', height: '700px', background: 'radial-gradient(circle, rgba(99,102,241,0.07) 0%, transparent 65%)', pointerEvents: 'none' }} />

      <div style={{ maxWidth: '1100px', margin: '0 auto', display: 'flex', flexDirection: mobile ? 'column' : 'row', alignItems: 'center', gap: mobile ? '48px' : '72px' }}>
        {/* Text */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Badge */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', background: 'rgba(99,102,241,0.1)', border: '1px solid rgba(99,102,241,0.25)', borderRadius: '100px', padding: '5px 14px', marginBottom: '28px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#22c55e', display: 'inline-block', flexShrink: 0 }} />
            <span style={{ fontSize: '12px', fontWeight: '600', color: '#a5b4fc', letterSpacing: '0.02em' }}>Beta · Free to start</span>
          </div>

          <h1 style={{ fontSize: mobile ? '36px' : '56px', fontWeight: '700', lineHeight: 1.08, letterSpacing: '-0.03em', color: 'var(--text)', marginBottom: '24px' }}>
            Find federal contracts{' '}
            {mobile ? null : <br />}
            you'd miss with{' '}
            <span style={{ color: 'var(--primary)' }}>keyword search.</span>
          </h1>

          <p style={{ fontSize: mobile ? '16px' : '19px', color: 'var(--muted)', lineHeight: 1.65, marginBottom: '40px', maxWidth: '520px' }}>
            Set your profile once. Swipe through curated opportunities. Our matching learns what you actually want — including the contracts you didn't know to search for.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: '10px' }}>
            <button
              onClick={() => navigate('/login?mode=signup')}
              style={{ background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '12px', padding: '15px 32px', fontSize: '16px', fontWeight: '700', cursor: 'pointer', letterSpacing: '-0.01em', boxShadow: '0 4px 24px rgba(99,102,241,0.35)' }}
            >
              Get Started Free
            </button>
            <p style={{ fontSize: '12px', color: 'var(--muted)' }}>No credit card. Email signup. Two minutes to your first feed.</p>
          </div>
        </div>

        {/* Demo */}
        <DemoMedia mobile={mobile} />
      </div>
    </section>
  )
}

function Problem({ mobile }) {
  return (
    <section style={{ padding: mobile ? '64px 24px' : '80px 48px', borderTop: '1px solid var(--border)' }}>
      <div style={{ maxWidth: '780px', margin: '0 auto', textAlign: 'center' }}>
        <p style={{ fontSize: mobile ? '17px' : '22px', color: 'var(--muted)', lineHeight: 1.75, fontWeight: '400' }}>
          <span style={{ color: 'var(--text)', fontWeight: '600' }}>SAM.gov has 30,000+ active opportunities.</span>
          {' '}Keyword search misses anything posted under a NAICS you don't watch, with terminology you don't use, or by an agency you've never won with. The contracts you don't find are the ones your competitors do.
        </p>
      </div>
    </section>
  )
}

function HowItWorks({ mobile }) {
  const steps = [
    {
      n: '1',
      title: 'Set your profile.',
      body: 'NAICS codes, keywords, exclusions. Two minutes.',
    },
    {
      n: '2',
      title: 'Swipe through opportunities.',
      body: 'Right to save, left to skip. Like Tinder, for contracts.',
    },
    {
      n: '3',
      title: 'Get smarter matches.',
      body: 'The more you swipe, the better the algorithm gets.',
    },
  ]

  return (
    <section style={{ padding: mobile ? '64px 24px' : '96px 48px', borderTop: '1px solid var(--border)' }}>
      <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
        <SectionLabel>How It Works</SectionLabel>
        <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1fr' : 'repeat(3, 1fr)', gap: '20px', marginTop: '40px' }}>
          {steps.map(step => (
            <div key={step.n} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '14px', padding: '28px 24px' }}>
              <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'rgba(99,102,241,0.12)', border: '1px solid rgba(99,102,241,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', fontWeight: '700', color: 'var(--primary)', marginBottom: '20px' }}>
                {step.n}
              </div>
              <h3 style={{ fontSize: '17px', fontWeight: '700', color: 'var(--text)', marginBottom: '8px', letterSpacing: '-0.02em' }}>{step.title}</h3>
              <p style={{ fontSize: '15px', color: 'var(--muted)', lineHeight: 1.6 }}>{step.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function Differentiators({ mobile }) {
  const items = [
    {
      title: 'Discovery, not just search.',
      body: 'Keyword search shows you what you asked for. Our algorithm shows you what you\'d want if you knew to ask. Right-swiped contracts in adjacent categories train the system to surface opportunities you\'d never type into a search bar.',
    },
    {
      title: 'Built for small businesses.',
      body: 'Built by a small business federal contractor, for small business federal contractors. No 50-seat enterprise license. No sales call. Sign up and start swiping in under two minutes.',
    },
    {
      title: 'Direct SAM.gov sourcing.',
      body: 'Every opportunity links directly to its official SAM.gov listing. No middleman, no stale data, no scraping. Sourced from the same federal database used by every legitimate procurement tool.',
    },
  ]

  return (
    <section style={{ padding: mobile ? '64px 24px' : '96px 48px', borderTop: '1px solid var(--border)', background: 'var(--surface)' }}>
      <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
        <SectionLabel>What Sets Us Apart</SectionLabel>
        <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1fr' : 'repeat(3, 1fr)', gap: '20px', marginTop: '40px' }}>
          {items.map(item => (
            <div key={item.title} style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: '14px', padding: '28px 24px' }}>
              <h3 style={{ fontSize: '17px', fontWeight: '700', color: 'var(--text)', marginBottom: '12px', letterSpacing: '-0.02em' }}>{item.title}</h3>
              <p style={{ fontSize: '15px', color: 'var(--muted)', lineHeight: 1.7 }}>{item.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function FAQItem({ q, a }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 0', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', gap: '16px' }}
      >
        <span style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text)', lineHeight: 1.4 }}>{q}</span>
        <span style={{ color: 'var(--muted)', fontSize: '20px', fontWeight: '300', transform: open ? 'rotate(45deg)' : 'none', transition: 'transform 0.2s', flexShrink: 0, lineHeight: 1 }}>+</span>
      </button>
      {open && (
        <p style={{ fontSize: '15px', color: 'var(--muted)', lineHeight: 1.7, paddingBottom: '20px' }}>{a}</p>
      )}
    </div>
  )
}

function FAQ({ mobile }) {
  const items = [
    {
      q: 'Is it really free?',
      a: 'Yes, free during beta. We\'ll add paid tiers later but beta users get permanent access to the free tier.',
    },
    {
      q: 'Where does the data come from?',
      a: 'Directly from SAM.gov, the official federal opportunity database. We sync daily.',
    },
    {
      q: 'Do I need a SAM.gov registration to use this?',
      a: 'No. You can browse and save opportunities without a SAM registration. You\'ll need one to actually bid.',
    },
    {
      q: 'What happens to my swipe data?',
      a: 'We use it to improve your matches. We don\'t sell individual user data. Aggregate trends may be shared with research partners.',
    },
    {
      q: 'I already use HigherGov, GovTribe, or similar tools. Why switch?',
      a: 'You don\'t have to switch. Most users layer this on top of existing tools. We\'re better at discovery; they\'re better at deep research.',
    },
    {
      q: 'How is this different from searching SAM.gov directly?',
      a: 'SAM.gov search returns what you ask for. GovScroll\'s algorithm surfaces opportunities that match your behavior — including ones you wouldn\'t have thought to search for.',
    },
  ]

  return (
    <section style={{ padding: mobile ? '64px 24px' : '96px 48px', borderTop: '1px solid var(--border)' }}>
      <div style={{ maxWidth: '720px', margin: '0 auto' }}>
        <SectionLabel>Frequently Asked Questions</SectionLabel>
        <div style={{ marginTop: '40px' }}>
          {items.map(item => <FAQItem key={item.q} q={item.q} a={item.a} />)}
        </div>
      </div>
    </section>
  )
}

function FinalCTA({ mobile }) {
  const navigate = useNavigate()
  return (
    <section style={{ padding: mobile ? '80px 24px' : '120px 48px', borderTop: '1px solid var(--border)', background: 'var(--surface)', textAlign: 'center' }}>
      <div style={{ maxWidth: '560px', margin: '0 auto' }}>
        <h2 style={{ fontSize: mobile ? '28px' : '40px', fontWeight: '700', color: 'var(--text)', letterSpacing: '-0.03em', marginBottom: '16px', lineHeight: 1.15 }}>
          Ready to find what you're missing?
        </h2>
        <p style={{ fontSize: '16px', color: 'var(--muted)', marginBottom: '36px', lineHeight: 1.6 }}>
          Free during beta. Email signup, no credit card.
        </p>
        <button
          onClick={() => navigate('/login?mode=signup')}
          style={{ background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '12px', padding: '16px 40px', fontSize: '17px', fontWeight: '700', cursor: 'pointer', letterSpacing: '-0.01em', boxShadow: '0 4px 24px rgba(99,102,241,0.35)' }}
        >
          Get Started Free
        </button>
      </div>
    </section>
  )
}

function Footer({ mobile }) {
  return (
    <footer style={{ padding: mobile ? '32px 24px' : '40px 48px', borderTop: '1px solid var(--border)', background: 'var(--bg)' }}>
      <div style={{ maxWidth: '1100px', margin: '0 auto', display: 'flex', flexDirection: mobile ? 'column' : 'row', alignItems: mobile ? 'flex-start' : 'center', justifyContent: 'space-between', gap: '16px' }}>
        <span style={{ fontSize: '13px', color: 'var(--muted)' }}>© 2026 Icarus Dynamics LLC. All rights reserved.</span>
        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
          <a href="/privacy" style={{ fontSize: '13px', color: 'var(--muted)', textDecoration: 'none' }}>Privacy Policy</a>
          <a href="/terms" style={{ fontSize: '13px', color: 'var(--muted)', textDecoration: 'none' }}>Terms of Service</a>
          <a href="mailto:hello@icarusdynamicsllc.com" style={{ fontSize: '13px', color: 'var(--muted)', textDecoration: 'none' }}>hello@icarusdynamicsllc.com</a>
        </div>
      </div>
    </footer>
  )
}

function SectionLabel({ children }) {
  return (
    <p style={{ fontSize: '12px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--primary)', marginBottom: '8px' }}>
      {children}
    </p>
  )
}

// ─── Root ──────────────────────────────────────────────────────────────────────

export default function Landing() {
  const mobile = useMobile()

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg)' }}>
      <Nav />
      <Hero mobile={mobile} />
      <Problem mobile={mobile} />
      <HowItWorks mobile={mobile} />
      <Differentiators mobile={mobile} />
      <FAQ mobile={mobile} />
      <FinalCTA mobile={mobile} />
      <Footer mobile={mobile} />
    </div>
  )
}
