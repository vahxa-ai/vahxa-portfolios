// Typed client for the FastAPI backend (portal/main.py).

export type AccessStatus = 'pending' | 'approved' | 'denied' | 'revoked'
export type Role = 'user' | 'admin'

export interface Me {
  email: string
  name: string
  role: Role
  permanent: boolean
  auth_enabled: boolean
  pending_requests: number
}

export interface CatalogApp {
  id: string
  name: string
  description: string
  project: string
  order: number
  status: AccessStatus | null
  access: { status: AccessStatus; note: string; requested_at: string | null; decided_at: string | null } | null
  url: string | null
}

export interface AccessRecord {
  email: string
  app_id: string
  app_name: string
  name: string
  note: string
  status: AccessStatus
  requested_at: string | null
  decided_at: string | null
  decided_by: string | null
}

export interface Person {
  email: string
  name: string
  role: Role
  permanent: boolean
  first_seen: string | null
  last_seen: string | null
  approved: number
  pending: number
}

export interface AppDef {
  id: string
  name: string
  description: string
  url: string
  project: string
  order: number
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = typeof body.detail === 'string'
        ? body.detail
        : (body.detail ?? []).map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

const send = (method: string, body?: unknown): RequestInit =>
  ({ method, body: body === undefined ? undefined : JSON.stringify(body) })
const enc = encodeURIComponent

export const api = {
  me: () => request<Me>('/me'),
  apps: () => request<CatalogApp[]>('/apps'),
  requestApp: (id: string, note: string, name: string) => request(`/apps/${enc(id)}/request`, send('POST', { note, name })),
  withdraw: (id: string) => request(`/apps/${enc(id)}/request`, send('DELETE')),

  access: (status?: AccessStatus) => request<AccessRecord[]>(`/admin/access${status ? `?status=${status}` : ''}`),
  decide: (appId: string, email: string, status: 'approved' | 'denied' | 'revoked') =>
    request(`/admin/access/${enc(appId)}/${enc(email)}`, send('POST', { status })),
  grant: (email: string, appId: string) => request('/admin/grants', send('POST', { email, app_id: appId })),

  people: () => request<Person[]>('/admin/users'),
  setRole: (email: string, role: Role) => request(`/admin/users/${enc(email)}/role`, send('PUT', { role })),

  appDefs: () => request<AppDef[]>('/admin/apps'),
  createApp: (app: AppDef) => request<AppDef>('/admin/apps', send('POST', app)),
  updateApp: (app: AppDef) => request<AppDef>(`/admin/apps/${enc(app.id)}`, send('PUT', app)),
  deleteApp: (id: string) => request(`/admin/apps/${enc(id)}`, send('DELETE')),
}

/** Sign out of the Identity-Aware Proxy session. */
export const SIGN_OUT_URL = '/?gcp-iap-mode=CLEAR_LOGIN_COOKIE'

export const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Request failed')

export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '–'
