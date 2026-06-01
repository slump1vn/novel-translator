'use client'

import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Loader2, Plus, Save, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import type { GlossaryEntry, GlossaryEntryInput, JobDetail } from '@/lib/types'

const CATEGORY_OPTIONS = [
  ['person', 'Nhân vật'],
  ['place', 'Địa danh'],
  ['organization', 'Tổ chức'],
  ['title', 'Danh xưng'],
  ['technique', 'Công pháp'],
  ['item', 'Vật phẩm'],
  ['realm', 'Cảnh giới'],
  ['other', 'Khác'],
] as const

interface Props {
  jobId: string
  editable: boolean
  showApprove?: boolean
  onApproved?: (job: JobDetail) => void
}

function toInput(entry: GlossaryEntry): GlossaryEntryInput {
  return {
    id: entry.id,
    source_term: entry.source_term,
    translated_term: entry.translated_term,
    category: entry.category || 'other',
    note: entry.note || '',
    occurrence_count: entry.occurrence_count || 0,
    position: entry.position || 0,
  }
}

function normalizeEntries(entries: GlossaryEntryInput[]): GlossaryEntryInput[] {
  return entries
    .map((entry, position) => ({
      ...entry,
      source_term: entry.source_term.trim(),
      translated_term: entry.translated_term.trim(),
      category: entry.category || 'other',
      note: entry.note?.trim() || null,
      occurrence_count: Math.max(0, Number(entry.occurrence_count) || 0),
      position,
    }))
    .filter((entry) => entry.source_term && entry.translated_term)
}

export default function GlossaryEditor({ jobId, editable, showApprove = false, onApproved }: Props) {
  const [entries, setEntries] = useState<GlossaryEntryInput[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [approving, setApproving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    api
      .getJobGlossary(jobId)
      .then((result) => {
        if (!active) return
        setEntries(result.entries.map(toInput))
      })
      .catch((err) => {
        if (!active) return
        setError(err instanceof Error ? err.message : 'Không thể tải từ điển')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [jobId])

  const validEntries = useMemo(() => normalizeEntries(entries), [entries])
  const canSubmit = editable && !loading && !saving && !approving

  const updateEntry = (index: number, patch: Partial<GlossaryEntryInput>) => {
    setSaved(false)
    setEntries((current) => current.map((entry, itemIndex) => (itemIndex === index ? { ...entry, ...patch } : entry)))
  }

  const addEntry = () => {
    setSaved(false)
    setEntries((current) => [
      ...current,
      {
        source_term: '',
        translated_term: '',
        category: 'other',
        note: '',
        occurrence_count: 0,
        position: current.length,
      },
    ])
  }

  const removeEntry = (index: number) => {
    setSaved(false)
    setEntries((current) => current.filter((_, itemIndex) => itemIndex !== index))
  }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      const result = await api.updateJobGlossary(jobId, validEntries)
      setEntries(result.entries.map(toInput))
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể lưu từ điển')
    } finally {
      setSaving(false)
    }
  }

  const approve = async () => {
    if (!onApproved) return
    setApproving(true)
    setError('')
    try {
      const job = await api.approveJobGlossary(jobId, validEntries)
      onApproved(job)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể duyệt từ điển')
    } finally {
      setApproving(false)
    }
  }

  return (
    <div className="rounded-2xl border p-5 space-y-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>
            Từ điển tên riêng
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>
            {validEntries.length} mục
          </p>
        </div>
        {editable && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={addEntry}
              disabled={!canSubmit}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-opacity hover:opacity-80 disabled:opacity-40"
              style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}
            >
              <Plus size={14} /> Thêm dòng
            </button>
            <button
              type="button"
              onClick={save}
              disabled={!canSubmit}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: '#01696f' }}
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Lưu
            </button>
            {showApprove && (
              <button
                type="button"
                onClick={approve}
                disabled={!canSubmit}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
                style={{ background: 'var(--color-brand)' }}
              >
                {approving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} Duyệt và dịch tiếp
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg px-3 py-2 text-sm" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
          {error}
        </div>
      )}
      {saved && (
        <div className="rounded-lg px-3 py-2 text-sm" style={{ background: '#437a2211', color: '#437a22' }}>
          Đã lưu từ điển
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-muted)' }}>
          <Loader2 size={16} className="animate-spin" /> Đang tải từ điển...
        </div>
      ) : entries.length === 0 ? (
        <div className="rounded-lg px-3 py-6 text-sm text-center" style={{ background: 'var(--color-bg)', color: 'var(--color-muted)' }}>
          Từ điển đang trống.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead>
              <tr style={{ color: 'var(--color-muted)' }}>
                <th className="text-left font-medium pb-2 pr-3">Nguồn</th>
                <th className="text-left font-medium pb-2 pr-3">Tên chuẩn</th>
                <th className="text-left font-medium pb-2 pr-3">Loại</th>
                <th className="text-left font-medium pb-2 pr-3">Số lần</th>
                <th className="text-left font-medium pb-2 pr-3">Ghi chú</th>
                {editable && <th className="w-10 pb-2" />}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, index) => (
                <tr key={`${entry.id || 'new'}-${index}`} className="border-t" style={{ borderColor: 'var(--color-border)' }}>
                  <td className="py-2 pr-3">
                    <input
                      value={entry.source_term}
                      disabled={!editable}
                      onChange={(event) => updateEntry(index, { source_term: event.target.value })}
                      className="w-full rounded-lg border px-3 py-2 disabled:opacity-70"
                      style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                    />
                  </td>
                  <td className="py-2 pr-3">
                    <input
                      value={entry.translated_term}
                      disabled={!editable}
                      onChange={(event) => updateEntry(index, { translated_term: event.target.value })}
                      className="w-full rounded-lg border px-3 py-2 disabled:opacity-70"
                      style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                    />
                  </td>
                  <td className="py-2 pr-3">
                    <select
                      value={entry.category || 'other'}
                      disabled={!editable}
                      onChange={(event) => updateEntry(index, { category: event.target.value })}
                      className="w-full rounded-lg border px-3 py-2 disabled:opacity-70"
                      style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                    >
                      {CATEGORY_OPTIONS.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2 pr-3 tabular-nums" style={{ color: 'var(--color-muted)' }}>
                    {entry.occurrence_count}
                  </td>
                  <td className="py-2 pr-3">
                    <input
                      value={entry.note || ''}
                      disabled={!editable}
                      onChange={(event) => updateEntry(index, { note: event.target.value })}
                      className="w-full rounded-lg border px-3 py-2 disabled:opacity-70"
                      style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                    />
                  </td>
                  {editable && (
                    <td className="py-2">
                      <button
                        type="button"
                        title="Xóa"
                        onClick={() => removeEntry(index)}
                        className="h-9 w-9 inline-flex items-center justify-center rounded-lg transition-opacity hover:opacity-70"
                        style={{ background: '#a12c7b11', color: '#a12c7b' }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
