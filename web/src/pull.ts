/**
 * Turns finger travel into list travel.
 *
 * Damped rather than followed one to one: a list that tracks the finger exactly
 * reads as a bug in the scroll, while one that lags behind reads as something
 * being pulled against a spring. The numbers here are proportions rather than
 * measurements, and the place to settle them is a real device.
 */

/** How much of the finger's travel the list actually takes. */
export const PULL_DAMPING = 0.5

/** Where the list stops following, well past the point the gesture is made. */
export const PULL_MAX = 96

/** Past this, releasing refreshes. Half of it in finger travel is 128px. */
export const PULL_THRESHOLD = 64

export function pullOffset(deltaY: number): number {
  if (deltaY <= 0) return 0
  return Math.min(deltaY * PULL_DAMPING, PULL_MAX)
}

export function shouldRefresh(offset: number): boolean {
  return offset >= PULL_THRESHOLD
}
