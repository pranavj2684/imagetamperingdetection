import { Fragment } from 'react'
import Surface from './Surface'

function Stat({ label, value }) {
  return (
    <div className="rounded-xl bg-white/[0.03] px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-[var(--on-surface-variant)]">{label}</dt>
      <dd className="font-mono-data mt-0.5 text-sm text-[var(--on-surface)]">{value}</dd>
    </div>
  )
}

export default function ExifPanel({ exif, wasPngSynthetic, elaMaxDiff, luminosityStd }) {
  const entries = Object.entries(exif ?? {})

  return (
    <Surface icon="info" title="Metadata & signal stats" className="h-full">
      <dl className="grid grid-cols-3 gap-2">
        <Stat label="ELA max diff" value={elaMaxDiff} />
        <Stat label="Luminosity σ" value={luminosityStd} />
        <Stat label="Synthetic ELA" value={wasPngSynthetic ? 'Yes' : 'No'} />
      </dl>
      {entries.length > 0 ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-white/5 pt-3 text-xs">
          {entries.map(([key, value]) => (
            <Fragment key={key}>
              <dt className="truncate text-[var(--on-surface-variant)]">{key}</dt>
              <dd className="font-mono-data truncate text-right text-[var(--on-surface)]">{String(value)}</dd>
            </Fragment>
          ))}
        </dl>
      ) : (
        <p className="mt-3 border-t border-white/5 pt-3 text-xs text-[var(--on-surface-variant)]">
          No EXIF metadata found in this image.
        </p>
      )}
    </Surface>
  )
}
