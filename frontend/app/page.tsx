'use client'
import { useState, useEffect } from 'react'
import Link from 'next/link'
import { api } from '@/lib/api'
import type { JobListItem } from '@/lib/types'
import UploadZone from '@/components/UploadZone'
import JobCard from '@/components/JobCard'
import NavBar from '@/components/NavBar'
import { RefreshCw } from 'lucide-react'

export default function HomePage() {
  const [jobs, setJobs] = useState<JobListItem[]>([])
  const [loading, setLoading] = useState(true)

  const fetchJobs = async () => {
    try { setJobs(await api.listJobs()) } catch {} finally { setLoading(false) }
  }

  useEffect(() => { fetchJobs(); const t = setInterval(fetchJobs, 5000); return () => clearInterval(t) }, [])

  return (
    <div className="min-h-screen" style={{ background: 'var(--color-bg)' }}>
      <NavBar />
      <main className="max-w-4xl mx-auto px-4 py-10 space-y-10">
        <section>
          <h1 className="text-2xl font-bold mb-1" style={{ color: 'var(--color-text)' }}>Dịch truyện mới</h1>
          <p className="text-sm mb-6" style={{ color: 'var(--color-muted)' }}>Hỗ trợ .txt · .epub · .pdf — tự động trích chương, dịch song song, xuất EPUB/TXT</p>
          <UploadZone onJobCreated={fetchJobs} />
        </section>

        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>Lịch sử dịch</h2>
            <button onClick={fetchJobs} className="p-1.5 rounded-md transition-colors hover:opacity-70" style={{ color: 'var(--color-muted)' }}>
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
          {loading && jobs.length === 0 ? (
            <div className="space-y-3">{[1,2,3].map(i=><div key={i} className="h-20 rounded-xl animate-pulse" style={{ background: 'var(--color-surface)' }} />)}</div>
          ) : jobs.length === 0 ? (
            <div className="text-center py-16 rounded-xl border border-dashed" style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)' }}>
              <p className="text-4xl mb-3">📚</p>
              <p className="font-medium">Chưa có job nào. Hãy tải lên truyện đầu tiên!</p>
            </div>
          ) : (
            <div className="space-y-3">
              {jobs.map(j => <JobCard key={j.id} job={j} />)}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
