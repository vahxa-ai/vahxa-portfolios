import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api, errorText, SIGN_OUT_URL, type Me } from './api'
import AccessPage from './pages/AccessPage'
import AppsPage from './pages/AppsPage'

const AdminPage = lazy(() => import('./pages/AdminPage'))

/** Approved people get the portal; everyone else gets the request-access page. */
export default function App() {
  const me = useQuery({
    queryKey: ['me'],
    queryFn: api.me,
    // While waiting for approval, check every 20 s so the portal opens as soon as it's granted.
    refetchInterval: q => (q.state.data && q.state.data.status !== 'approved' ? 20_000 : 60_000),
  })
  if (me.isLoading) return <div className="loading" style={{ padding: 24 }}>Loading…</div>
  if (me.isError || !me.data) {
    return <main><div className="notice error">Couldn't load your account: {errorText(me.error)}</div></main>
  }
  if (me.data.status !== 'approved') return <AccessPage me={me.data} />
  return <Shell me={me.data} />
}

function Shell({ me }: { me: Me }) {
  const isAdmin = me.role === 'admin'
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand"><span className="brand-mark" aria-hidden>V</span>Vahxa <span>Portfolios</span></Link>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>Apps</NavLink>
          {isAdmin && (
            <NavLink to="/admin" className={({ isActive }) => (isActive ? 'active' : '')}>
              Admin{me.pending_requests > 0 && <span className="count" title="Requests waiting">{me.pending_requests}</span>}
            </NavLink>
          )}
        </nav>
        <div className="user">
          <span className="user-email" title={me.email}>{me.email}</span>
          {me.auth_enabled && <a href={SIGN_OUT_URL}>Sign out</a>}
        </div>
      </header>
      <main>
        <Suspense fallback={<div className="loading">Loading…</div>}>
          <Routes>
            <Route path="/" element={<AppsPage me={me} />} />
            {isAdmin && <Route path="/admin" element={<AdminPage me={me} />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </main>
    </>
  )
}
