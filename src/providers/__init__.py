"""AI 服务商接入层：LLM / 图片生成 / 视频生成都按 settings.json 里的配置调用。

- settings: 服务商与模型分配的读写、API Key 轮询
- llm: OpenAI 兼容 / Gemini 官方 / Anthropic 原生三种 API 格式的对话与结构化输出
- image: 图片生成（Gemini generateContent / OpenAI Images API）
- video: 视频生成（统一视频接口 / OpenAI Sora / Google Veo）
"""
