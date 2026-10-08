// Typed client for the FastAPI backend (portal/main.py).

export type AccessStatus = 'pending' | 'approved' | 'denied' | 'revoked'
export type Role = 'user' | 'admin'

export interface Me {
  email: string
  name: string
  reason: string
  status: AccessStatus | null
  role: Role
  permanent: boolean
  requested_at: string | null
  decided_at: string | null
  auth_enabled: boolean
  pending_requests: number
}

export interface AppDef {
  id: string
  name: string
  description: string
  url: string
  project: string
  order: number
}

export interface Person {
  email: string
  name: string
  reason: string
  status: AccessStatus | null
  role: Role
  permanent: boolean
  requested_at: string | null
  decided_at: string | null
  decided_by: string | null
  first_seen: string | null
  last_seen: string | null
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
  requestAccess: (name: string, reason: string) => request<Person>('/access/request', send('POST', { name, reason })),
  apps: () => request<AppDef[]>('/apps'),

  people: () => request<Person[]>('/admin/people'),
  decide: (email: string, status: 'approved' | 'denied' | 'revoked') =>
    request<Person>(`/admin/people/${enc(email)}/decision`, send('POST', { status })),
  invite: (email: string) => request<Person>('/admin/people', send('POST', { email })),
  setRole: (email: string, role: Role) => request<Person>(`/admin/people/${enc(email)}/role`, send('PUT', { role })),

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
