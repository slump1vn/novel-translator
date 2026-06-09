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

interface ChapterGroup {
  key: string
  index: number
  title: string
  chunks: JobChunkResult[]
  totalChunks: number
  completedChunks: number
  failedChunks: number
}

function groupedChapters(chunks: JobChunkResult[]): ChapterGroup[] {
  const groups = new Map<string, ChapterGroup>()
  chunks.forEach((chunk) => {
    if (chunk.chapter_index === null || !chunk.chapter_title) return
    const key = String(chunk.chapter_index)
    const current = groups.get(key)
    if (current) {
      current.chunks.push(chunk)
      current.totalChunks = Math.max(current.totalChunks, chunk.chapter_total_chunks || 0)
      current.completedChunks += chunk.status === 'completed' ? 1 : 0
      current.failedChunks += chunk.status === 'failed' ? 1 : 0
      return
    }
    groups.set(key, {
      key,
      index: chunk.chapter_index,
      title: chunk.chapter_title,
      chunks: [chunk],
      totalChunks: chunk.chapter_total_chunks || 1,
      completedChunks: chunk.status === 'completed' ? 1 : 0,
      failedChunks: chunk.status === 'failed' ? 1 : 0,
    })
  })

  return [...groups.values()].sort((left, right) => left.index - right.index)
}

function latestChunk(chunks: JobChunkResult[]): JobChunkResult {
  return [...chunks].sort((left, right) => right.chunk_index - left.chunk_index)[0]
}

function ChunkPreview({ chunk }: { chunk: JobChunkResult }) {
  return (
    <div className="grid gap-3">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--color-muted)' }}>
          Nguồn
        </p>
        <div className="rounded-lg border px-3 py-2 text-sm whitespace-pre-wrap break-words max-h-40 overflow-y-auto" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
          {chunk.source_text}
        </div>
      </div>

      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--color-muted)' }}>
          Bản dịch
        </p>
        <div className="rounded-lg border px-3 py-2 text-sm whitespace-pre-wrap break-words min-h-[4rem] max-h-40 overflow-y-auto" style={{ borderColor: 'var(--color-border)', color: chunk.status === 'failed' ? '#a12c7b' : 'var(--color-text)' }}>
          {chunk.translated_text || chunk.error_message || 'Đang chờ kết quả...'}
        </div>
      </div>
    </div>
  )
}

export default function JobChunkResultsPanel({ chunks }: Props) {
  const chapters = groupedChapters(chunks)
  const hasChapterMetadata = chapters.length > 0

  return (
    <div className="rounded-2xl border p-5 h-full" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>
            {hasChapterMetadata ? 'Chương đang dịch' : 'Kết quả dịch trực tiếp'}
          </h2>
          <p className="text-xs mt-1" style={{ color: 'var(--color-muted)' }}>
            {hasChapterMetadata ? 'Theo dõi tiến độ và đoạn mới nhất của từng chương.' : 'Mỗi chunk sẽ hiện đoạn gốc và đoạn đã dịch ngay khi xong.'}
          </p>
        </div>
        <span className="text-xs tabular-nums" style={{ color: 'var(--color-muted)' }}>
          {hasChapterMetadata ? chapters.length : chunks.length}
        </span>
      </div>

      {chunks.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--color-muted)' }}>
          Chưa có nội dung dịch trực tiếp.
        </p>
      ) : hasChapterMetadata ? (
        <div className="max-h-[620px] space-y-3 overflow-y-auto pr-1">
          {chapters.map((chapter) => {
            const recent = latestChunk(chapter.chunks)
            const visibleTotal = Math.max(chapter.totalChunks, chapter.chunks.length, 1)
            const progress = Math.max(0, Math.min(100, Math.round((chapter.completedChunks / visibleTotal) * 100)))
            const status = chapter.failedChunks > 0 ? 'failed' : chapter.completedChunks >= visibleTotal ? 'completed' : 'processing'
            const color = STATUS_COLOR[status]

            return (
              <div key={chapter.key} className="rounded-xl border p-3 space-y-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg)' }}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold truncate" style={{ color: 'var(--color-text)' }}>
                      {chapter.index + 1}. {chapter.title}
                    </p>
                    <p className="text-xs tabular-nums" style={{ color: 'var(--color-muted)' }}>
                      {chapter.completedChunks}/{visibleTotal} chunk
                    </p>
                  </div>
                  <span className="rounded-full px-2.5 py-1 text-[11px] font-semibold" style={{ background: `${color}22`, color }}>
                    {STATUS_LABEL[status]}
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: 'var(--color-border)' }}>
                  <div className="h-1.5 rounded-full transition-all duration-500" style={{ width: `${progress}%`, background: color }} />
                </div>
                <ChunkPreview chunk={recent} />
              </div>
            )
          })}
        </div>
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
                <ChunkPreview chunk={chunk} />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
