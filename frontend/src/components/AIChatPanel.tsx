'use client'

import { useState } from 'react'
import clsx from 'clsx'
import type { ChatTurn } from '@/lib/trip-types'

export interface AIChatPanelProps {
  history: ChatTurn[]
  onSend: (prompt: string) => Promise<void> | void
  busy?: boolean
}

const QUICK_PROMPTS = [
  '把午餐換成素食友善的選項',
  '行程太累了，幫我精簡成 4 站',
  '加入大稻埕的歷史景點',
  '預算改成 NT$ 800',
]

export default function AIChatPanel({ history, onSend, busy }: AIChatPanelProps) {
  const [draft, setDraft] = useState('')

  const send = async (text: string) => {
    const v = text.trim()
    if (!v || busy) return
    setDraft('')
    await onSend(v)
  }

  return (
    <section className="flex h-full flex-col rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">與 AI 對話調整</h2>
        <p className="text-[11px] text-slate-500">用自然語言告訴 AI 你想怎麼改這份行程</p>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 scrollbar-thin">
        {history.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-200 p-3 text-xs text-slate-500">
            還沒有對話。試試下面的快速指令，或自己輸入需求。
          </div>
        )}
        {history.map((turn, i) => (
          <ChatBubble key={i} turn={turn} />
        ))}
        {busy && (
          <div className="text-xs text-slate-400">AI 正在重寫行程…</div>
        )}
      </div>

      <div className="border-t border-slate-100 px-4 pb-2 pt-3">
        <div className="mb-2 flex flex-wrap gap-1">
          {QUICK_PROMPTS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => send(p)}
              disabled={busy}
              className="rounded-full border border-slate-200 px-2 py-0.5 text-[11px] text-slate-600 hover:border-blue-300 hover:text-blue-600 disabled:opacity-40"
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <form
        className="flex items-end gap-2 border-t border-slate-200 p-3"
        onSubmit={(e) => {
          e.preventDefault()
          send(draft)
        }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              send(draft)
            }
          }}
          placeholder="例如：把咖啡廳換到富錦街附近"
          rows={2}
          className="flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none"
        />
        <button
          type="submit"
          disabled={busy || draft.trim().length === 0}
          className="shrink-0 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          送出
        </button>
      </form>
    </section>
  )
}

function ChatBubble({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === 'user'
  return (
    <div className={clsx('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={clsx(
          'max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed shadow-sm',
          isUser
            ? 'rounded-br-sm bg-blue-600 text-white'
            : 'rounded-bl-sm border border-slate-200 bg-slate-50 text-slate-800',
        )}
      >
        <div className="whitespace-pre-wrap">{turn.content}</div>
        <div
          className={clsx(
            'mt-1 text-[10px]',
            isUser ? 'text-blue-100' : 'text-slate-400',
          )}
        >
          {new Date(turn.ts).toLocaleTimeString('zh-TW', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </div>
      </div>
    </div>
  )
}
