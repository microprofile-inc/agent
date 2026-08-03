/** 聊天主面板：消息流（AI Elements）+ 工具调用展示 + 输入框。 */

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation'
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message'
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  type PromptInputMessage,
} from '@/components/ai-elements/prompt-input'
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from '@/components/ai-elements/tool'
import { Spinner } from '@/components/ui/spinner'
import { useChat, type ToolRun } from '@/stores/chat'

function ToolCard({ t }: { t: ToolRun }) {
  return (
    <Tool>
      <ToolHeader
        type={`tool-${t.tool}`}
        state={t.result === undefined ? 'input-available' : 'output-available'}
      />
      <ToolContent>
        <ToolInput input={t.args} />
        {t.result !== undefined && <ToolOutput output={t.result} errorText={undefined} />}
      </ToolContent>
    </Tool>
  )
}

export function ChatPanel() {
  const { messages, streaming, send } = useChat()

  const onSubmit = (msg: PromptInputMessage) => {
    if (msg.text.trim()) send(msg.text)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Conversation className="flex-1">
        <ConversationContent>
          {messages.length === 0 && (
            <ConversationEmptyState
              title="开始对话"
              description="输入消息，agent 会思考并可执行终端命令"
            />
          )}
          {messages.map((m, i) => (
            <Message key={i} from={m.role}>
              <MessageContent>
                {m.tools.map((t, j) => (
                  <ToolCard key={j} t={t} />
                ))}
                {m.content && <MessageResponse>{m.content}</MessageResponse>}
                {m.role === 'assistant' &&
                  !m.content &&
                  m.tools.length === 0 &&
                  streaming && <Spinner />}
              </MessageContent>
            </Message>
          ))}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="border-t p-3">
        <PromptInput onSubmit={onSubmit}>
          <PromptInputBody>
            <PromptInputTextarea
              placeholder="输入消息，Enter 发送，Shift+Enter 换行"
              disabled={streaming}
            />
          </PromptInputBody>
          <PromptInputFooter className="justify-end">
            <PromptInputSubmit disabled={streaming} status={streaming ? 'streaming' : 'ready'} />
          </PromptInputFooter>
        </PromptInput>
      </div>
    </div>
  )
}
