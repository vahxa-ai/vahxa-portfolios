import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorText, when, type AccessRecord, type AccessStatus, type AppDef, type Me } from '../api'

type Tab = 'requests' | 'access' | 'people' | 'apps'

const TABS: [Tab, string][] = [['requests', 'Requests'], ['access', 'Access'], ['people', 'People'], ['apps', 'Apps']]

export default function AdminPage({ me }: { me: Me }) {
  const [tab, setTab] = useState<Tab>('requests')
  return (
    <div className="stack" style={{ gap: 20 }}>
      <header className="page-head">
        <h1>Admin</h1>
        <p>Approve who can use each app, manage admins and keep the app list up to date.</p>
      </header>
      <div className="tabs" role="tablist">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
            {label}{t === 'requests' && me.pending_requests > 0 && <span className="count">{me.pending_requests}</span>}
          </button>
        ))}
      </div>
      {tab === 'requests' && <Requests />}
      {tab === 'access' && <Access />}
      {tab === 'people' && <People me={me} />}
      {tab === 'apps' && <Apps />}
    </div>
  )
}

/** Refresh everything an access change affects. */
function useRefresh() {
  const qc = useQueryClient()
  return () => ['access', 'people', 'me', 'apps', 'appDefs'].forEach(k => qc.invalidateQueries({ queryKey: [k] }))
}

// ------------------------------------------------------------------ pending requests
function Requests() {
  const pending = useQuery({ queryKey: ['access', 'pending'], queryFn: () => api.access('pending'), refetchInterval: 20_000 })
  const refresh = useRefresh()
  const decide = useMutation({
    mutationFn: ({ r, status }: { r: AccessRecord; status: 'approved' | 'denied' }) => api.decide(r.app_id, r.email, status),
    onSuccess: refresh,
  })

  return (
    <div className="stack">
      <section className="card">
        <h2>Waiting for a decision</h2>
        {pending.isLoading ? <div className="loading">Loading…</div>
          : pending.isError ? <div className="notice error">{errorText(pending.error)}</div>
          : !pending.data?.length ? <div className="empty">No requests waiting.</div>
          : pending.data.map(r => (
            <div key={`${r.app_id}/${r.email}`} className="request-row">
              <div className="who">
                <strong>{r.name || r.email}</strong>{r.name && <span className="muted"> · {r.email}</span>}
                <div className="muted small">wants <b>{r.app_name}</b> · asked {when(r.requested_at)}</div>
                {r.note && <p className="note">{r.note}</p>}
              </div>
              <div className="actions">
                <button className="btn primary" disabled={decide.isPending} onClick={() => decide.mutate({ r, status: 'approved' })}>Approve</button>
                <button className="btn danger" disabled={decide.isPending} onClick={() => decide.mutate({ r, status: 'denied' })}>Deny</button>
              </div>
            </div>
          ))}
        {decide.isError && <div className="notice error">{errorText(decide.error)}</div>}
      </section>
      <GrantForm />
    </div>
  )
}

