import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorText, when, type AccessStatus, type AppDef, type Me, type Person } from '../api'

type Tab = 'people' | 'apps'

export default function AdminPage({ me }: { me: Me }) {
  const [tab, setTab] = useState<Tab>('people')
  return (
    <div className="stack" style={{ gap: 20 }}>
      <header className="page-head">
        <h1>Admin</h1>
        <p>Approve who can use the portal and keep the app list up to date. Access inside each app is
          approved in that app.</p>
      </header>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'people'} className={tab === 'people' ? 'on' : ''} onClick={() => setTab('people')}>
          People{me.pending_requests > 0 && <span className="count">{me.pending_requests}</span>}
        </button>
        <button role="tab" aria-selected={tab === 'apps'} className={tab === 'apps' ? 'on' : ''} onClick={() => setTab('apps')}>Apps</button>
      </div>
      {tab === 'people' ? <People me={me} /> : <Apps />}
    </div>
  )
}

/** Refresh everything a change can affect. */
function useRefresh() {
  const qc = useQueryClient()
  return () => ['people', 'me', 'apps', 'appDefs'].forEach(k => qc.invalidateQueries({ queryKey: [k] }))
}

// ------------------------------------------------------------------ people
const FILTERS: (AccessStatus | 'all')[] = ['all', 'approved', 'denied', 'revoked']
const STATUS_LABEL: Record<string, string> = {
  pending: 'Waiting', approved: 'Approved', denied: 'Denied', revoked: 'Revoked',
}

