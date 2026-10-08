import { useQuery } from '@tanstack/react-query'
import { api, errorText, type AppDef, type Me } from '../api'

// One color per position in the catalog, so neighbouring apps never share one.
const HUES = [221, 160, 24, 262, 330, 190, 45]
const monogramColor = (i: number) => `hsl(${HUES[i % HUES.length]} 62% 46%)`

export default function AppsPage({ me }: { me: Me }) {
  const apps = useQuery({ queryKey: ['apps'], queryFn: api.apps })
  const first = me.name || me.email.split('@')[0]

  return (
    <div className="stack" style={{ gap: 24 }}>
      <header className="page-head">
        <h1>Welcome, {first}</h1>
        <p>Open any Vahxa app from here. Each app manages its own access, so the first time you open one
          it may ask you to request access inside the app.</p>
      </header>

      {apps.isLoading ? <div className="loading">Loading apps…</div>
        : apps.isError ? <div className="notice error">{errorText(apps.error)}</div>
        : !apps.data?.length ? <div className="card empty">No apps have been added yet.</div>
        : (
          <div className="app-grid">
            {apps.data.map((a, i) => <AppCard key={a.id} app={a} color={monogramColor(i)} />)}
          </div>
        )}
    </div>
  )
}

function host(url: string) {
  try { return new URL(url).hostname } catch { return url }
}

function AppCard({ app, color }: { app: AppDef; color: string }) {
  return (
    <article className="app-card">
      <div className="app-top">
        <span className="monogram" style={{ background: color }} aria-hidden>{app.name.charAt(0)}</span>
        <div className="app-title">
          <h3>{app.name}</h3>
          {app.project && <div className="muted small">{app.project}</div>}
        </div>
      </div>
      <p className="app-desc">{app.description || 'No description yet.'}</p>
      <div className="app-foot">
        <span className="muted small app-host">{host(app.url)}</span>
        <a className="btn primary" href={app.url} target="_blank" rel="noopener noreferrer">Open app <span aria-hidden>↗</span></a>
      </div>
    </article>
  )
}
