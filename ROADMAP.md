# Roadmap

对标 opencode / Claude Code 的差距分析与演进路线（2026-08 评估，不含易用性/UX 维度）。

## 定位

本项目是"架构方向正确、有一个差异化亮点、但工程深度差一个数量级"的最小内核。

- ✅ 架构分层（core 零 IO + 事件流 + SSE 三端复用）与二者设计哲学同构
- ✅ 艾宾浩斯记忆是真正的差异化长板（opencode 无内建长期记忆，Claude Code 仅 CLAUDE.md 静态记忆）
- ❌ 差距不在想法，而在工具语义、权限模型、上下文经济三大硬工程

## 差距清单（按优先级）

### P0 — 决定能否"日常使用"

| 差距 | 现状 | 目标 | 对标 |
|------|------|------|------|
| 文件编辑工具（patch 语义） | 无，模型用 `cat > file` 写文件，无审查无回滚 | read_file / edit_file（diff patch）/ write_file 工具，变更可预览 | 二者均有 diff-based edit |
| 快照/撤销 | 无 | 文件级 snapshot/revert（git stash 或自管快照） | opencode snapshot/revert |
| 权限规则引擎 | 正则匹配危险命令（可被 `find -delete`、变量拼接绕过） | allow/ask/deny × 工具 × 模式 的规则引擎 + 路径白名单 | 二者权限系统 |

### P1 — 决定成本与规模

| 差距 | 现状 | 目标 |
|------|------|------|
| Prompt caching | 每轮全量重发 messages | 利用供应商 prompt caching，token 成本降一个量级 |
| Token 级上下文管理 | 字符数（2 万）触发压缩 | tokenizer 精确计量 + 分级压缩策略 |
| 子代理（subagent） | 无 | Task 式子代理，上下文隔离 + 并行执行 |
| 记忆系统规模化验证 | 几条记忆手工验证 | 几千条规模下检索质量/抽取成本基准测试 |

### P2 — 生态与完备性

| 差距 | 现状 | 目标 |
|------|------|------|
| Skill 系统 | 无（已调研，SKILL.md 事实标准） | `packages/core/agent/skills/` 内置 + `~/.agent/skills/` 用户目录，load_skill 按需注入 |
| MCP 协议 | 无 | MCP client，接入外部工具生态 |
| Hooks / 插件 | 无 | 事件钩子（pre/post tool、turn 边界） |
| 测试体系 | 仅冒烟脚本 | pytest 单测（core 纯逻辑可测）+ CI |
| 错误恢复 | 异常即崩溃/静默 | 重试、中断取消、API 错误分类处理 |
| 多用户/并发安全 | 单用户假设（内存 session_state、SQLite 无锁） | 连接锁、状态持久化（若需多人） |

## 阶段规划

- **M5（当前）**：Tauri 2 桌面端 + PyInstaller sidecar
- **M6（P0）**：文件编辑工具 patch 语义 + 快照撤销 + 权限规则引擎 → 跨过"可日常使用"门槛
- **M7（P1）**：prompt caching + token 管理 + 子代理
- **M8（P2）**：skill 系统 + MCP + 测试体系

详细对比记录见本文件 git 历史（首版含逐维度对比表）。
