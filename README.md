# openClaude

**用任意 OpenAI 兼容模型驱动 Claude Code**

Claude Code 是 Anthropic 的终端 AI 编程工具，但它硬编码绑定了 Anthropic API。本项目通过 API 代理层，让你用 Kimi 2.5、GLM5、Qwen3 等国产模型（或任何 OpenAI 兼容的 LLM HTTP Server）来运行 Claude Code。

## 架构

`
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   Claude Code   │────>│  openClaude Proxy     │────>│  你的 LLM 服务   │
│   (原版二进制)    │     │  (Anthropic→OpenAI    │     │  Kimi / GLM /   │
│                 │<────│   协议转换)            │<────│  Qwen / vLLM    │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
`

## 核心思路

1. Claude Code 客户端发送 **Anthropic Messages API** 格式的请求
2. openClaude Proxy 拦截请求，**转换为 OpenAI Chat Completions API** 格式
3. 转发给你的 LLM 服务（本地或云端），拿到响应
4. 将 OpenAI 格式的响应 **转换回 Anthropic 格式** 返回给 Claude Code

## 状态

🚧 **开发中** — 见下方 PLAN

---

## License

MIT
