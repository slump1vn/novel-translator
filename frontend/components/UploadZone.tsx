'use client'
import { useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { Upload, FileText, Loader2 } from 'lucide-react'

interface Props { onJobCreated?: () => void }

const FORMATS = [
  { label: 'EPUB', value: 'epub' },
  { label: 'TXT', value: 'txt' },
]
const PROVIDERS_PLACEHOLDER = 'Dùng provider mặc định'

export default function UploadZone({ onJobCreated }: Props) {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [outputFormat, setOutputFormat] = useState('epub')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) setFile(f)
  }, [])

  const handleSubmit = async () => {
    if (!file) return
    setLoading(true); setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('output_format', outputFormat)
      const res = await api.createJob(fd)
      onJobCreated?.()
      router.push(`/jobs/${res.job_id}`)
    } catch (e: any) {
      setError(e.message || 'Lỗi tạo job')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className="relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all"
        style={{
          borderColor: dragging ? 'var(--color-brand)' : 'var(--color-border)',
          background: dragging ? '#01696f08' : 'var(--color-surface)',
        }}
      >
        <input ref={inputRef} type="file" accept=".txt,.epub,.pdf,.mobi" className="hidden"
          onChange={e => { if (e.target.files?.[0]) setFile(e.target.files[0]) }} />
        <div className="flex flex-col items-center gap-3">
          {file ? (
            <>
              <FileText size={36} style={{ color: 'var(--color-brand)' }} />
              <p className="font-semibold" style={{ color: 'var(--color-text)' }}>{file.name}</p>
              <p className="text-xs" style={{ color: 'var(--color-muted)' }}>{(file.size / 1024 / 1024).toFixed(2)} MB · Click để đổi file</p>
            </>
          ) : (
            <>
              <Upload size={36} style={{ color: 'var(--color-muted)' }} />
              <p className="font-medium" style={{ color: 'var(--color-text)' }}>Kéo thả file vào đây hoặc click để chọn</p>
              <p className="text-xs" style={{ color: 'var(--color-muted)' }}>.txt · .epub · .pdf · tối đa 50MB</p>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-muted)' }}>
          <span>Xuất ra:</span>
          {FORMATS.map(f => (
            <button key={f.value} onClick={() => setOutputFormat(f.value)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
              style={outputFormat === f.value
                ? { background: 'var(--color-brand)', color: '#fff' }
                : { background: 'var(--color-bg)', color: 'var(--color-muted)', border: '1px solid var(--color-border)' }
              }>{f.label}</button>
          ))}
        </div>
        <button
          onClick={handleSubmit}
          disabled={!file || loading}
          className="ml-auto flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40"
          style={{ background: 'var(--color-brand)' }}
        >
          {loading ? <><Loader2 size={15} className="animate-spin" /> Đang tạo job…</> : <><Upload size={15} /> Bắt đầu dịch</>}
        </button>
      </div>

      {error && <p className="text-sm rounded-lg px-3 py-2" style={{ background: '#a12c7b11', color: '#a12c7b' }}>⚠️ {error}</p>}
    </div>
  )
}
