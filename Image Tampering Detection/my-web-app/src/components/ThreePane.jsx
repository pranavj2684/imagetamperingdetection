function Pane({ title, src, description }) {
  return (
    <div className="flex flex-1 flex-col gap-2.5">
      <h3 className="text-sm font-medium text-[var(--on-surface)]">{title}</h3>
      <div className="aspect-video overflow-hidden rounded-2xl border border-white/5 bg-black shadow-[0_1px_2px_rgba(0,0,0,0.4),0_10px_28px_-14px_rgba(0,0,0,0.6)]">
        <img src={src} alt={title} className="h-full w-full object-contain" />
      </div>
      <p className="text-xs leading-relaxed text-[var(--on-surface-variant)]">{description}</p>
    </div>
  )
}

function LegendDot({ color, label }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  )
}

export default function ThreePane({ images }) {
  return (
    <div className="rounded-2xl border border-white/5 bg-[var(--surface-container)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.4),0_10px_28px_-14px_rgba(0,0,0,0.6)] sm:p-5">
      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <Pane
          title="Original"
          src={images.original}
          description="As uploaded (PNG sources are re-encoded once for Synthetic ELA)."
        />
        <Pane
          title="Error Level Analysis"
          src={images.ela}
          description="Brightness = compression-error magnitude per region."
        />
        <Pane
          title="Morphological Reconstruction"
          src={images.morphological}
          description="Tophat + Bothat contour map, boxed by anomaly type."
        />
      </div>
      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5 border-t border-white/5 pt-3 text-xs text-[var(--on-surface-variant)]">
        <LegendDot color="#ff3c3c" label="Compression-error anomaly" />
        <LegendDot color="#ffa500" label="Sharpness-deficit (blur/inpainting)" />
        <LegendDot color="#c800c8" label="Noise-floor-deficit (clean-residual)" />
      </div>
    </div>
  )
}