function People({ me }: { me: Me }) {
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, refetchInterval: 20_000 })
  const [filter, setFilter] = useState<AccessStatus | 'all'>('all')
  const refresh = useRefresh()
  const decide = useMutation({
    mutationFn: ({ email, status }: { email: string; status: 'approved' | 'denied' | 'revoked' }) => api.decide(email, status),
    onSuccess: refresh,
  })
  const setRole = useMutation({
    mutationFn: ({ email, role }: { email: string; role: 'user' | 'admin' }) => api.setRole(email, role),
    onSuccess: refresh,
  })

  if (people.isLoading) return <div className="loading">Loading…</div>
  if (people.isError) return <div className="notice error">{errorText(people.error)}</div>
  const all = people.data ?? []
  const pending = all.filter(p => p.status === 'pending')
  const others = all.filter(p => p.status !== 'pending' && (filter === 'all' || p.status === filter))
  const busy = decide.isPending || setRole.isPending
  const editable = (p: Person) => !p.permanent && p.email !== me.email

  return (
    <div className="stack">
      <section className="card">
        <h2>Waiting for a decision</h2>
        {!pending.length ? <div className="empty">No requests waiting.</div> : pending.map(p => (
          <div key={p.email} className="request-row">
            <div className="who">
              <strong>{p.name || p.email}</strong>{p.name && <span className="muted"> · {p.email}</span>}
              <div className="muted small">asked {when(p.requested_at)}</div>
              {p.reason && <p className="note">{p.reason}</p>}
            </div>
            <div className="actions">
              <button className="btn primary" disabled={busy} onClick={() => decide.mutate({ email: p.email, status: 'approved' })}>Approve</button>
              <button className="btn danger" disabled={busy} onClick={() => decide.mutate({ email: p.email, status: 'denied' })}>Deny</button>
            </div>
          </div>
        ))}
      </section>

      <InviteForm />

      <section className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Everyone</h2>
          <div className="segmented" role="group" aria-label="Filter by status">
            {FILTERS.map(f => (
              <button key={f} className={filter === f ? 'on' : ''} aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {f === 'all' ? 'All' : STATUS_LABEL[f]}
              </button>
            ))}
          </div>
        </div>
        {!others.length ? <div className="empty">Nobody here.</div> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Person</th><th>Access</th><th>Role</th><th>Last seen</th><th /></tr></thead>
              <tbody>
                {others.map(p => (
                  <tr key={p.email}>
                    <td><div>{p.email}</div>{p.name && <div className="muted small">{p.name}</div>}</td>
                    <td>
                      {p.status ? <span className={`pill ${p.status}`}>{STATUS_LABEL[p.status]}</span> : <span className="pill none">Never asked</span>}
                      {p.decided_by && <div className="muted small">by {p.decided_by}, {when(p.decided_at)}</div>}
                    </td>
                    <td><span className={`pill ${p.role}`}>{p.role}{p.permanent ? ' · permanent' : ''}</span></td>
                    <td className="small">{p.last_seen ? when(p.last_seen) : <span className="muted">never signed in</span>}</td>
                    <td className="actions">
                      {editable(p) && p.status === 'approved' && (p.role === 'admin'
                        ? <button className="btn sm" disabled={busy} onClick={() => setRole.mutate({ email: p.email, role: 'user' })}>Remove admin</button>
                        : <button className="btn sm" disabled={busy} onClick={() => setRole.mutate({ email: p.email, role: 'admin' })}>Make admin</button>)}
                      {editable(p) && p.status === 'approved' &&
                        <button className="btn sm danger" disabled={busy} onClick={() => decide.mutate({ email: p.email, status: 'revoked' })}>Revoke</button>}
                      {editable(p) && p.status !== 'approved' &&
                        <button className="btn sm" disabled={busy} onClick={() => decide.mutate({ email: p.email, status: 'approved' })}>Approve</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(decide.isError || setRole.isError) && <div className="notice error">{errorText(decide.error ?? setRole.error)}</div>}
      </section>
    </div>
  )
}

function InviteForm() {
  const [email, setEmail] = useState('')
  const refresh = useRefresh()
  const invite = useMutation({ mutationFn: () => api.invite(email.trim()), onSuccess: () => { setEmail(''); refresh() } })
  const submit = (e: FormEvent) => { e.preventDefault(); invite.mutate() }

  return (
    <section className="card">
      <h2>Approve someone in advance</h2>
      <p className="muted small" style={{ marginTop: -6 }}>No request needed: they go straight to the apps the first time they sign in with this Gmail address.</p>
      <form className="inline-form" onSubmit={submit}>
        <label className="field"><span>Gmail address</span>
          <input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="name@gmail.com" />
        </label>
        <button className="btn primary" type="submit" disabled={invite.isPending}>Approve</button>
      </form>
      {invite.isError && <div className="notice error" style={{ marginTop: 10 }}>{errorText(invite.error)}</div>}
      {invite.isSuccess && <div className="notice ok" style={{ marginTop: 10 }}>Approved.</div>}
    </section>
  )
}

// ------------------------------------------------------------------ app catalog
const BLANK: AppDef = { id: '', name: '', description: '', url: 'https://', project: '', order: 100 }

function Apps() {
  const apps = useQuery({ queryKey: ['appDefs'], queryFn: api.appDefs })
  const [editing, setEditing] = useState<{ app: AppDef; isNew: boolean } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const refresh = useRefresh()
  const remove = useMutation({ mutationFn: (id: string) => api.deleteApp(id), onSuccess: () => { setConfirmDelete(null); refresh() } })

  return (
    <div className="stack">
      {editing && <AppForm initial={editing.app} isNew={editing.isNew} onDone={() => setEditing(null)} />}
      <section className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Apps in the portal</h2>
          <button className="btn primary" onClick={() => setEditing({ app: BLANK, isNew: true })}>Add app</button>
        </div>
        {apps.isLoading ? <div className="loading">Loading…</div>
          : apps.isError ? <div className="notice error">{errorText(apps.error)}</div>
          : !apps.data?.length ? <div className="empty">No apps yet.</div>
          : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>App</th><th>Link</th><th>Project</th><th>Order</th><th /></tr></thead>
                <tbody>
                  {apps.data.map(a => (
                    <tr key={a.id}>
                      <td><strong>{a.name}</strong><div className="muted small">{a.id}</div></td>
                      <td className="small"><a href={a.url} target="_blank" rel="noopener noreferrer">{a.url.replace(/^https:\/\//, '')}</a></td>
                      <td className="small">{a.project || '–'}</td>
                      <td className="small">{a.order}</td>
                      <td className="actions">
                        {confirmDelete === a.id ? (
                          <>
                            <span className="small">Delete it and everyone's access to it?</span>{' '}
                            <button className="btn sm danger" disabled={remove.isPending} onClick={() => remove.mutate(a.id)}>Delete</button>
                            <button className="btn sm" onClick={() => setConfirmDelete(null)}>Cancel</button>
                          </>
                        ) : (
                          <>
                            <button className="btn sm" onClick={() => setEditing({ app: a, isNew: false })}>Edit</button>
                            <button className="btn sm danger" onClick={() => setConfirmDelete(a.id)}>Delete</button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {remove.isError && <div className="notice error">{errorText(remove.error)}</div>}
      </section>
    </div>
  )
}

function AppForm({ initial, isNew, onDone }: { initial: AppDef; isNew: boolean; onDone: () => void }) {
  const [app, setApp] = useState<AppDef>(initial)
  const refresh = useRefresh()
  const save = useMutation({
    mutationFn: () => (isNew ? api.createApp(app) : api.updateApp(app)),
    onSuccess: () => { refresh(); onDone() },
  })
  const set = (patch: Partial<AppDef>) => setApp(a => ({ ...a, ...patch }))
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate() }

  return (
    <section className="card">
      <h2>{isNew ? 'Add an app' : `Edit ${initial.name}`}</h2>
      <form className="app-form" onSubmit={submit}>
        <label className="field"><span>Name</span>
          <input required value={app.name} onChange={e => set({ name: e.target.value })} maxLength={80} />
        </label>
        <label className="field"><span>Id <span className="muted">(lowercase, can't change later)</span></span>
          <input required value={app.id} disabled={!isNew} pattern="[a-z0-9][a-z0-9\-]{1,39}"
                 onChange={e => set({ id: e.target.value.toLowerCase() })} />
        </label>
        <label className="field wide"><span>Link</span>
          <input type="url" required value={app.url} onChange={e => set({ url: e.target.value })} />
        </label>
        <label className="field wide"><span>Description</span>
          <textarea rows={2} value={app.description} onChange={e => set({ description: e.target.value })} maxLength={500} />
        </label>
        <label className="field"><span>GCP project</span>
          <input value={app.project} onChange={e => set({ project: e.target.value })} maxLength={100} />
        </label>
        <label className="field"><span>Order</span>
          <input type="number" min={0} max={10000} value={app.order} onChange={e => set({ order: Number(e.target.value) })} />
        </label>
        {save.isError && <div className="notice error wide">{errorText(save.error)}</div>}
        <div className="actions">
          <button className="btn primary" type="submit" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
          <button className="btn" type="button" onClick={onDone}>Cancel</button>
        </div>
      </form>
    </section>
  )
}
