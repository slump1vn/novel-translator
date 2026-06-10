'use client'

import type { JobChunkResult } from '@/lib/types'

const STATUS_LABEL: Record<JobChunkResult['status'], string> = {
  queued: 'Chờ dịch',
  processing: 'Đang dịch',
  completed: 'Đã dịch',
  failed: 'Lỗi',
}

const STATUS_COLOR: Record<JobChunkResult['status'], string> = {
  queued: '#7a7974',
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

function displayChapterTitle(chapter: { index: number; title: string }): string {
  const title = chapter.title.trim()
  return title || `Chapter ${chapter.index + 1}`
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

function sortedChunks(chunks: JobChunkResult[]): JobChunkResult[] {
  return [...chunks].sort((left, right) => {
    const leftIndex = left.chapter_chunk_index ?? left.chunk_index
    const rightIndex = right.chapter_chunk_index ?? right.chunk_index
    return leftIndex - rightIndex
  })
}

function chapterSourceText(chunks: JobChunkResult[]): string {
  return sortedChunks(chunks)
    .map((chunk) => chunk.source_text.trim())
    .filter(Boolean)
    .join('\n\n')
}

function chapterTranslatedText(chunks: JobChunkResult[]): string {
  return sortedChunks(chunks)
    .map((chunk) => {
      if (chunk.translated_text?.trim()) return chunk.translated_text.trim()
      if (chunk.error_message?.trim()) return `[${chunk.error_message.trim()}]`
      return ''
    })
    .filter(Boolean)
    .join('\n\n')
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

function ChapterContent({ chunks }: { chunks: JobChunkResult[] }) {
  const sourceText = chapterSourceText(chunks)
  const translatedText = chapterTranslatedText(chunks)

  return (
    <div className="grid gap-3">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--color-muted)' }}>
          Nội dung chương
        </p>
        <div className="rounded-lg border px-3 py-2 text-sm whitespace-pre-wrap break-words max-h-72 overflow-y-auto" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
          {sourceText || 'Đang chờ nội dung nguồn...'}
        </div>
      </div>

      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--color-muted)' }}>
          Bản dịch chương
        </p>
        <div className="rounded-lg border px-3 py-2 text-sm whitespace-pre-wrap break-words min-h-[6rem] max-h-72 overflow-y-auto" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
          {translatedText || 'Đang chờ bản dịch...'}
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
            const visibleTotal = Math.max(chapter.totalChunks, chapter.chunks.length, 1)
            const progress = Math.max(0, Math.min(100, Math.round((chapter.completedChunks / visibleTotal) * 100)))
            const hasProcessing = chapter.chunks.some((chunk) => chunk.status === 'processing')
            const status = chapter.failedChunks > 0 ? 'failed' : chapter.completedChunks >= visibleTotal ? 'completed' : hasProcessing ? 'processing' : 'queued'
            const color = STATUS_COLOR[status]

            return (
              <div key={chapter.key} className="rounded-xl border p-3 space-y-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg)' }}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold truncate" style={{ color: 'var(--color-text)' }}>
                      {displayChapterTitle(chapter)}
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
                <ChapterContent chunks={chapter.chunks} />
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
