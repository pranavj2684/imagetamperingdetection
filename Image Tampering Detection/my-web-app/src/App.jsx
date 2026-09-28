import { useCallback, useState } from 'react'
import Dropzone from './components/Dropzone'
import ThreePane from './components/ThreePane'
import ScoreBadge from './components/ScoreBadge'
import ReportPanel from './components/ReportPanel'
import ExifPanel from './components/ExifPanel'
import Icon from './components/Icon'

function AppBar() {
  return (
    <header className="mb-8 flex items-center gap-3.5">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[var(--primary-container)]/40 text-[var(--primary)]">
        <Icon name="scan" className="h-5.5 w-5.5" strokeWidth={1.6} />
      </span>
      <div className="min-w-0">
        <h1 className="text-xl font-medium tracking-tight text-[var(--on-surface)]">
          Image Tampering Detection &amp; Localization
        </h1>
        <p className="mt-0.5 truncate text-sm text-[var(--on-surface-variant)]">
          ELA · Sharpness &amp; Noise Deficit · MRZ Checksum · AI Interpreter
        </p>
      </div>
    </header>
  )
}

function LoadingState() {
  return (
    <div className="mt-6 flex items-center gap-3 rounded-2xl border border-white/5 bg-[var(--surface-container)] p-4 text-sm text-[var(--primary)]">
      <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
      Running ELA, denoising, MRZ OCR and morphological localization…
    </div>
  )
}

function ErrorState({ message }) {
  return (
    <div className="mt-6 flex items-start gap-3 rounded-2xl border border-rose-500/25 bg-rose-500/[0.08] p-4 text-sm text-rose-200">
      <Icon name="alertTriangle" className="mt-0.5 h-5 w-5 shrink-0 text-rose-400" />
      <span>{message}</span>
    </div>
  )
}

function App() {
  const [status, setStatus] = useState('idle') // idle | loading | error | done
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const analyzeFile = useCallback(async (file) => {
    setStatus('loading')
    setError(null)
    setResult(null)

    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch('/api/analyze', { method: 'POST', body: form })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${res.status})`)
      }
      const data = await res.json()
      setResult(data)
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }, [])

  return (
    <div className="min-h-screen px-4 py-8 sm:px-6 sm:py-10 lg:px-10">
      <div className="mx-auto max-w-6xl">
        <AppBar />

        <Dropzone onFile={analyzeFile} disabled={status === 'loading'} />

        {status === 'loading' && <LoadingState />}
        {status === 'error' && <ErrorState message={error} />}

        {status === 'done' && result && (
          <div className="mt-8 flex animate-fade-in-up flex-col gap-6">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[auto_1fr]">
              <ScoreBadge score={result.tamper_score} verdict={result.verdict} />
              <ExifPanel
                exif={result.exif}
                wasPngSynthetic={result.was_png_synthetic}
                elaMaxDiff={result.ela_max_diff}
                luminosityStd={result.luminosity_std}
              />
            </div>

            <ThreePane images={result.images} />

            <ReportPanel
              report={result.report}
              warnings={result.warnings}
              regions={result.regions}
              blurRegions={result.blur_regions}
              noiseRegions={result.noise_regions}
              mrz={result.mrz}
            />
          </div>
        )}
      </div>
    </div>
  )
}

export default App
