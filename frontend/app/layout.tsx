import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'ConvertVN — Dịch Truyện Tiên Hiệp',
  description: 'Dịch truyện tiên hiệp Trung Quốc sang tiếng Việt với AI',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" data-theme="light">
      <body className="min-h-screen">
        {children}
      </body>
    </html>
  )
}
