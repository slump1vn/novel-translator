import type { JobLog } from '@/lib/types'

const LEVEL_COLOR: Record<string, string> = {
  debug: '#7a7974',
  info: '#01696f',
  warning: '#da7101',
  error: '#a12c7b',
}

interface Props {
  logs: JobLog[]
}

export default function JobLogPanel({ logs }: Props) {
  return (
    <div className="rounded-2xl border p-5 h-full" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>
          Log xử lý
        </h2>
        <span className="text-xs tabular-nums" style={{ color: 'var(--color-muted)' }}>
          {logs.length}
        </span>
      </div>

      {logs.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--color-muted)' }}>
          Chưa có log.
        </p>
      ) : (
        <div className="max-h-[620px] overflow-y-auto pr-1 font-mono text-xs leading-5">
          {logs.map((log) => {
            const color = LEVEL_COLOR[log.level] || LEVEL_COLOR.info
            return (
              <div key={log.id} className="border-l-2 pl-3 pb-3" style={{ borderColor: color }}>
                <div className="flex items-center gap-2 flex-wrap">
                  <span style={{ color: 'var(--color-muted)' }}>{new Date(log.created_at).toLocaleTimeString('vi-VN')}</span>
                  <span className="uppercase font-semibold" style={{ color }}>
                    {log.level}
                  </span>
                  {log.step_name && <span style={{ color: 'var(--color-muted)' }}>{log.step_name}</span>}
                  {log.progress_percent !== null && (
                    <span className="tabular-nums" style={{ color: 'var(--color-muted)' }}>
                      {log.progress_percent}%
                    </span>
                  )}
                </div>
                <p className="mt-0.5 break-words" style={{ color: 'var(--color-text)' }}>
                  {log.message}
                </p>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
