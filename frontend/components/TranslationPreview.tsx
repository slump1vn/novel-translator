'use client'

import { useEffect, useMemo, useState } from 'react'
import { Clipboard, Loader2, PlayCircle } from 'lucide-react'
import { api } from '@/lib/api'
import type { ProviderConfig, TranslationPreviewResponse } from '@/lib/types'

const MAX_PREVIEW_CHARS = 60000

export default function TranslationPreview() {
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [providerId, setProviderId] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [result, setResult] = useState<TranslationPreviewResponse | null>(null)
  const [loadingProviders, setLoadingProviders] = useState(true)
  const [translating, setTranslating] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  const numberFormat = useMemo(() => new Intl.NumberFormat('vi-VN'), [])
  const selectedProvider = providers.find((provider) => provider.id === providerId)

  useEffect(() => {
    let mounted = true
    api
      .listProviderConfigs()
      .then((items) => {
        if (!mounted) return
        setProviders(items)
        setProviderId(items.find((item) => item.is_default)?.id || items[0]?.id || '')
      })
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : 'Không thể tải provider')
      })
      .finally(() => {
        if (mounted) setLoadingProviders(false)
      })

    return () => {
      mounted = false
    }
  }, [])

  const handleTranslate = async () => {
    const text = sourceText.trim()
    if (!text) {
      setError('Vui lòng nhập nội dung cần dịch')
      return
    }
    if (text.length > MAX_PREVIEW_CHARS) {
      setError(`Nội dung vượt quá ${numberFormat.format(MAX_PREVIEW_CHARS)} ký tự`)
      return
    }
    setTranslating(true)
    setError('')
    setCopied(false)
    try {
      const response = await api.translatePreview({
        text,
        provider_config_id: providerId || undefined,
      })
      setResult(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể dịch thử')
    } finally {
      setTranslating(false)
    }
  }

  const copyResult = async () => {
    if (!result?.translated_text) return
    try {
      await navigator.clipboard.writeText(result.translated_text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('Không thể copy bản dịch')
    }
  }

  return (
    <div className="rounded-2xl border p-4 sm:p-5 space-y-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
            Dịch thử
          </h2>
          <div className="text-xs" style={{ color: 'var(--color-muted)' }}>
            {numberFormat.format(sourceText.length)} / {numberFormat.format(MAX_PREVIEW_CHARS)}
          </div>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <select
            value={providerId}
            disabled={loadingProviders || translating || providers.length === 0}
            onChange={(event) => setProviderId(event.target.value)}
            className="w-full sm:w-64 rounded-lg border px-3 py-2 text-sm outline-none transition-all focus:ring-1"
            style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
            aria-label="Provider dịch thử"
          >
            {providers.length === 0 ? (
              <option value="">Chưa có provider</option>
            ) : (
              providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.config_name} · {provider.model_name}
                </option>
              ))
            )}
          </select>
          <button
            type="button"
            onClick={handleTranslate}
            disabled={translating || loadingProviders || providers.length === 0}
            className="flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-all disabled:opacity-40"
            style={{ background: 'var(--color-brand)' }}
          >
            {translating ? (
              <>
                <Loader2 size={15} className="animate-spin" /> Đang dịch...
              </>
            ) : (
              <>
                <PlayCircle size={15} /> Dịch thử
              </>
            )}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <textarea
          value={sourceText}
          onChange={(event) => {
            setSourceText(event.target.value)
            if (result) setResult(null)
            if (error) setError('')
          }}
          className="min-h-[320px] resize-y rounded-xl border p-3 text-sm leading-6 outline-none transition-all focus:ring-1"
          style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
          placeholder="Dán nội dung chương cần dịch"
        />

        <div className="min-h-[320px] rounded-xl border p-3 text-sm leading-6 whitespace-pre-wrap overflow-auto" style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: result ? 'var(--color-text)' : 'var(--color-muted)' }}>
          {result?.translated_text || 'Bản dịch sẽ xuất hiện ở đây'}
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs" style={{ color: 'var(--color-muted)' }}>
          {result
            ? `${selectedProvider?.config_name || result.provider} · ${result.model_name} · ${result.chunk_count} chunk · ${(result.elapsed_ms / 1000).toFixed(1)}s`
            : selectedProvider
              ? `${selectedProvider.provider} · ${selectedProvider.model_name}`
              : 'Cần cấu hình provider trước khi dịch thử'}
        </div>

        <button
          type="button"
          onClick={copyResult}
          disabled={!result?.translated_text}
          className="flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-opacity hover:opacity-70 disabled:opacity-40"
          style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
        >
          <Clipboard size={14} /> {copied ? 'Đã copy' : 'Copy'}
        </button>
      </div>

      {error && (
        <p className="rounded-lg px-3 py-2 text-sm" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
          {error}
        </p>
      )}
    </div>
  )
}
