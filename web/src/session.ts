/**
 * The id that scopes the reader's last few minutes.
 *
 * sessionStorage rather than a cookie or a module variable: it is scoped to the
 * tab and the browser discards it when the tab closes, which is the architecture's
 * "dies with the session" without an expiry to calibrate or a sweep to run. A
 * module variable would reset on every reload and lose a run mid way; a cookie
 * would outlive the visit and let a curious afternoon become an identity.
 *
 * A tab left open all day stays one session, and that costs almost nothing: at a
 * ten minute half life, something read two hours ago arrives under one percent.
 */
const KEY = 'notle-session'

export function sessionId(): string {
  let id = sessionStorage.getItem(KEY)
  if (!id) {
    id = crypto.randomUUID()
    sessionStorage.setItem(KEY, id)
  }
  return id
}
