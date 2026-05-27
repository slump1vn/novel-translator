'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import type { JobDetail, JobStep, DownloadInfo } from '@/lib/types'
import NavBar from '@/components/NavBar'
import JobProgressBar from '@/components/JobProgressBar'
import StepTimeline from '@/components/StepTimeline'
import { Download, ArrowLeft, XCircle } from 'lucide-react'

const STATUS_LABEL: Record<string, string> = {
  queued: 'Chờ xử lý', processing: 'Đang dịch', completed: 'Hoàn tất',
  failed: 'Thất bại', cancelled: 'Đã hủy', partial_success: 'Một phần thành công',
}
const STATUS_COLOR: Record<string, string> = {
  queued: '#d19900', processing: '#01696f', completed: '#437a22',
  failed: '#a12c7b', cancelled: '#7a7974', partial_success: '#da7101',
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [job, setJob] = useState<JobDetail | null>(null)
  const [steps, setSteps] = useState<JobStep[]>([])
  const [download, setDownload] = useState<DownloadInfo | null>(null)
  const [cancelling, setCancelling] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const [j, s] = await Promise.all([api.getJob(id), api.getJobSteps(id)])
        setJob(j)
        setSteps(s.steps)
        if (j.status === 'completed' && !download) {
          const dl = await api.getDownload(id).catch(() => null)
          setDownload(dl)
        }
      } catch {}
    }
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [id])

  const handleCancel = async () => {
    setCancelling(true)
    try { await api.cancelJob(id); setJob(j => j ? { ...j, status: 'cancelled' } : j) } finally { setCancelling(false) }
  }

  if (!job) return (
    <div style={{ background: 'var(--color-bg)' }} className="min-h-screen">
      <NavBar />
      <div className="max-w-2xl mx-auto px-4 py-20 space-y-4">
        {[1,2,3,4].map(i => <div key={i} className="h-16 rounded-xl animate-pulse" style={{ background: 'var(--color-surface)' }} />)}
      </div>
    </div>
  )

  return (
    <div style={{ background: 'var(--color-bg)' }} className="min-h-screen">
      <NavBar />
      <main className="max-w-2xl mx-auto px-4 py-10 space-y-6">
        <button onClick={() => router.push('/')} className="flex items-center gap-2 text-sm transition-opacity hover:opacity-70" style={{ color: 'var(--color-muted)' }}>
          <ArrowLeft size={14} /> Quay lại
        </button>

        <div className="rounded-2xl p-6 border space-y-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-lg font-bold" style={{ color: 'var(--color-text)' }}>{job.source_file?.filename || 'Job'}</h1>
              <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>ID: {id.slice(0, 8)}… · {job.output_format.toUpperCase()}</p>
            </div>
            <span className="text-xs font-semibold px-3 py-1 rounded-full" style={{ background: STATUS_COLOR[job.status] + '22', color: STATUS_COLOR[job.status] }}>
              {STATUS_LABEL[job.status] || job.status}
            </span>
          </div>

          <JobProgressBar percent={job.progress_percent} status={job.status} />

          <div className="grid grid-cols-3 gap-3 text-center">
            {[
              ['Tổng chunk', job.total_chunks ?? '—'],
              ['Đã dịch', job.translated_chunks],
              ['Lỗi', job.failed_chunks],
            ].map(([label, val]) => (
              <div key={label as string} className="rounded-lg p-3" style={{ background: 'var(--color-bg)' }}>
                <p className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>{val}</p>
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>{label}</p>
              </div>
            ))}
          </div>

          {job.provider && (
            <p className="text-xs" style={{ color: 'var(--color-muted)' }}>Model: <strong style={{ color: 'var(--color-text)' }}>{job.provider.provider} / {job.provider.model_name}</strong></p>
          )}

          {job.error_message && (
            <div className="rounded-lg p-3 text-sm" style={{ background: '#a12c7b11', color: '#a12c7b' }}>⚠️ {job.error_message}</div>
          )}

          <div className="flex gap-3 pt-2">
            {job.status === 'completed' && download && (
              <a href={download.download_url} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors"
                style={{ background: 'var(--color-brand)' }}>
                <Download size={14} /> Tải về {download.filename}
              </a>
            )}
            {['queued','processing'].includes(job.status) && (
              <button onClick={handleCancel} disabled={cancelling}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-opacity hover:opacity-70 disabled:opacity-40"
                style={{ background: '#a12c7b22', color: '#a12c7b' }}>
                <XCircle size={14} /> {cancelling ? 'Đang hủy…' : 'Hủy job'}
              </button>
            )}
          </div>
        </div>

        <StepTimeline steps={steps} currentStep={job.current_step} />
      </main>
    </div>
  )
}
