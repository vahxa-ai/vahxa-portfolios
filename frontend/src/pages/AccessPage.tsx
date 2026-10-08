import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorText, SIGN_OUT_URL, when, type Me } from '../api'

/** What a signed-in person sees until an admin approves them for the portal. */
export default function AccessPage({ me }: { me: Me }) {
  const qc = useQueryClient()
  const [name, setName] = useState(me.name)
  const [reason, setReason] = useState('')
  const [editing, setEditing] = useState(false)
  const ask = useMutation({
    mutationFn: () => api.requestAccess(name, reason),
    onSuccess: () => { setEditing(false); qc.invalidateQueries({ queryKey: ['me'] }) },
  })
  const submit = (e: FormEvent) => { e.preventDefault(); ask.mutate() }

  const pending = me.status === 'pending' && !editing
  const closed = (me.status === 'denied' || me.status === 'revoked') && !editing

  return (
    <div className="access">
      <section className="card access-card">
        <span className="brand-mark big" aria-hidden>V</span>
        {pending ? (
          <>
            <h1>Request sent</h1>
            <p className="muted">An admin will review it. This page opens the portal by itself once you're approved.</p>
            <dl className="facts">
              <div><dt>Account</dt><dd>{me.email}</dd></div>
              <div><dt>Requested</dt><dd>{when(me.requested_at)}</dd></div>
              {me.reason && <div><dt>Your note</dt><dd>{me.reason}</dd></div>}
            </dl>
          </>
        ) : closed ? (
          <>
            <h1>{me.status === 'denied' ? 'Request not approved' : 'Access removed'}</h1>
            <p className="muted">
              {me.status === 'denied' ? 'An admin declined your request' : 'An admin removed your access'} on {when(me.decided_at)}.
              You can send a new request if something has changed.
            </p>
            <button className="btn primary" onClick={() => setEditing(true)}>Request again</button>
          </>
        ) : (
          <>
            <h1>Request access to Vahxa Portfolios</h1>
            <p className="muted">The portal is the entry point to the Vahxa apps. An admin approves each person first.
              You're signed in as <b>{me.email}</b>.</p>
            <form className="request-form" onSubmit={submit}>
              <label className="field"><span>Your name</span>
                <input required value={name} onChange={e => setName(e.target.value)} maxLength={100} autoComplete="name" />
              </label>
              <label className="field"><span>Why do you need access? <span className="muted">(optional)</span></span>
                <textarea rows={3} value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} />
              </label>
              {ask.isError && <div className="notice error">{errorText(ask.error)}</div>}
              <div className="actions">
                <button className="btn primary" type="submit" disabled={ask.isPending}>{ask.isPending ? 'Sending…' : 'Send request'}</button>
                {editing && <button className="btn" type="button" onClick={() => setEditing(false)}>Cancel</button>}
              </div>
            </form>
          </>
        )}
        {me.auth_enabled && <p className="access-foot small muted">Wrong account? <a href={SIGN_OUT_URL}>Sign out</a></p>}
      </section>
    </div>
  )
}
