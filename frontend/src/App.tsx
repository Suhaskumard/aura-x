import { useEffect, useState } from 'react'
import './App.css'

type HealthResponse = {
  status: string
  app_name: string
  environment: string
  github_token_configured: boolean
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/v1/health`)
      .then((res) => {
        if (!res.ok) throw new Error(`Backend returned ${res.status}`)
        return res.json() as Promise<HealthResponse>
      })
      .then(setHealth)
      .catch((err: Error) => setError(err.message))
  }, [])

  return (
    <main style={{ fontFamily: 'sans-serif', padding: '2rem', maxWidth: 640 }}>
      <h1>AURA-X</h1>
      <p>Autonomous Unified Reliability &amp; Evolution Analyzer</p>
      <p>
        This is the Phase 0 bootstrap shell. The GitHub repository onboarding
        UI is implemented in Phase 13 of the integration plan.
      </p>

      <h2>Backend connectivity</h2>
      {error && (
        <p style={{ color: 'crimson' }}>
          Could not reach backend at {API_BASE_URL}: {error}
        </p>
      )}
      {!error && !health && <p>Checking backend health…</p>}
      {health && (
        <pre style={{ background: '#f1f5f9', padding: '1rem', borderRadius: 8 }}>
          {JSON.stringify(health, null, 2)}
        </pre>
      )}
    </main>
  )
}

export default App
