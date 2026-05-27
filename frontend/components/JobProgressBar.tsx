interface Props { percent: number; status: string; compact?: boolean }

const TRACK_COLOR: Record<string, string> = {
  completed: '#437a22', failed: '#a12c7b', cancelled: '#7a7974',
}

export default function JobProgressBar({ percent, status, compact }: Props) {
  const fill = TRACK_COLOR[status] || '#01696f'
  const h = compact ? 'h-1' : 'h-2'
  return (
    <div className={`w-full ${h} rounded-full overflow-hidden`} style={{ background: 'var(--color-border)' }}>
      <div
        className={`${h} rounded-full transition-all duration-700`}
        style={{ width: `${Math.min(100, percent)}%`, background: fill }}
      />
    </div>
  )
}
