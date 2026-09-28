import Icon from './Icon'
import Surface from './Surface'

function RegionTable({ columns, rows }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-white/5">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="bg-white/[0.03] text-[var(--on-surface-variant)]">
            {columns.map((c) => (
              <th key={c} className="px-3 py-2 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono-data">
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-white/5 text-[var(--on-surface)] transition-colors hover:bg-white/[0.03]">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MrzPanel({ mrz }) {
  if (!mrz || mrz.parse_error) return null

  return (
    <Surface
      icon="fingerprint"
      title="MRZ checksum validation"
      subtitle={mrz.all_valid ? 'All checkable fields match' : 'Check-digit mismatch found'}
      tone={mrz.all_valid ? 'success' : 'danger'}
    >
      <RegionTable
        columns={['Field', 'Expected', 'Actual', 'Result']}
        rows={mrz.checks.map((c) => [
          c.field,
          c.expected,
          c.actual,
          c.matches ? (
            <span className="inline-flex items-center gap-1 text-emerald-400">
              <Icon name="checkCircle" className="h-3.5 w-3.5" strokeWidth={2} /> match
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-rose-400">
              <Icon name="xCircle" className="h-3.5 w-3.5" strokeWidth={2} /> mismatch
            </span>
          ),
        ])}
      />
    </Surface>
  )
}

export default function ReportPanel({
  report,
  warnings,
  regions,
  blurRegions = [],
  noiseRegions = [],
  mrz = null,
}) {
  return (
    <div className="flex flex-col gap-4">
      {warnings.length > 0 && (
        <Surface icon="alertTriangle" title="Reliability warnings" tone="warning">
          <ul className="space-y-1.5 text-sm text-amber-100/90">
            {warnings.map((w, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-amber-400" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </Surface>
      )}

      <MrzPanel mrz={mrz} />

      <Surface icon="scan" title="AI localization report" subtitle="Rule-based retrieval over forensic heuristics">
        <ul className="space-y-3 text-sm leading-relaxed text-[var(--on-surface)]/90">
          {report.map((line, i) => (
            <li key={i} className="flex gap-3">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--primary-container)]/40 text-[10px] font-medium text-[var(--primary)]">
                {i + 1}
              </span>
              <span>{line}</span>
            </li>
          ))}
        </ul>
      </Surface>

      {regions.length > 0 && (
        <Surface icon="alertTriangle" title={`Flagged regions (${regions.length})`} subtitle="Error Level Analysis channel" tone="danger">
          <RegionTable
            columns={['Position', 'Size', 'Mean ELA', 'Contrast ratio']}
            rows={regions.map((r) => [`(${r.x}, ${r.y})`, `${r.w}×${r.h}px`, r.mean_ela, `${r.contrast_ratio}×`])}
          />
        </Surface>
      )}

      {blurRegions.length > 0 && (
        <Surface
          icon="alertTriangle"
          title={`Sharpness-anomaly regions (${blurRegions.length})`}
          subtitle="Laplacian-variance channel — deficit (blur) or excess (resampling/blockiness)"
          tone="warning"
        >
          <RegionTable
            columns={['Position', 'Size', 'Type', 'Ratio']}
            rows={blurRegions.map((r) => [
              `(${r.x}, ${r.y})`,
              `${r.w}×${r.h}px`,
              r.polarity === 'excess' ? 'sharper/blockier' : 'blurrier',
              `${r.deficit_ratio}×`,
            ])}
          />
        </Surface>
      )}

      {noiseRegions.length > 0 && (
        <Surface
          icon="alertTriangle"
          title={`Noise-floor-anomaly regions (${noiseRegions.length})`}
          subtitle="Wiener-residual variance channel — deficit (too clean) or excess (resampling/blockiness)"
          tone="primary"
        >
          <RegionTable
            columns={['Position', 'Size', 'Type', 'Ratio']}
            rows={noiseRegions.map((r) => [
              `(${r.x}, ${r.y})`,
              `${r.w}×${r.h}px`,
              r.polarity === 'excess' ? 'noisier' : 'cleaner',
              `${r.deficit_ratio}×`,
            ])}
          />
        </Surface>
      )}
    </div>
  )
}
