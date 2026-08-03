# Agent

一个自研的多端 AI Agent：terminal / web / 桌面（Tauri，待 M5）三端复用同一核心引擎，支持多供应商、多会话、双模式与艾宾浩斯遗忘曲线记忆系统。

## 功能

- **多端**：terminal（Textual TUI + 纯文本 REPL）、React Web（FastAPI + SSE）、桌面端（M5 待做）
- **多供应商**：DeepSeek + Kimi（OpenAI 兼容协议，`config.toml` 可扩展）
- **双模式**：`think`（只思考展示计划，不执行）/ `act`（思考并执行工具）
- **多会话**：JSONL 落盘，启动选择、新建、`/search` 搜索，首轮自动命名
- **记忆系统**：艾宾浩斯遗忘曲线 —— soft 记忆随时间衰减、命中强化、低于阈值遗忘；hard 记忆（路径/凭据/决策）永不衰减；默认注入 7 天窗口，`recall_memory` 工具支持回溯
- **工具**：`run_shell`（终端命令）、`recall_memory`（记忆回溯，只读）
- **安全**：危险命令（rm/sudo/dd 等）执行前需确认；server 端默认拦截
- **体验**：SSE 流式逐字输出；对话历史超长自动摘要压缩

## 快速开始

```bash
# 环境准备
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
cd apps/web && pnpm install && cd ../..

# 配置供应商 key
#   DeepSeek: 写入 ~/.deepseek_key（最后一行为 key）
#   Kimi:     export KIMI_KEY=sk-kimi-...

# 一键启动（后端 :8899 + 前端 :5173）
./start.sh

# 或单独启动 terminal（Textual TUI）
python3 apps/terminal/main.py
# 纯文本 REPL 回退
python3 apps/terminal/main.py --plain
```

打开 http://localhost:5173 即可使用 Web 端。

## Terminal 命令

| 命令 | 说明 |
|------|------|
| `/mode think\|act` | 切换思考/执行模式 |
| `/provider <名>` | 切换供应商（deepseek / kimi） |
| `/model <名>` | 切换模型 |
| `/sessions` | 列出并切换会话 |
| `/new [标题]` | 新建会话 |
| `/search <词>` | 搜索历史会话（标题+内容） |
| `!<命令>` | 直接执行 shell，不经过 LLM |

## 架构

```
apps/
├── terminal/     # Textual TUI（tui.py）+ 纯文本 REPL 回退（main.py --plain）
├── server/       # FastAPI：/api/chat(SSE) /api/sessions /api/providers
├── web/          # React + TS + Vite + Tailwind + zustand + shadcn + AI Elements
│   └── src/{api,stores,features/{chat,sessions,controls}}
└── desktop/      # Tauri 2（M5 待做）
packages/core/agent/
├── loop.py       # 主循环：流式事件流、模式调度、记忆抽取、上下文压缩
├── modes.py      # THINK / ACT
├── providers.py  # config.toml → OpenAI 兼容 client
├── memory.py     # 艾宾浩斯记忆（fastembed + sqlite-vec）
├── session.py    # 多会话存储与搜索
└── tools.py      # 工具注册表
config.toml       # 供应商配置
```

调用链：`web/desktop → server(SSE) → core`；`terminal → core` 直连。core 零 IO 依赖，三端复用。

## 记忆系统原理

```
写入：每轮结束 LLM 抽取事实 → embedding → sim>0.9 合并强化，否则新增
      （含路径/key/端口等关键词强制标 hard）
读取：score = 语义相似度 × R，R = e^(-t/S)
      默认 7 天窗口 top-5 注入 prompt；被注入则 S×2.5（复习强化）
遗忘：soft 记忆 R<0.15 惰性删除；hard 记忆 R 恒为 1 永不衰减
回溯：recall_memory 工具可扩大天数窗口（think 模式同样可用）
```

## HTTP API

| 端点 | 说明 |
|------|------|
| `GET /api/providers` | 供应商与模型列表 |
| `GET /api/sessions` | 会话列表 |
| `POST /api/sessions` | 新建会话 |
| `GET /api/sessions/{id}` | 会话消息 + 运行状态 |
| `GET /api/sessions/search?q=` | 搜索会话 |
| `POST /api/chat` | SSE 对话（text_delta / tool_call / tool_result / done 事件流） |

## 数据位置

- 会话：`~/.agent/sessions/*.jsonl` + `index.json`
- 记忆：`~/.agent/memory.db`（SQLite + sqlite-vec）

## 开发

```bash
# 前端
cd apps/web && pnpm dev      # 开发
pnpm exec tsc -b             # 类型检查
pnpm build                   # 生产构建

# 后端
python3 apps/server/main.py  # :8899
```

技术栈与演进计划见 [PLAN.md](PLAN.md)。
