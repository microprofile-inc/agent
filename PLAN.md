# Agent 开发方案

## 1. 需求列表

| # | 需求 | 决策 |
|---|------|------|
| 1 | 多端支持：独立桌面应用、terminal、web | 桌面 = **Tauri 2**，web 后端 = **FastAPI** |
| 2 | 记忆系统（具体方案稍后提供） | 接口先行 |
| 3 | 多供应商、多模型支持 | OpenAI 兼容协议 + config.toml |
| 4 | 模式切换：思考（不执行任何操作）/ 执行（思考 + 执行操作） | core 拦截 tool_calls |
| 5 | Web 前端：**React**，**monorepo**，清晰拆分功能和文件 | 已确认 |
| 6 | 多 session：启动时选择/新建 session，支持搜索历史会话 | 已确认 |

## 2. 技术栈

| 层 | 选型 |
|---|------|
| 语言 | Python 3.10+（引擎/后端）+ TypeScript（前端） |
| LLM SDK | `openai`（DeepSeek/Moonshot/Qwen/OpenAI 均兼容） |
| 后端 | FastAPI + SSE（uvicorn） |
| Web 前端 | React 18 + TypeScript + Vite + Tailwind + zustand + shadcn/ui + AI Elements |
| 桌面 | Tauri 2（加载 web 构建产物，PyInstaller sidecar 拉起后端） |
| Monorepo | pnpm workspace（JS）+ pip/uv（Python）混合 |
| 配置 | `config.toml`（标准库 `tomllib`） |
| 记忆 | 抽象接口 + JSONL 起步，长期方案待定 |

## 3. Monorepo 目录结构

```
agent/
├── apps/
│   ├── terminal/              # Python REPL（直连 core）
│   ├── server/                # FastAPI：/chat(SSE) /models /modes
│   ├── web/                   # React + Vite + TS
│   │   └── src/
│   │       ├── features/
│   │       │   ├── chat/      # 对话流（消息列表、SSE 订阅）
│   │       │   ├── modes/     # think/act 切换
│   │       │   └── providers/ # 供应商/模型选择
│   │       ├── api/           # SSE client、REST 封装
│   │       ├── stores/        # 状态管理
│   │       └── shared/ui/     # 通用组件
│   └── desktop/               # Tauri 2 shell（复用 apps/web 产物）
├── packages/
│   └── core/                  # agent 引擎（纯逻辑，零 IO）
│       └── agent/
│           ├── loop.py        # run_turn → Event 流
│           ├── modes.py       # THINK 拦截 / ACT 执行
│           ├── providers.py   # config.toml → OpenAI client
│           ├── memory.py      # 抽象 + JSONL 实现
│           └── tools.py       # 工具注册表
├── config.toml                # 供应商配置
├── pyproject.toml             # Python 依赖（openai / fastapi / uvicorn）
├── pnpm-workspace.yaml
└── package.json
```

**调用链**：web / desktop → server(SSE) → core；terminal → core 直连。core 不含任何 FastAPI/React 依赖。

## 4. 核心接口

```python
# loop.py
class Agent:
    def __init__(self, provider, model, mode: Mode, memory: Memory, tools: list[Tool]): ...
    def run_turn(self, user_input: str) -> Iterator[Event]: ...
    # Event: text_delta / tool_call / tool_result / done

# modes.py
class Mode(Enum):
    THINK = "think"   # 收到 tool_calls 不执行，仅展示模型意图
    ACT   = "act"     # 正常执行工具

# memory.py
class Memory(ABC):
    def write(self, messages: list) -> None: ...
    def read(self, query: str) -> str: ...   # 注入 prompt 的记忆文本

# session.py
class SessionStore:
    """多 session 管理：~/.agent/sessions/<id>.jsonl + index.json 元数据"""
    def create(self, title: str) -> Session: ...
    def list(self) -> list[Session]: ...      # 启动时供选择
    def load(self, session_id: str) -> list[Message]: ...
    def search(self, keyword: str) -> list[Session]: ...  # 标题+内容子串匹配
```

**session 行为**：启动时列出全部 session（最近排序），可输入序号选择、`new` 新建、`/search <词>` 搜索；terminal 内 `/sessions` 切换、`/search` 检索。

## 5. 多供应商（config.toml）

```toml
[providers.deepseek]
base_url = "https://api.deepseek.com"
key_file = "~/.deepseek_key"
default_model = "deepseek-chat"

[providers.openai]
key_env = "OPENAI_API_KEY"
default_model = "gpt-4o"
```

运行时切换：`/provider <名>` `/model <名>`（terminal）或前端下拉框（web/desktop）。

## 6. 里程碑

| 阶段 | 内容 | 验收 |
|------|------|------|
| M0 | 最小可用版（单文件 terminal） | 已完成 |
| M1 | monorepo 骨架 + core 模块化 + 模式系统 + 多 session（选择/新建/搜索）+ terminal 前端 | terminal 模式切换 + session 选择/搜索验证通过 |
| M2 | config.toml 多供应商 + 切换命令 | 已完成（deepseek + kimi，kimi 走 api.kimi.com/coding/v1） |
| M3 | 记忆系统完整实现（按用户提供的方案） | 已完成（注：Intel Mac 无 torch 轮，embedding 改用 fastembed/ONNX 跑同一 MiniLM 模型） |

### M3 记忆系统设计（已确认）

- **Embedding**：sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2`（本地，384 维）
- **存储**：sqlite-vec（`~/.agent/memory.db`），装不上则降级纯 SQLite + Python 余弦
- **双层记忆**：soft 走艾宾浩斯 `R = e^(-t/S)`，命中强化 `S *= 2.5`；hard/pinned 永不衰减
- **抽取**：每轮结束多调一次 LLM 抽取记忆并打 kind 标签 + 关键词规则兜底（路径/URL/key/密码/端口/明确指令 → 强制 hard）
- **检索**：默认注入 7 天内 top-5（score = sim × R > 0.3）；`recall_memory` 工具支持模型自主回溯更久
- **遗忘**：惰性清理，read 时删除 R<0.15 的 soft 记忆
| M4 | FastAPI server + React web | 已完成（浏览器对话/切模式/切模型/会话搜索全通） |
| M5 | Tauri 2 桌面端 | 独立窗口运行 |
| 收尾 | 流式逐字输出 / 危险命令确认 / 上下文压缩 / start.sh / README | 已完成（2026-07-25） |

## 7. 约束

- 标准库优先，依赖按需引入
- core 与 IO 完全解耦，三端复用
- 每步改动用真实请求验证

## 8. 已确认决策

1. 记忆系统具体方案（用户稍后提供）
2. 桌面端后端形态：Tauri sidecar + **PyInstaller** 打包 Python，App 启动时拉起后端 ✅
3. JS 包管理器：**pnpm** ✅
4. 前端：**zustand + tailwindcss** ✅
