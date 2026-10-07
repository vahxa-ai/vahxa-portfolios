import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api, errorText, SIGN_OUT_URL } from './api'
import AppsPage from './pages/AppsPage'

const AdminPage = lazy(() => import('./pages/AdminPage'))

export default function App() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, refetchInterval: 60_000 })
  if (me.isLoading) return <div className="loading" style={{ padding: 24 }}>Loading…</div>
  if (me.isError || !me.data) {
    return <main><div className="notice error">Couldn't load your account: {errorText(me.error)}</div></main>
  }
  const isAdmin = me.data.role === 'admin'

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand"><span className="brand-mark" aria-hidden>V</span>Vahxa <span>Portfolios</span></Link>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>Apps</NavLink>
          {isAdmin && (
            <NavLink to="/admin" className={({ isActive }) => (isActive ? 'active' : '')}>
              Admin{me.data.pending_requests > 0 && <span className="count" title="Requests waiting">{me.data.pending_requests}</span>}
            </NavLink>
          )}
        </nav>
        <div className="user">
          <span className="user-email" title={me.data.email}>{me.data.email}</span>
          {me.data.auth_enabled && <a href={SIGN_OUT_URL}>Sign out</a>}
        </div>
      </header>
      <main>
        <Suspense fallback={<div className="loading">Loading…</div>}>
          <Routes>
            <Route path="/" element={<AppsPage me={me.data} />} />
            {isAdmin && <Route path="/admin" element={<AdminPage me={me.data} />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </main>
    </>
  )
}
