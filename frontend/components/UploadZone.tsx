'use client'

import { useCallback, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { FileText, ListChecks, Loader2, Upload } from 'lucide-react'
import { api } from '@/lib/api'
import type { EpubAiSplitProgressResponse, EpubChapter } from '@/lib/types'

interface Props {
  onJobCreated?: () => void
}

const FORMATS = [
  { label: 'EPUB', value: 'epub' },
  { label: 'TXT', value: 'txt' },
]

const MAX_FILE_SIZE_MB = 50
const POLL_INTERVAL_MS = 1200

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export default function UploadZone({ onJobCreated }: Props) {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const aiSplitRunRef = useRef(0)
  const selectedChapterIndexesRef = useRef<number[]>([])
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [chapters, setChapters] = useState<EpubChapter[]>([])
  const [selectedChapterIndexes, setSelectedChapterIndexes] = useState<number[]>([])
  const [canAiSplit, setCanAiSplit] = useState(false)
  const [chapterMessage, setChapterMessage] = useState('')
  const [detectedChapterCount, setDetectedChapterCount] = useState(0)
  const [rangeStart, setRangeStart] = useState(1)
  const [rangeEnd, setRangeEnd] = useState(1)
  const [outputFormat, setOutputFormat] = useState('epub')
  const [loading, setLoading] = useState(false)
  const [loadingChapters, setLoadingChapters] = useState(false)
  const [aiSplitting, setAiSplitting] = useState(false)
  const [aiSplitProgress, setAiSplitProgress] = useState<EpubAiSplitProgressResponse | null>(null)
  const [error, setError] = useState('')

  const applySelectedChapterIndexes = (indexes: number[]) => {
    const normalized = [...indexes].sort((a, b) => a - b)
    selectedChapterIndexesRef.current = normalized
    setSelectedChapterIndexes(normalized)
  }

  const setSelectedFile = async (selected: File) => {
    const allowed = ['.txt', '.epub', '.pdf']
    const lowerName = selected.name.toLowerCase()
    if (!allowed.some((extension) => lowerName.endsWith(extension))) {
      setError('Chỉ hỗ trợ file .txt, .epub hoặc .pdf')
      return
    }
    if (selected.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      setError(`File vượt quá ${MAX_FILE_SIZE_MB}MB`)
      return
    }
    setError('')
    aiSplitRunRef.current += 1
    setFile(selected)
    setChapters([])
    applySelectedChapterIndexes([])
    setCanAiSplit(false)
    setChapterMessage('')
    setAiSplitProgress(null)
    setAiSplitting(false)
    setDetectedChapterCount(0)
    setRangeStart(1)
    setRangeEnd(1)

    if (!lowerName.endsWith('.epub')) return

    setLoadingChapters(true)
    try {
      const body = new FormData()
      body.append('file', selected)
      const result = await api.inspectEpubChapters(body)
      setDetectedChapterCount(result.chapters.length)
      setCanAiSplit(result.can_ai_split)
      setChapterMessage(result.message || '')
      if (result.can_ai_split) {
        setChapters([])
        applySelectedChapterIndexes([])
      } else {
        setChapters(result.chapters)
        applySelectedChapterIndexes(result.chapters.map((chapter) => chapter.index))
        setRangeStart(1)
        setRangeEnd(Math.max(result.chapters.length, 1))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể nhận dạng chương EPUB')
    } finally {
      setLoadingChapters(false)
    }
  }

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const selected = event.dataTransfer.files[0]
    if (selected) void setSelectedFile(selected)
  }, [])

  const handleSubmit = async () => {
    if (!file) return
    setLoading(true)
    setError('')
    try {
      const body = new FormData()
      body.append('file', file)
      body.append('output_format', outputFormat)
      const effectiveSelectedChapterIndexes = selectedChapterIndexesRef.current
      if (chapters.length > 0) {
        if (effectiveSelectedChapterIndexes.length > 0) {
          body.append('selected_chapter_indexes', JSON.stringify(effectiveSelectedChapterIndexes))
        }
        if (chapters.some((chapter) => chapter.source === 'ai')) {
          body.append('chapter_segments', JSON.stringify(chapters))
        }
      }
      const result = await api.createJob(body)
      onJobCreated?.()
      router.push(`/jobs/${result.job_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lỗi tạo job')
    } finally {
      setLoading(false)
    }
  }

  const isEpub = Boolean(file?.name.toLowerCase().endsWith('.epub'))
  const canSubmit = Boolean(file && !loading && !loadingChapters && !aiSplitting)

  const toggleChapter = (index: number) => {
    const current = selectedChapterIndexesRef.current
    const next = current.includes(index) ? current.filter((item) => item !== index) : [...current, index]
    applySelectedChapterIndexes(next)
  }

  const selectAllChapters = () => {
    applySelectedChapterIndexes(chapters.map((chapter) => chapter.index))
    setRangeStart(1)
    setRangeEnd(Math.max(chapters.length, 1))
  }

  const selectChapterRange = () => {
    const start = Math.max(1, Math.min(rangeStart, rangeEnd))
    const end = Math.min(chapters.length, Math.max(rangeStart, rangeEnd))
    setRangeStart(start)
    setRangeEnd(end)
    applySelectedChapterIndexes(chapters.filter((chapter) => chapter.index + 1 >= start && chapter.index + 1 <= end).map((chapter) => chapter.index))
  }

  const splitWithAi = async () => {
    if (!file) return
    const runId = aiSplitRunRef.current + 1
    aiSplitRunRef.current = runId
    setAiSplitting(true)
    setAiSplitProgress({
      task_id: '',
      status: 'queued',
      progress_percent: 0,
      message: 'Đang gửi file để tự phân chương...',
      detected_candidates: 0,
      selected_headings: 0,
      chapter_count: 0,
      chapters: [],
      can_ai_split: true,
      chapterized: false,
      error: null,
    })
    setError('')
    try {
      const body = new FormData()
      body.append('file', file)
      const task = await api.startAiSplitEpubChapters(body)
      if (aiSplitRunRef.current !== runId) return

      for (;;) {
        const progress = await api.getAiSplitEpubChapters(task.task_id)
        if (aiSplitRunRef.current !== runId) return
        setAiSplitProgress(progress)

        if (progress.status === 'completed') {
          setCanAiSplit(false)
          setChapterMessage(progress.message || '')
          setChapters(progress.chapters)
          applySelectedChapterIndexes(progress.chapters.map((chapter) => chapter.index))
          setRangeStart(1)
          setRangeEnd(Math.max(progress.chapters.length, 1))
          break
        }

        if (progress.status === 'failed') {
          throw new Error(progress.error || progress.message || 'Không thể tự phân chương bằng AI')
        }

        await sleep(POLL_INTERVAL_MS)
      }
    } catch (err) {
      if (aiSplitRunRef.current === runId) {
        setError(err instanceof Error ? err.message : 'Không thể tự phân chương bằng AI')
      }
    } finally {
      if (aiSplitRunRef.current === runId) {
        setAiSplitting(false)
      }
    }
  }

  return (
    <div className="space-y-4">
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className="relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all"
        style={{
          borderColor: dragging ? 'var(--color-brand)' : 'var(--color-border)',
          background: dragging ? '#01696f08' : 'var(--color-surface)',
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".txt,.epub,.pdf"
          className="hidden"
          onChange={(event) => {
            if (event.target.files?.[0]) void setSelectedFile(event.target.files[0])
          }}
        />
        <div className="flex flex-col items-center gap-3">
          {file ? (
            <>
              <FileText size={36} style={{ color: 'var(--color-brand)' }} />
              <p className="font-semibold" style={{ color: 'var(--color-text)' }}>
                {file.name}
              </p>
              <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                {(file.size / 1024 / 1024).toFixed(2)} MB · Click để đổi file
              </p>
            </>
          ) : (
            <>
              <Upload size={36} style={{ color: 'var(--color-muted)' }} />
              <p className="font-medium" style={{ color: 'var(--color-text)' }}>
                Kéo thả file vào đây hoặc click để chọn
              </p>
              <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                .txt · .epub · .pdf · tối đa 50MB
              </p>
            </>
          )}
        </div>
      </div>

      {isEpub && (
        <div className="rounded-2xl border p-4 space-y-3" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <ListChecks size={16} style={{ color: 'var(--color-brand)' }} />
              <div>
                <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                  Chương EPUB
                </h2>
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                  {loadingChapters
                    ? 'Đang nhận dạng...'
                    : chapters.length > 0
                      ? selectedChapterIndexes.length > 0
                        ? `${selectedChapterIndexes.length}/${chapters.length} chương`
                        : `Toàn bộ ${chapters.length} chương`
                      : `${detectedChapterCount} chương có sẵn`}
                </p>
              </div>
            </div>
            {chapters.length > 0 && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={selectAllChapters}
                  className="rounded-lg px-3 py-1.5 text-xs font-medium transition-opacity hover:opacity-70"
                  style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}
                >
                  Dịch toàn bộ
                </button>
                <button
                  type="button"
                  onClick={() => applySelectedChapterIndexes([])}
                  className="rounded-lg px-3 py-1.5 text-xs font-medium transition-opacity hover:opacity-70"
                  style={{ background: 'var(--color-bg)', color: 'var(--color-muted)' }}
                >
                  Bỏ chọn (dịch tất cả)
                </button>
              </div>
            )}
          </div>

          {loadingChapters ? (
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-muted)' }}>
              <Loader2 size={15} className="animate-spin" /> Đang đọc mục lục EPUB...
            </div>
          ) : canAiSplit ? (
            <div className="rounded-xl border p-4 space-y-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg)' }}>
              <p className="text-sm" style={{ color: 'var(--color-text)' }}>
                File này chưa phân chương rõ ràng. Hệ thống chỉ nhận dạng được {detectedChapterCount} phần, dưới ngưỡng 10 chương.
              </p>
              {chapterMessage && (
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                  {chapterMessage}
                </p>
              )}
              {aiSplitProgress && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3 text-xs" style={{ color: 'var(--color-muted)' }}>
                    <span className="min-w-0 truncate">{aiSplitProgress.message}</span>
                    <span className="tabular-nums">{Math.max(0, Math.min(100, aiSplitProgress.progress_percent))}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: 'var(--color-border)' }}>
                    <div
                      className="h-1.5 rounded-full transition-all duration-500"
                      style={{ width: `${Math.max(0, Math.min(100, aiSplitProgress.progress_percent))}%`, background: 'var(--color-brand)' }}
                    />
                  </div>
                  <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                    Ứng viên: {aiSplitProgress.detected_candidates} · AI chọn: {aiSplitProgress.selected_headings} · Đã phân: {aiSplitProgress.chapter_count} chương
                  </p>
                </div>
              )}
              <button
                type="button"
                onClick={splitWithAi}
                disabled={aiSplitting}
                className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-40"
                style={{ background: 'var(--color-brand)' }}
              >
                {aiSplitting ? <Loader2 size={15} className="animate-spin" /> : <ListChecks size={15} />}
                {aiSplitting ? 'Đang tự phân chương...' : 'Tự phân chương bằng AI'}
              </button>
            </div>
          ) : chapters.length > 0 ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-end gap-2 rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg)' }}>
                <label className="text-xs" style={{ color: 'var(--color-muted)' }}>
                  Từ chương
                  <input
                    type="number"
                    min={1}
                    max={chapters.length}
                    value={rangeStart}
                    onChange={(event) => setRangeStart(Number(event.target.value))}
                    className="mt-1 w-24 rounded-lg border px-2 py-1.5 text-sm"
                    style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                  />
                </label>
                <label className="text-xs" style={{ color: 'var(--color-muted)' }}>
                  Đến chương
                  <input
                    type="number"
                    min={1}
                    max={chapters.length}
                    value={rangeEnd}
                    onChange={(event) => setRangeEnd(Number(event.target.value))}
                    className="mt-1 w-24 rounded-lg border px-2 py-1.5 text-sm"
                    style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                  />
                </label>
                <button
                  type="button"
                  onClick={selectChapterRange}
                  className="rounded-lg px-3 py-2 text-xs font-medium transition-opacity hover:opacity-70"
                  style={{ background: 'var(--color-surface)', color: 'var(--color-text)' }}
                >
                  Dịch theo khoảng
                </button>
              </div>
              {chapterMessage && (
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                  {chapterMessage}
                </p>
              )}
              <div className="max-h-72 overflow-auto rounded-xl border" style={{ borderColor: 'var(--color-border)' }}>
                {chapters.map((chapter) => {
                  const checked = selectedChapterIndexes.includes(chapter.index)
                  return (
                    <label
                      key={`${chapter.index}-${chapter.path}`}
                      className="flex items-center gap-3 border-b px-3 py-2 text-sm last:border-b-0"
                      style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                    >
                      <input type="checkbox" checked={checked} onChange={() => toggleChapter(chapter.index)} className="rounded" />
                      <span className="min-w-0 flex-1 truncate">
                        {chapter.index + 1}. {chapter.title || chapter.path}
                      </span>
                      <span className="text-xs tabular-nums" style={{ color: 'var(--color-muted)' }}>
                        {chapter.character_count.toLocaleString('vi-VN')}
                      </span>
                    </label>
                  )
                })}
              </div>
            </div>
          ) : (
            <p className="text-sm" style={{ color: 'var(--color-muted)' }}>
              Chưa có danh sách chương.
            </p>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-muted)' }}>
          <span>Xuất ra:</span>
          {FORMATS.map((format) => (
            <button
              key={format.value}
              onClick={() => setOutputFormat(format.value)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
              style={
                outputFormat === format.value
                  ? { background: 'var(--color-brand)', color: '#fff' }
                  : { background: 'var(--color-bg)', color: 'var(--color-muted)', border: '1px solid var(--color-border)' }
              }
            >
              {format.label}
            </button>
          ))}
        </div>
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="ml-auto flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40"
          style={{ background: 'var(--color-brand)' }}
        >
          {loading ? (
            <>
              <Loader2 size={15} className="animate-spin" /> Đang tạo job...
            </>
          ) : (
            <>
              <Upload size={15} /> Bắt đầu dịch
            </>
          )}
        </button>
      </div>

      {error && (
        <p className="text-sm rounded-lg px-3 py-2" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
          {error}
        </p>
      )}
    </div>
  )
}
