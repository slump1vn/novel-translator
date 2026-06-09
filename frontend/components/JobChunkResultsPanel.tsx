'use client'

import type { JobChunkResult } from '@/lib/types'

const STATUS_LABEL: Record<JobChunkResult['status'], string> = {
  processing: 'Đang dịch',
  completed: 'Đã dịch',
  failed: 'Lỗi',
}

const STATUS_COLOR: Record<JobChunkResult['status'], string> = {
  processing: '#01696f',
  completed: '#437a22',
  failed: '#a12c7b',
}

interface Props {
  chunks: JobChunkResult[]
}

export default function JobChunkResultsPanel({ chunks }: Props) {
  return (
    <div className="rounded-2xl border p-5 h-full" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>
            Kết quả dịch trực tiếp
          </h2>
          <p className="text-xs mt-1" style={{ color: 'var(--color-muted)' }}>
            Mỗi chunk sẽ hiện đoạn gốc và đoạn đã dịch ngay khi xong.
          </p>
        </div>
        <span className="text-xs tabular-nums" style={{ color: 'var(--color-muted)' }}>
          {chunks.length}
        </span>
      </div>

      {chunks.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--color-muted)' }}>
          Chưa có chunk nào hoàn tất.
        </p>
      ) : (
        <div className="max-h-[620px] space-y-3 overflow-y-auto pr-1">
          {chunks.map((chunk) => {
            const color = STATUS_COLOR[chunk.status]
            return (
              <div key={chunk.id} className="rounded-xl border p-3 space-y-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg)' }}>
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                      Chunk {chunk.chunk_index + 1}
                    </p>
                    {(chunk.provider_name || chunk.model_name) && (
                      <p className="text-xs truncate" style={{ color: 'var(--color-muted)' }}>
                        {(chunk.provider_name || '-').toUpperCase()} / {chunk.model_name || '-'}
                      </p>
                    )}
                  </div>
                  <span className="rounded-full px-2.5 py-1 text-[11px] font-semibold" style={{ background: `${color}22`, color }}>
                    {STATUS_LABEL[chunk.status]}
                  </span>
                </div>

                <div className="grid gap-3">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--color-muted)' }}>
                      Nguồn
                    </p>
                    <div className="rounded-lg border px-3 py-2 text-sm whitespace-pre-wrap break-words" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
                      {chunk.source_text}
                    </div>
                  </div>

                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--color-muted)' }}>
                      Bản dịch
                    </p>
                    <div className="rounded-lg border px-3 py-2 text-sm whitespace-pre-wrap break-words min-h-[4rem]" style={{ borderColor: 'var(--color-border)', color: chunk.status === 'failed' ? '#a12c7b' : 'var(--color-text)' }}>
                      {chunk.translated_text || chunk.error_message || 'Đang chờ kết quả...'}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
