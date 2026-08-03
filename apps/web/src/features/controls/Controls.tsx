/** 顶栏控制：供应商 / 模型 / 模式切换。 */

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { BrainIcon, PlayIcon } from 'lucide-react'
import { useChat } from '@/stores/chat'

export function Controls() {
  const { providers, provider, model, mode, setProvider, setModel, setMode } = useChat()
  const models = providers.find((p) => p.name === provider)?.models ?? []

  return (
    <header className="flex items-center gap-3 border-b px-4 py-2">
      <Select value={provider} onValueChange={setProvider}>
        <SelectTrigger className="w-36">
          <SelectValue placeholder="供应商" />
        </SelectTrigger>
        <SelectContent>
          {providers.map((p) => (
            <SelectItem key={p.name} value={p.name}>
              {p.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={model} onValueChange={setModel}>
        <SelectTrigger className="w-52">
          <SelectValue placeholder="模型" />
        </SelectTrigger>
        <SelectContent>
          {models.map((m) => (
            <SelectItem key={m} value={m}>
              {m}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Button
        variant={mode === 'act' ? 'default' : 'secondary'}
        size="sm"
        onClick={() => setMode(mode === 'act' ? 'think' : 'act')}
        title={mode === 'act' ? '执行模式：会执行工具' : '思考模式：不执行任何操作'}
      >
        {mode === 'act' ? (
          <PlayIcon className="mr-1 size-4" />
        ) : (
          <BrainIcon className="mr-1 size-4" />
        )}
        {mode === 'act' ? '执行' : '思考'}
      </Button>
    </header>
  )
}
