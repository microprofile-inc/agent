/** 会话侧边栏：列表 + 搜索 + 新建。 */

import { useState } from 'react'
import { PlusIcon, SearchIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { api, type SessionMeta } from '@/api/client'
import { useChat } from '@/stores/chat'

export function SessionSidebar() {
  const { sessions, sessionId, select, create } = useChat()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<(SessionMeta & { snippet: string })[] | null>(null)

  const doSearch = async (kw: string) => {
    setQ(kw)
    if (!kw.trim()) return setHits(null)
    const r = await api.search(kw)
    setHits(r.hits)
  }

  const list = hits ?? sessions

  return (
    <aside className="flex h-full w-64 flex-col border-r">
      <div className="flex items-center gap-2 p-3">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-2 top-2.5 size-4 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="搜索会话…"
            value={q}
            onChange={(e) => doSearch(e.target.value)}
          />
        </div>
        <Button size="icon" variant="outline" onClick={create} title="新建会话">
          <PlusIcon className="size-4" />
        </Button>
      </div>
      <ScrollArea className="flex-1">
        {list.map((s) => (
          <button
            key={s.id}
            onClick={() => select(s.id)}
            className={`block w-full truncate px-4 py-2 text-left text-sm hover:bg-accent ${
              s.id === sessionId ? 'bg-accent font-medium' : ''
            }`}
          >
            {s.title}
            {'snippet' in s && (
              <span className="block truncate text-xs text-muted-foreground">
                {(s as { snippet: string }).snippet}
              </span>
            )}
          </button>
        ))}
        {hits && hits.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">无匹配会话</p>
        )}
      </ScrollArea>
    </aside>
  )
}
