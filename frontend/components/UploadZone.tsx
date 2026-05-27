'use client'

import { useCallback, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { FileText, Loader2, Upload } from 'lucide-react'
import { api } from '@/lib/api'

interface Props {
  onJobCreated?: () => void
}

const FORMATS = [
  { label: 'EPUB', value: 'epub' },
  { label: 'TXT', value: 'txt' },
]

const MAX_FILE_SIZE_MB = 50

export default function UploadZone({ onJobCreated }: Props) {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [outputFormat, setOutputFormat] = useState('epub')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const setSelectedFile = (selected: File) => {
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
    setFile(selected)
  }

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const selected = event.dataTransfer.files[0]
    if (selected) setSelectedFile(selected)
  }, [])

  const handleSubmit = async () => {
    if (!file) return
    setLoading(true)
    setError('')
    try {
      const body = new FormData()
      body.append('file', file)
      body.append('output_format', outputFormat)
      const result = await api.createJob(body)
      onJobCreated?.()
      router.push(`/jobs/${result.job_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lỗi tạo job')
    } finally {
      setLoading(false)
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
            if (event.target.files?.[0]) setSelectedFile(event.target.files[0])
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
          disabled={!file || loading}
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
