import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const KEY = 'notle-theme'

/**
 * What the reader last chose, or what their system says if they never chose.
 *
 * Read once at startup rather than watched. Someone who has picked a side has
 * said what they want, and flipping the page under them because the operating
 * system reached sunset would be the site overruling them.
 */
function initial(): Theme {
  const stored = localStorage.getItem(KEY)
  if (stored === 'light' || stored === 'dark') return stored

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(initial)

  useEffect(() => {
    // The attribute, not a class: the stylesheet keys both the forced light and
    // the forced dark off it, so it has to win over the media query in both
    // directions rather than only turning the lights out.
    document.documentElement.dataset.theme = theme
    localStorage.setItem(KEY, theme)
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  return [theme, toggle]
}
