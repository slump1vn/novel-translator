'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, Download, Loader2, Pause, Play, RefreshCw, XCircle } from 'lucide-react'
import { api } from '@/lib/api'
import type { DownloadInfo, JobChunkResult, JobDetail, JobLog, JobStep, ProviderConfig } from '@/lib/types'
import NavBar from '@/components/NavBar'
import JobProgressBar from '@/components/JobProgressBar'
import StepTimeline from '@/components/StepTimeline'
import JobLogPanel from '@/components/JobLogPanel'
import JobChunkResultsPanel from '@/components/JobChunkResultsPanel'
import GlossaryEditor from '@/components/GlossaryEditor'

const STATUS_LABEL: Record<string, string> = {
  queued: 'Chờ xử lý',
  processing: 'Đang dịch',
  paused: 'Tạm dừng',
  awaiting_glossary_review: 'Chờ duyệt từ điển',
  completed: 'Hoàn tất',
  failed: 'Thất bại',
  cancelled: 'Đã hủy',
  partial_success: 'Một phần thành công',
}

const STATUS_COLOR: Record<string, string> = {
  queued: '#d19900',
  processing: '#01696f',
  paused: '#7a4dd8',
  awaiting_glossary_review: '#b15d00',
  completed: '#437a22',
  failed: '#a12c7b',
  cancelled: '#7a7974',
  partial_success: '#da7101',
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [job, setJob] = useState<JobDetail | null>(null)
  const [steps, setSteps] = useState<JobStep[]>([])
  const [logs, setLogs] = useState<JobLog[]>([])
  const [chunks, setChunks] = useState<JobChunkResult[]>([])
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [selectedProviderId, setSelectedProviderId] = useState('')
  const [selectedGlossaryProviderId, setSelectedGlossaryProviderId] = useState('')
  const [download, setDownload] = useState<DownloadInfo | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [pausing, setPausing] = useState(false)
  const [resuming, setResuming] = useState(false)
  const [changingProvider, setChangingProvider] = useState(false)
  const [changingGlossaryProvider, setChangingGlossaryProvider] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadingPartial, setDownloadingPartial] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [jobDetail, stepResult, logResult, chunkResult] = await Promise.all([
        api.getJob(id),
        api.getJobSteps(id),
        api.getJobLogs(id),
        api.getJobChunks(id),
      ])
      setJob(jobDetail)
      setSteps(stepResult.steps)
      setLogs(logResult.logs)
      setChunks(chunkResult.chunks)
      setError('')
      if (jobDetail.status === 'completed') {
        setDownload(await api.getDownload(id).catch(() => null))
      } else {
        setDownload(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tải chi tiết job')
    }
  }, [id])

  useEffect(() => {
    load()
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [load])

  useEffect(() => {
    api
      .listProviderConfigs()
      .then(setProviders)
      .catch((err) => setError(err instanceof Error ? err.message : 'Không thể tải danh sách model'))
  }, [])

  useEffect(() => {
    if (job?.provider_config_id) {
      setSelectedProviderId(job.provider_config_id)
    }
  }, [job?.provider_config_id])

  useEffect(() => {
    if (job?.glossary_provider_config_id) {
      setSelectedGlossaryProviderId(job.glossary_provider_config_id)
    } else if (job?.provider_config_id) {
      setSelectedGlossaryProviderId(job.provider_config_id)
    }
  }, [job?.glossary_provider_config_id, job?.provider_config_id])

  useEffect(() => {
    if (!selectedProviderId && providers[0]) {
      setSelectedProviderId(providers[0].id)
    }
  }, [providers, selectedProviderId])

  useEffect(() => {
    if (!selectedGlossaryProviderId && providers[0]) {
      setSelectedGlossaryProviderId(providers[0].id)
    }
  }, [providers, selectedGlossaryProviderId])

  const handleCancel = async () => {
    setCancelling(true)
    setError('')
    try {
      setJob(await api.cancelJob(id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể hủy job')
    } finally {
      setCancelling(false)
    }
  }

  const handlePause = async () => {
    setPausing(true)
    setError('')
    try {
      setJob(await api.pauseJob(id))
      void load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tạm dừng job')
    } finally {
      setPausing(false)
    }
  }

  const handleResume = async () => {
    setResuming(true)
    setError('')
    try {
      setJob(await api.resumeJob(id))
      void load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tiếp tục job')
    } finally {
      setResuming(false)
    }
  }

  const handleChangeProvider = async () => {
    if (!selectedProviderId) return
    setChangingProvider(true)
    setError('')
    try {
      const updated = await api.updateJobProvider(id, selectedProviderId)
      setJob(updated)
      void load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể đổi model cho job')
    } finally {
      setChangingProvider(false)
    }
  }

  const handleChangeGlossaryProvider = async () => {
    if (!selectedGlossaryProviderId) return
    setChangingGlossaryProvider(true)
    setError('')
    try {
      const updated = await api.updateJobGlossaryProvider(id, selectedGlossaryProviderId)
      setJob(updated)
      void load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể đổi model tạo từ điển')
    } finally {
      setChangingGlossaryProvider(false)
    }
  }

  const handleDownload = async () => {
    if (!download) return
    setDownloading(true)
    setError('')
    try {
      await api.downloadJobFile(id, download.filename)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tải file đã dịch')
    } finally {
      setDownloading(false)
    }
  }

  const handlePartialDownload = async () => {
    setDownloadingPartial(true)
    setError('')
    try {
      await api.downloadPartialJobFile(id, `${job?.job_name || 'translation'}.partial.epub`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tải EPUB tạm')
    } finally {
      setDownloadingPartial(false)
    }
  }

  if (!job) {
    return (
      <div style={{ background: 'var(--color-bg)' }} className="min-h-screen">
        <NavBar />
        <div className="max-w-2xl mx-auto px-4 py-20 space-y-4">
          {error ? (
            <div className="rounded-lg px-3 py-2 text-sm" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
              {error}
            </div>
          ) : (
            [1, 2, 3, 4].map((item) => (
              <div key={item} className="h-16 rounded-xl animate-pulse" style={{ background: 'var(--color-surface)' }} />
            ))
          )}
        </div>
      </div>
    )
  }

  const statusColor = STATUS_COLOR[job.status] || '#7a7974'
  const showGlossary = job.status === 'awaiting_glossary_review' || steps.some((step) => step.step_name === 'glossary_generated' && step.status === 'completed')
  const canControlJob = ['queued', 'processing', 'paused'].includes(job.status)
  const glossaryEditable = ['queued', 'processing', 'paused', 'awaiting_glossary_review'].includes(job.status)
  const glossaryStep = steps.find((step) => step.step_name === 'glossary_generated')
  const canChangeGlossaryProvider = canControlJob && (glossaryStep?.status ?? 'pending') === 'pending'
  const providerChanged = Boolean(selectedProviderId && selectedProviderId !== job.provider_config_id)
  const glossaryProviderChanged = Boolean(selectedGlossaryProviderId && selectedGlossaryProviderId !== (job.glossary_provider_config_id || job.provider_config_id))
  const hasPartialTranslation = chunks.some((chunk) => Boolean(chunk.translated_text?.trim()))

  return (
    <div style={{ background: 'var(--color-bg)' }} className="min-h-screen">
      <NavBar />
      <main className="max-w-6xl mx-auto px-4 py-10 space-y-6">
        <button
          onClick={() => router.push('/')}
          className="flex items-center gap-2 text-sm transition-opacity hover:opacity-70"
          style={{ color: 'var(--color-muted)' }}
        >
          <ArrowLeft size={14} /> Quay lại
        </button>

        {error && (
          <div className="rounded-lg px-3 py-2 text-sm" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_420px] gap-6 items-start">
          <div className="space-y-6">
            <div className="rounded-2xl p-6 border space-y-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h1 className="text-lg font-bold truncate" style={{ color: 'var(--color-text)' }}>
                    {job.source_file?.filename || job.job_name || 'Job'}
                  </h1>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>
                    ID: {id.slice(0, 8)}... · {job.output_format.toUpperCase()}
                  </p>
                </div>
                <span className="text-xs font-semibold px-3 py-1 rounded-full flex-shrink-0" style={{ background: `${statusColor}22`, color: statusColor }}>
                  {STATUS_LABEL[job.status] || job.status}
                </span>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium" style={{ color: 'var(--color-muted)' }}>
                    Tổng tiến độ
                  </span>
                  <span className="text-xs tabular-nums font-semibold" style={{ color: 'var(--color-text)' }}>
                    {Math.max(0, Math.min(100, job.progress_percent))}%
                  </span>
                </div>
                <JobProgressBar percent={job.progress_percent} status={job.status} />
              </div>

              <div className="grid grid-cols-3 gap-3 text-center">
                {[
                  ['Tổng chunk', job.total_chunks ?? '-'],
                  ['Đã dịch', job.translated_chunks],
                  ['Lỗi', job.failed_chunks],
                ].map(([label, value]) => (
                  <div key={label as string} className="rounded-lg p-3" style={{ background: 'var(--color-bg)' }}>
                    <p className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>
                      {value}
                    </p>
                    <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                      {label}
                    </p>
                  </div>
                ))}
              </div>

              {job.provider && (
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                  Model dịch:{' '}
                  <strong style={{ color: 'var(--color-text)' }}>
                    {job.provider.provider} / {job.provider.model_name}
                  </strong>
                </p>
              )}

              {job.glossary_provider && (
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                  Model tạo từ điển:{' '}
                  <strong style={{ color: 'var(--color-text)' }}>
                    {job.glossary_provider.provider} / {job.glossary_provider.model_name}
                  </strong>
                </p>
              )}

              {canControlJob && providers.length > 0 && (
                <div className="flex flex-col gap-2">
                  <label className="text-xs font-medium" style={{ color: 'var(--color-muted)' }}>
                    Model cho các chunk tiếp theo
                  </label>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <select
                      value={selectedProviderId}
                      onChange={(event) => setSelectedProviderId(event.target.value)}
                      className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm"
                      style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                    >
                      {providers.map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.config_name} · {provider.provider}/{provider.model_name}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={handleChangeProvider}
                      disabled={!providerChanged || changingProvider}
                      className="inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
                      style={{ background: 'var(--color-brand)' }}
                    >
                      {changingProvider ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                      Đổi model
                    </button>
                  </div>
                </div>
              )}

              {providers.length > 0 && (
                <div className="flex flex-col gap-2">
                  <label className="text-xs font-medium" style={{ color: 'var(--color-muted)' }}>
                    Model tạo từ điển
                  </label>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <select
                      value={selectedGlossaryProviderId}
                      onChange={(event) => setSelectedGlossaryProviderId(event.target.value)}
                      disabled={!canChangeGlossaryProvider}
                      className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm disabled:opacity-60"
                      style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                    >
                      {providers.map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.config_name} · {provider.provider}/{provider.model_name}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={handleChangeGlossaryProvider}
                      disabled={!canChangeGlossaryProvider || !glossaryProviderChanged || changingGlossaryProvider}
                      className="inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
                      style={{ background: 'var(--color-brand)' }}
                    >
                      {changingGlossaryProvider ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                      Đổi model từ điển
                    </button>
                  </div>
                  {!canChangeGlossaryProvider && (
                    <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                      Bước tạo từ điển đã bắt đầu nên không thể đổi model nữa.
                    </p>
                  )}
                </div>
              )}

              {job.error_message && (
                <div className="rounded-lg p-3 text-sm" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
                  {job.error_message}
                </div>
              )}

              <div className="flex flex-wrap gap-3 pt-2">
                {job.status === 'completed' && download && (
                  <button
                    type="button"
                    onClick={handleDownload}
                    disabled={downloading}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors"
                    style={{ background: 'var(--color-brand)' }}
                  >
                    {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                    {downloading ? 'Đang tải...' : `Tải về ${download.filename}`}
                  </button>
                )}
                {job.status !== 'completed' && hasPartialTranslation && (
                  <button
                    type="button"
                    onClick={handlePartialDownload}
                    disabled={downloadingPartial}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors disabled:opacity-40"
                    style={{ background: 'var(--color-brand)' }}
                  >
                    {downloadingPartial ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                    {downloadingPartial ? 'Đang tạo EPUB...' : 'Tải EPUB tạm'}
                  </button>
                )}
                {['queued', 'processing'].includes(job.status) && (
                  <button
                    onClick={handlePause}
                    disabled={pausing}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-opacity hover:opacity-70 disabled:opacity-40"
                    style={{ background: '#7a4dd822', color: '#7a4dd8' }}
                  >
                    {pausing ? <Loader2 size={14} className="animate-spin" /> : <Pause size={14} />}
                    {pausing ? 'Đang tạm dừng...' : 'Tạm dừng'}
                  </button>
                )}
                {job.status === 'paused' && (
                  <button
                    onClick={handleResume}
                    disabled={resuming}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-opacity hover:opacity-70 disabled:opacity-40"
                    style={{ background: '#437a2222', color: '#437a22' }}
                  >
                    {resuming ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    {resuming ? 'Đang tiếp tục...' : 'Tiếp tục'}
                  </button>
                )}
                {['queued', 'processing', 'paused', 'awaiting_glossary_review'].includes(job.status) && (
                  <button
                    onClick={handleCancel}
                    disabled={cancelling}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-opacity hover:opacity-70 disabled:opacity-40"
                    style={{ background: '#a12c7b22', color: '#a12c7b' }}
                  >
                    <XCircle size={14} /> {cancelling ? 'Đang hủy...' : 'Hủy job'}
                  </button>
                )}
              </div>
            </div>

            <StepTimeline steps={steps} currentStep={job.current_step} />

            {showGlossary && (
              <GlossaryEditor
                jobId={id}
                editable={glossaryEditable}
                showApprove={job.status === 'awaiting_glossary_review'}
                onApproved={(updatedJob) => {
                  setJob(updatedJob)
                  void load()
                }}
              />
            )}
          </div>

          <div className="space-y-6">
            <JobChunkResultsPanel chunks={chunks} />
            <JobLogPanel logs={logs} />
          </div>
        </div>
      </main>
    </div>
  )
}
