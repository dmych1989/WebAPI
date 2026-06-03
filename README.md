# WebAPI

> 网页版大模型对话 → 本地 OpenAI 兼容 API

## 简介

WebAPI 将各大 AI 厂商的**网页版对话服务**转换为本地 **OpenAI 兼容 API**，使任何支持 OpenAI API 的客户端工具（Cherry Studio、NextChat、Cline、Roo Code 等）都能免费调用这些模型。

不依赖官方 API Key，模拟用户在浏览器中的操作，将网页版对话能力暴露为标准 API。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 Provider（填入你的 Web Token）
notepad config\config.yaml

# 3. 启动服务
python -m src.main

# 4. 测试
curl http://localhost:18080/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"deepseek-v4-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello!\"}],\"stream\":true}"
```

## 支持的 Provider

| Provider          | 渠道                    | 协议                 | 认证                  | 状态     |
| ----------------- | --------------------- | ------------------ | ------------------- | ------ |
| DeepSeek          | `chat.deepseek.com`   | Server-Sent JSON   | Cookie / Token      | ✅ 已实现  |
| Kimi              | `www.kimi.com`        | gRPC-Web (Connect) | JWT / Refresh Token | ✅ 已实现  |
| 通义千问 (Qwen)       | `tongyi.aliyun.com`   | Server-Sent JSON   | SSO Ticket          | ✅ 已实现  |
| MiniMax (Minimax) | `chat.minimax.io`     | WebSocket          | Cookie              | ✅ 已实现  |
| 豆包 (Doubao)       | `www.doubao.com`      | Server-Sent JSON   | Cookie / Token      | ✅ 已实现  |
| 腾讯元宝 (Yuanbao)    | `yuanbao.tencent.com` | Server-Sent JSON   | Cookie              | ✅ 已实现  |
| Coze              | `www.coze.cn`         | —                  | —                   | 🚧 计划中 |

模型名称通过 `config/config.yaml` 中的 `model_mappings` 进行映射，调用方使用 OpenAI 风格模型名。

## API 端点

| 端点                        | 方法      | 说明                    |
| ------------------------- | ------- | --------------------- |
| `/v1/chat/completions`    | POST    | OpenAI 兼容对话（流式 + 非流式） |
| `/v1/models`              | GET     | 已注册模型列表               |
| `/health`                 | GET     | 服务健康检查                |
| `/admin/providers`        | GET     | Provider 池状态          |
| `/admin/config`           | GET/PUT | 查看/热重载配置              |
| `/admin/login/{provider}` | POST    | 触发浏览器自动登录提取 Token     |
| `/admin/reset`            | POST    | 重置账户失败计数              |

## 架构

```
用户客户端 → FastAPI (OpenAI 兼容)
              ↓
         Provider 调度器
              ↓
    ┌─────────┼─────────┐
    ↓         ↓         ↓
DeepSeek    Kimi      Qwen   ...
```

## 开发

```bash
# 运行测试
pytest tests/ -v

# 开发模式（自动重载）
uvicorn src.server.app:app --reload --port 18080
```

## License

GPL-3.0
