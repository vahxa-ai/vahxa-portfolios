import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorText, when, type CatalogApp, type Me } from '../api'

const STATUS_TEXT: Record<string, string> = {
  approved: 'Access granted',
  pending: 'Request pending',
  denied: 'Not approved',
  revoked: 'Access removed',
}

// One color per position in the catalog, so neighbouring apps never share one.
const HUES = [221, 160, 24, 262, 330, 190, 45]
const monogramColor = (i: number) => `hsl(${HUES[i % HUES.length]} 62% 46%)`

export default function AppsPage({ me }: { me: Me }) {
  const apps = useQuery({ queryKey: ['apps'], queryFn: api.apps, refetchInterval: 30_000 })
  const isAdmin = me.role === 'admin'
  const first = me.name || me.email.split('@')[0]

  return (
    <div className="stack" style={{ gap: 24 }}>
      <header className="page-head">
        <h1>Welcome, {first}</h1>
        <p>{isAdmin
          ? 'You are an admin, so every app is open to you. Review requests on the Admin page.'
          : 'These are the Vahxa apps. Request access to the ones you need; once an admin approves you, the app opens from here.'}</p>
      </header>

      {apps.isLoading ? <div className="loading">Loading apps…</div>
        : apps.isError ? <div className="notice error">{errorText(apps.error)}</div>
        : !apps.data?.length ? <div className="card empty">No apps have been added yet.</div>
        : (
          <div className="app-grid">
            {apps.data.map((a, i) => <AppCard key={a.id} app={a} me={me} color={monogramColor(i)} />)}
          </div>
        )}
    </div>
  )
}

function AppCard({ app, me, color }: { app: CatalogApp; me: Me; color: string }) {
  const qc = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [note, setNote] = useState('')
  const [name, setName] = useState(me.name)
  const refresh = () => qc.invalidateQueries({ queryKey: ['apps'] })

  const ask = useMutation({
    mutationFn: () => api.requestApp(app.id, note, name),
    onSuccess: () => { setAsking(false); setNote(''); refresh(); qc.invalidateQueries({ queryKey: ['me'] }) },
  })
  const withdraw = useMutation({ mutationFn: () => api.withdraw(app.id), onSuccess: refresh })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    ask.mutate()
  }

  const status = app.status
  return (
    <article className="app-card">
      <div className="app-top">
        <span className="monogram" style={{ background: color }} aria-hidden>{app.name.charAt(0)}</span>
        <div className="app-title">
          <h3>{app.name}</h3>
          {app.project && <div className="muted small">{app.project}</div>}
        </div>
        {status && <span className={`pill ${me.role === 'admin' ? 'admin' : status}`}>{me.role === 'admin' ? 'Admin' : STATUS_TEXT[status]}</span>}
      </div>
      <p className="app-desc">{app.description || 'No description yet.'}</p>

      <div className="app-foot">
        {status === 'approved' && app.url ? (
          <>
            <span className="muted small">{app.access?.decided_at ? `Approved ${when(app.access.decided_at)}` : ''}</span>
            <a className="btn primary" href={app.url} target="_blank" rel="noopener noreferrer">Open app <span aria-hidden>↗</span></a>
          </>
        ) : status === 'pending' ? (
          <>
            <span className="muted small">Requested {when(app.access?.requested_at)}</span>
            <button className="btn sm" onClick={() => withdraw.mutate()} disabled={withdraw.isPending}>Withdraw</button>
          </>
        ) : asking ? (
          <form className="request-form" style={{ width: '100%' }} onSubmit={submit}>
            {!me.name && (
              <label className="field"><span>Your name</span>
                <input value={name} onChange={e => setName(e.target.value)} maxLength={100} autoComplete="name" />
              </label>
            )}
            <label className="field"><span>Why do you need it? <span className="muted">(optional)</span></span>
              <textarea rows={2} value={note} onChange={e => setNote(e.target.value)} maxLength={1000} autoFocus />
            </label>
            {ask.isError && <div className="notice error">{errorText(ask.error)}</div>}
            <div className="actions">
              <button className="btn primary" type="submit" disabled={ask.isPending}>{ask.isPending ? 'Sending…' : 'Send request'}</button>
              <button className="btn" type="button" onClick={() => setAsking(false)}>Cancel</button>
            </div>
          </form>
        ) : (
          <>
            <span className="muted small">
              {status === 'denied' ? `Declined ${when(app.access?.decided_at)}`
                : status === 'revoked' ? `Removed ${when(app.access?.decided_at)}` : 'Approval needed'}
            </span>
            <button className="btn primary" onClick={() => setAsking(true)}>
              {status ? 'Request again' : 'Request access'}
            </button>
          </>
        )}
        {withdraw.isError && <div className="notice error">{errorText(withdraw.error)}</div>}
      </div>
    </article>
  )
}
