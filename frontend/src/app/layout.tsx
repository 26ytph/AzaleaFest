import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Taipei WanderGuard',
  description: '把 IG / Threads 的旅遊靈感整理成台北行程',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-TW">
      <body>{children}</body>
    </html>
  )
}
