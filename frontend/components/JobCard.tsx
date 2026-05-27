'use client'
import Link from 'next/link'
import type { JobListItem } from '@/lib/types'
import JobProgressBar from './JobProgressBar'
import { FileText, ChevronRight } from 'lucide-react'

const STATUS_LABEL: Record<string, string> = {
  queued: 'Chờ', processing: 'Đang dịch', completed: 'Hoàn tất',
  failed: 'Thất bại', cancelled: 'Đã hủy', partial_success: 'Một phần',
}
const STATUS_DOT: Record<string, string> = {
  queued: '#d19900', processing: '#01696f', completed: '#437a22',
  failed: '#a12c7b', cancelled: '#7a7974', partial_success: '#da7101',
}

export default function JobCard({ job }: { job: JobListItem }) {
  const dot = STATUS_DOT[job.status] || '#7a7974'
  return (
    <Link href={`/jobs/${job.id}`}
      className="flex items-center gap-4 rounded-xl border p-4 transition-all hover:shadow-md"
      style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
    >
      <FileText size={20} style={{ color: 'var(--color-muted)', flexShrink: 0 }} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <p className="text-sm font-semibold truncate" style={{ color: 'var(--color-text)' }}>{job.job_name || job.id.slice(0,8)}</p>
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: dot }} />
          <span className="text-xs flex-shrink-0" style={{ color: dot }}>{STATUS_LABEL[job.status] || job.status}</span>
          <span className="text-xs ml-auto flex-shrink-0 px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg)', color: 'var(--color-muted)' }}>{job.output_format.toUpperCase()}</span>
        </div>
        <JobProgressBar percent={job.progress_percent} status={job.status} compact />
        <p className="text-xs mt-1" style={{ color: 'var(--color-muted)' }}>
          {new Date(job.created_at).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })}
        </p>
      </div>
      <ChevronRight size={16} style={{ color: 'var(--color-muted)', flexShrink: 0 }} />
    </Link>
  )
}
