import Icon from './Icon'

function bandFor(score) {
  if (score >= 60) {
    return {
      label: 'High risk',
      stroke: '#fb7185',
      text: 'text-rose-400',
      chip: 'bg-rose-500/15 text-rose-300',
      icon: 'shieldAlert',
    }
  }
  if (score >= 30) {
    return {
      label: 'Moderate risk',
      stroke: '#fbbf24',
      text: 'text-amber-400',
      chip: 'bg-amber-500/15 text-amber-300',
      icon: 'alertTriangle',
    }
  }
  return {
    label: 'Low risk',
    stroke: '#34d399',
    text: 'text-emerald-400',
    chip: 'bg-emerald-500/15 text-emerald-300',
    icon: 'shieldCheck',
  }
}

export default function ScoreBadge({ score, verdict }) {
  const band = bandFor(score)
  const radius = 42
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (Math.min(score, 100) / 100) * circumference

  return (
    <div className="flex items-center gap-5 rounded-2xl border border-white/5 bg-[var(--surface-container)] p-5 shadow-[0_1px_2px_rgba(0,0,0,0.4),0_10px_28px_-14px_rgba(0,0,0,0.6)]">
      <div className="relative flex h-28 w-28 shrink-0 items-center justify-center">
        <svg width="112" height="112" viewBox="0 0 112 112" className="-rotate-90">
          <circle cx="56" cy="56" r={radius} fill="none" stroke="var(--outline-variant)" strokeWidth="9" />
          <circle
            cx="56"
            cy="56"
            r={radius}
            fill="none"
            stroke={band.stroke}
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="transition-[stroke-dashoffset] duration-700 ease-out"
          />
        </svg>
        <div className="absolute flex flex-col items-center">
          <span className="font-mono-data text-3xl font-medium leading-none text-[var(--on-surface)]">
            {score.toFixed(1)}
          </span>
          <span className="mt-1 text-[10px] uppercase tracking-wider text-[var(--on-surface-variant)]">
            / 100
          </span>
        </div>
      </div>
      <div className="min-w-0">
        <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${band.chip}`}>
          <Icon name={band.icon} className="h-3.5 w-3.5" strokeWidth={2} />
          {band.label}
        </span>
        <p className="mt-2 text-sm leading-snug text-[var(--on-surface-variant)]">{verdict}</p>
      </div>
    </div>
  )
}