function GrantForm() {
  const apps = useQuery({ queryKey: ['appDefs'], queryFn: api.appDefs })
  const [email, setEmail] = useState('')
  const [appId, setAppId] = useState('')
  const refresh = useRefresh()
  const grant = useMutation({
    mutationFn: () => api.grant(email.trim(), appId || apps.data?.[0]?.id || ''),
    onSuccess: () => { setEmail(''); refresh() },
  })
  const submit = (e: FormEvent) => { e.preventDefault(); grant.mutate() }

  return (
    <section className="card">
      <h2>Give someone access</h2>
      <p className="muted small" style={{ marginTop: -6 }}>No request needed: the app shows up for them the next time they sign in with this Gmail address.</p>
      <form className="inline-form" onSubmit={submit}>
        <label className="field"><span>Gmail address</span>
          <input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="name@gmail.com" />
        </label>
        <label className="field"><span>App</span>
          <select value={appId || apps.data?.[0]?.id || ''} onChange={e => setAppId(e.target.value)}>
            {apps.data?.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
        <button className="btn primary" type="submit" disabled={grant.isPending || !apps.data?.length}>Grant access</button>
      </form>
      {grant.isError && <div className="notice error" style={{ marginTop: 10 }}>{errorText(grant.error)}</div>}
      {grant.isSuccess && <div className="notice ok" style={{ marginTop: 10 }}>Access granted.</div>}
    </section>
  )
}

// ------------------------------------------------------------------ all access records
const FILTERS: (AccessStatus | 'all')[] = ['all', 'approved', 'pending', 'denied', 'revoked']

function Access() {
  const [filter, setFilter] = useState<AccessStatus | 'all'>('approved')
  const rows = useQuery({ queryKey: ['access', filter], queryFn: () => api.access(filter === 'all' ? undefined : filter) })
  const refresh = useRefresh()
  const decide = useMutation({
    mutationFn: ({ r, status }: { r: AccessRecord; status: 'approved' | 'revoked' }) => api.decide(r.app_id, r.email, status),
    onSuccess: refresh,
  })

  return (
    <section className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Who can use what</h2>
        <div className="segmented" role="group" aria-label="Filter by status">
          {FILTERS.map(f => (
            <button key={f} className={filter === f ? 'on' : ''} aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>
      {rows.isLoading ? <div className="loading">Loading…</div>
        : rows.isError ? <div className="notice error">{errorText(rows.error)}</div>
        : !rows.data?.length ? <div className="empty">Nothing here.</div>
        : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Person</th><th>App</th><th>Status</th><th>Decided</th><th /></tr></thead>
              <tbody>
                {rows.data.map(r => (
                  <tr key={`${r.app_id}/${r.email}`}>
                    <td><div>{r.email}</div>{r.name && <div className="muted small">{r.name}</div>}</td>
                    <td>{r.app_name}</td>
                    <td><span className={`pill ${r.status}`}>{r.status}</span></td>
                    <td className="small">{when(r.decided_at)}{r.decided_by && <div className="muted">by {r.decided_by}</div>}</td>
                    <td className="actions">
                      {r.status === 'approved' && <button className="btn sm danger" disabled={decide.isPending} onClick={() => decide.mutate({ r, status: 'revoked' })}>Revoke</button>}
                      {(r.status === 'denied' || r.status === 'revoked') && <button className="btn sm" disabled={decide.isPending} onClick={() => decide.mutate({ r, status: 'approved' })}>Approve</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {decide.isError && <div className="notice error">{errorText(decide.error)}</div>}
    </section>
  )
}

// ------------------------------------------------------------------ people
function People({ me }: { me: Me }) {
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const refresh = useRefresh()
  const setRole = useMutation({
    mutationFn: ({ email, role }: { email: string; role: 'user' | 'admin' }) => api.setRole(email, role),
    onSuccess: refresh,
  })

  return (
    <section className="card">
      <h2>People who signed in</h2>
      {people.isLoading ? <div className="loading">Loading…</div>
        : people.isError ? <div className="notice error">{errorText(people.error)}</div>
        : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Person</th><th>Role</th><th>Apps</th><th>Last seen</th><th /></tr></thead>
              <tbody>
                {people.data!.map(p => (
                  <tr key={p.email}>
                    <td><div>{p.email}</div>{p.name && <div className="muted small">{p.name}</div>}</td>
                    <td><span className={`pill ${p.role}`}>{p.role}{p.permanent ? ' · permanent' : ''}</span></td>
                    <td className="small">{p.role === 'admin' ? 'all' : `${p.approved} approved`}{p.pending > 0 && <span className="muted"> · {p.pending} pending</span>}</td>
                    <td className="small">{p.last_seen ? when(p.last_seen) : <span className="muted">never signed in</span>}</td>
                    <td className="actions">
                      {!p.permanent && p.email !== me.email && (p.role === 'admin'
                        ? <button className="btn sm" disabled={setRole.isPending} onClick={() => setRole.mutate({ email: p.email, role: 'user' })}>Remove admin</button>
                        : <button className="btn sm" disabled={setRole.isPending} onClick={() => setRole.mutate({ email: p.email, role: 'admin' })}>Make admin</button>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {setRole.isError && <div className="notice error">{errorText(setRole.error)}</div>}
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
