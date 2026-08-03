import { useEffect } from 'react'
import { SessionSidebar } from '@/features/sessions/SessionSidebar'
import { Controls } from '@/features/controls/Controls'
import { ChatPanel } from '@/features/chat/ChatPanel'
import { useChat } from '@/stores/chat'

export default function App() {
  const init = useChat((s) => s.init)
  useEffect(() => {
    init()
  }, [init])

  return (
    <div className="flex h-screen">
      <SessionSidebar />
      <main className="flex min-w-0 flex-1 flex-col">
        <Controls />
        <ChatPanel />
      </main>
    </div>
  )
}
