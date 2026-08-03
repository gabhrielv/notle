import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Registered after load so it never competes with the first paint for
// bandwidth. The screen that decides whether a visitor stays is the one this
// cannot be allowed to slow down.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js').catch(() => {
      // A browser that refuses it still gets the whole site over the network.
      // Offline is the only thing lost, and telling the reader about it would be
      // reporting a capability they never asked for.
    })
  })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
