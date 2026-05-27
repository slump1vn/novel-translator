import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react'
import type { JobStep } from '@/lib/types'

const STEP_NAMES: Record<string, string> = {
  upload_received: 'Nhận file',
  file_validated: 'Kiểm tra file',
  text_extracted: 'Trích xuất nội dung',
  chunked: 'Chia đoạn',
  translating: 'Đang dịch',
  merged: 'Ghép bản dịch',
  output_built: 'Tạo file đầu ra',
  download_ready: 'Sẵn sàng tải',
}

interface Props {
  steps: JobStep[]
  currentStep: string
}

export default function StepTimeline({ steps, currentStep }: Props) {
  if (!steps.length) return null

  return (
    <div className="rounded-2xl border p-5" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <h2 className="font-semibold mb-4 text-sm" style={{ color: 'var(--color-text)' }}>
        Tiến trình xử lý
      </h2>
      <ol className="space-y-3">
        {steps.map((step) => {
          const isActive = step.step_name === currentStep
          const isDone = step.status === 'completed'
          const isFailed = step.status === 'failed'

          return (
            <li key={step.step_name} className="flex items-start gap-3">
              <div className="mt-0.5 flex-shrink-0">
                {isFailed ? (
                  <XCircle size={18} style={{ color: '#a12c7b' }} />
                ) : isDone ? (
                  <CheckCircle2 size={18} style={{ color: '#437a22' }} />
                ) : isActive ? (
                  <Loader2 size={18} className="animate-spin" style={{ color: '#01696f' }} />
                ) : (
                  <Circle size={18} style={{ color: 'var(--color-border)' }} />
                )}
              </div>
              <div className="flex-1">
                <p className="text-sm" style={{ color: isDone || isActive ? 'var(--color-text)' : 'var(--color-muted)', fontWeight: isActive ? 600 : 400 }}>
                  {STEP_NAMES[step.step_name] || step.step_name}
                </p>
                {step.started_at && (
                  <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>
                    {new Date(step.started_at).toLocaleTimeString('vi-VN')}
                    {step.ended_at && ` -> ${new Date(step.ended_at).toLocaleTimeString('vi-VN')}`}
                  </p>
                )}
                {step.error_message && (
                  <p className="text-xs mt-0.5" style={{ color: '#a12c7b' }}>
                    {step.error_message}
                  </p>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
