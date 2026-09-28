import { useCallback, useRef, useState } from 'react'
import Icon from './Icon'

export default function Dropzone({ onFile, disabled }) {
  const inputRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)

  const handleFiles = useCallback(
    (files) => {
      const file = files?.[0]
      if (file) onFile(file)
    },
    [onFile],
  )

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setIsDragging(true)
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setIsDragging(false)
        if (!disabled) handleFiles(e.dataTransfer.files)
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => {
        if (!disabled && (e.key === 'Enter' || e.key === ' ')) inputRef.current?.click()
      }}
      role="button"
      tabIndex={disabled ? -1 : 0}
      className={`group relative flex flex-col items-center justify-center gap-3 overflow-hidden rounded-3xl border-2 border-dashed p-12 text-center transition-all duration-200
        ${isDragging
          ? 'scale-[1.01] border-[var(--primary)] bg-[var(--primary-container)]/20'
          : 'border-[var(--outline)] bg-[var(--surface-container-low)]'}
        ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:border-[var(--primary)]/60 hover:bg-[var(--surface-container)]'}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png"
        className="hidden"
        disabled={disabled}
        onChange={(e) => handleFiles(e.target.files)}
      />
      <span
        className={`flex h-16 w-16 items-center justify-center rounded-full bg-[var(--primary-container)]/40 text-[var(--primary)] transition-transform duration-200 ${
          isDragging ? 'scale-110' : 'group-hover:scale-105'
        }`}
      >
        <Icon name="upload" className="h-7 w-7" strokeWidth={1.6} />
      </span>
      <div>
        <p className="text-base font-medium text-[var(--on-surface)]">
          Drop a JPEG or PNG here, or click to browse
        </p>
        <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
          Analyzed locally — nothing leaves this machine
        </p>
      </div>
    </div>
  )
}
