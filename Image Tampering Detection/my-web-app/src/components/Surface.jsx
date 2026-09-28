import Icon from './Icon'

const toneStyles = {
  neutral: {
    wrap: 'border-white/5 bg-[var(--surface-container)]',
    icon: 'text-[var(--on-surface-variant)]',
  },
  primary: {
    wrap: 'border-[var(--primary)]/20 bg-[var(--primary-container)]/15',
    icon: 'text-[var(--primary)]',
  },
  warning: {
    wrap: 'border-amber-500/25 bg-amber-500/[0.06]',
    icon: 'text-amber-400',
  },
  success: {
    wrap: 'border-emerald-500/25 bg-emerald-500/[0.06]',
    icon: 'text-emerald-400',
  },
  danger: {
    wrap: 'border-rose-500/25 bg-rose-500/[0.06]',
    icon: 'text-rose-400',
  },
}

export default function Surface({ icon, title, subtitle, tone = 'neutral', children, className = '' }) {
  const t = toneStyles[tone] ?? toneStyles.neutral
  return (
    <section
      className={`rounded-2xl border ${t.wrap} p-4 shadow-[0_1px_2px_rgba(0,0,0,0.4),0_10px_28px_-14px_rgba(0,0,0,0.6)] sm:p-5 ${className}`}
    >
      {(title || icon) && (
        <header className="mb-3 flex items-center gap-2.5">
          {icon && (
            <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/5 ${t.icon}`}>
              <Icon name={icon} className="h-4.5 w-4.5" />
            </span>
          )}
          <div className="min-w-0">
            <p className="text-sm font-medium text-[var(--on-surface)]">{title}</p>
            {subtitle && <p className="truncate text-xs text-[var(--on-surface-variant)]">{subtitle}</p>}
          </div>
        </header>
      )}
      {children}
    </section>
  )
}
