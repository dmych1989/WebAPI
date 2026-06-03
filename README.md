# WebAPI 项目概览

## 🎯 项目简介

WebAPI 是一个**本地部署的 OpenAI 兼容 API 网关**，将各大 AI 厂商的网页版对话服务转换为标准化的 API 接口。支持多种 Provider，让任何支持 OpenAI API 的客户端工具都能免费调用这些模型。

### 核心特性

- 🔥 **免费使用**: 无需官方 API Key，利用网页版服务
- 🚀 **本地部署**: 数据不经过第三方，保护隐私
- 🌐 **多Provider支持**: 集成 DeepSeek、Kimi、通义千问等主流AI服务
- 📊 **完整管理界面**: 专业级的管理和监控功能
- ⚡ **高性能**: 支持并发请求和智能负载均衡
- 🔒 **安全可控**: 完全本地化部署，数据不出本地

## 🖥️ 管理界面

### 界面特色

- **现代化设计**: 采用渐变色主题和毛玻璃效果
- **实时监控**: 5秒自动更新，实时显示服务状态
- **完整功能**: Provider管理、API Key管理、配置管理
- **响应式设计**: 完美适配桌面、平板、手机
- **主题切换**: 支持浅色/深色主题

### 主要功能模块

#### 📊 概览面板
```
┌─────────────────────────────────────────────────┐
│ 服务状态: ● 运行中      实时更新: 🟢              │
├─────────────────────────────────────────────────┤
│ 已配置渠道: 8      总请求数: 1,234              │
│ 平均响应: 245ms     API Key: 3                  │
│ 活跃会话: 5        运行时间: 2h 15m           │
└─────────────────────────────────────────────────┘
```

#### 🔌 Provider管理
```
┌─────────────────────────────────────────────────┐
│ DeepSeek 🐳    | 健康 | 1个账号 | 并发:0 | 失败:0 │
│ Kimi 🌙        | 健康 | 1个账号 | 并发:0 | 失败:0 │
│ 通义千问 ☁️    | 健康 | 1个账号 | 并发:0 | 失败:0 │
│ MiniMax 🌟     | 健康 | 1个账号 | 并发:0 | 失败:0 │
│ 豆包 🫘        | 异常 | 1个账号 | 并发:0 | 失败:47 │
│ 腾讯元宝 💎     | 健康 | 1个账号 | 并发:0 | 失败:0 │
│ GLM 🤖         | 健康 | 1个账号 | 并发:0 | 失败:0 │
│ Coze 🤖        | 异常 | 1个账号 | 并发:0 | 失败:76 │
└─────────────────────────────────────────────────┘
```

#### ⚙️ 设置管理
```
┌─────────────────────────────────────────────────┐
│ 服务器配置:                                     │
│ 监听地址: 127.0.0.1:18080                      │
│ 最大并发: 100          请求超时: 30秒         │
│                                              │
│ API Key管理:                                    │
│ [●] 启用认证            [➕] 新建 Key           │
│ Key数量: 3              [📤] 导出 Keys        │
└─────────────────────────────────────────────────┘
```

## 📋 支持的 Provider

### 已实现 Provider

| Provider | 渠道 | 协议 | 认证方式 | 状态 | 特点 |
|---------|------|------|----------|------|------|
| **DeepSeek** | chat.deepseek.com | Server-Sent JSON | Cookie / Token | ✅ 已实现 | 稳定，支持多种模型 |
| **Kimi** | www.kimi.com | gRPC-Web (Connect) | JWT / Refresh Token | ✅ 已实现 | 响应速度快，支持长文本 |
| **通义千问** | tongyi.aliyun.com | Server-Sent JSON | SSO Ticket | ✅ 已实现 | 阿里出品，稳定性好 |
| **MiniMax** | chat.minimax.io | WebSocket | Cookie | ✅ 已实现 | 支持多模态 |
| **豆包** | www.doubao.com | Server-Sent JSON | Cookie / Token | ✅ 已实现 | 字节跳动出品 |
| **腾讯元宝** | yuanbao.tencent.com | Server-Sent JSON | Cookie | ✅ 已实现 | 腾讯出品，集成微信生态 |
| **GLM** | chatglm.cn | Server-Sent JSON | Cookie | ✅ 已实现 | 智谱出品，中文优化 |

### 计划中 Provider

| Provider | 渠道 | 状态 | 预计时间 |
|---------|------|------|----------|
| **Coze** | www.coze.cn | 🚧 计划中 | 2026 Q2 |

## 🚀 快速开始

### 1. 环境准备
```bash
# 克隆项目
git clone https://github.com/your-repo/WebAPI.git
cd WebAPI

# 安装依赖
pip install -r requirements.txt

# 检查Python版本
python --version  # 需要 Python 3.8+
```

### 2. 配置 Provider
```yaml
# config/config.yaml
server:
  host: "127.0.0.1"
  port: 18080
  max_concurrent: 100
  timeout: 30

providers:
  deepseek:
    accounts:
      - name: "my-main-account"
        token: "${DEEPSEEK_TOKEN}"
        models: ["deepseek-v4", "deepseek-v4-flash"]
        max_concurrent: 5
  
  kimi:
    accounts:
      - name: "my-kimi-account"
        token: "${KIMI_TOKEN}"
        models: ["moonshot-v1-32k", "moonshot-v1-128k"]
        max_concurrent: 5
```

### 3. 启动服务
```bash
# 启动服务
python -m src.main

# 或使用开发模式（自动重载）
uvicorn src.server.app:app --reload --port 18080
```

### 4. 访问界面
- **管理面板**: http://localhost:18080/
- **Admin Console**: http://localhost:18080/admin

### 5. 测试 API
```bash
# 测试对话
curl http://localhost:18080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [
      {"role": "user", "content": "Hello! How are you?"}
    ],
    "stream": true
  }'

# 查看模型列表
curl http://localhost:18080/v1/models
```

## 🔧 配置详解

### 环境变量配置
```bash
# 创建 .env 文件
echo "DEEPSEEK_TOKEN=your_token_here" > .env
echo "KIMI_TOKEN=your_token_here" >> .env
echo "QWEN_COOKIE=your_cookie_here" >> .env

# 或直接在命令行设置
export DEEPSEEK_TOKEN="your_token_here"
export KIMI_TOKEN="your_token_here"
```

### Provider 配置示例

#### DeepSeek 配置
```yaml
providers:
  deepseek:
    accounts:
      - name: "production-account"
        token: "${DEEPSEEK_TOKEN}"
        models: 
          - "deepseek-v4"
          - "deepseek-v4-flash"
          - "deepseek-r1"
        max_concurrent: 10
        health_check_interval: 60
        enabled: true
```

#### Kimi 配置
```yaml
providers:
  kimi:
    accounts:
      - name: "main-account"
        token: "${KIMI_TOKEN}"
        models:
          - "moonshot-v1-32k"
          - "moonshot-v1-128k"
          - "moonshot-v1-8k"
        max_concurrent: 8
        health_check_interval: 30
        enabled: true
```

#### 通义千问配置
```yaml
providers:
  qwen:
    accounts:
      - name: "qwen-account"
        cookie: "${QWEN_COOKIE}"
        models:
          - "qwen-turbo"
          - "qwen-plus"
          - "qwen-max"
        max_concurrent: 15
        health_check_interval: 45
        enabled: true
```

## 📊 性能监控

### 实时指标
- **请求数**: 总请求数和错误数
- **响应时间**: 平均响应时间
- **并发数**: 当前活跃连接数
- **Provider状态**: 各Provider的健康状态
- **错误率**: 错误请求比例

### 监控界面
```
┌─────────────────────────────────────────────────┐
│ 实时监控                                       │
│ ┌─────────────────┐ ┌─────────────────┐      │
│ │ QPS: 15.3       │ │ 延迟: 245ms     │      │
│ │ 并发: 12        │ │ 错误率: 0.5%    │      │
│ └─────────────────┘ └─────────────────┘      │
│                                              │
│ Provider状态:                                 │
│ ● DeepSeek: 正常     ● Kimi: 正常            │
│ ● 通义千问: 正常     ● MiniMax: 正常          │
│ ● 豆包: 异常        ● 腾讯元宝: 正常          │
└─────────────────────────────────────────────────┘
```

## 🔒 安全配置

### API Key 管理
```yaml
server:
  api_key_enabled: true
  api_keys:
    - name: "cherry-studio"
      description: "Cherry Studio客户端"
      enabled: true
    - name: "nextchat"
      description: "NextChat客户端"
      enabled: true
```

### 访问控制
```yaml
server:
  host: "127.0.0.1"  # 仅本地访问
  port: 18080
  max_concurrent: 100
  timeout: 30
```

## 🚨 故障排除

### 常见问题

#### 1. Provider 账号异常
```bash
# 检查账号状态
curl http://localhost:18080/admin/providers

# 手动验证账号
curl -X POST http://localhost:18080/admin/providers/deepseek/accounts/account-1/validate
```

#### 2. API Key 认证失败
```bash
# 检查 API Key 状态
curl http://localhost:18080/admin/api-keys

# 重新生成 Key
curl -X POST http://localhost:18080/admin/api-keys/{key-id}/regenerate
```

#### 3. 服务启动失败
```bash
# 检查端口占用
netstat -ano | findstr :18080

# 检查配置文件
python -c "import yaml; yaml.safe_load(open('config/config.yaml'))"
```

### 日志查看
```bash
# 查看服务日志
tail -f logs/uvicorn.log

# 查看错误日志
tail -f logs/uvicorn_err.log
```

## 🎨 界面定制

### 主题配置
```css
/* 自定义主题颜色 */
:root {
  --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  --success: #4ade80;
  --warning: #fbbf24;
  --error: #f87171;
  --info: #60a5fa;
}
```

### 界面语言
```javascript
// 切换语言
document.documentElement.lang = "zh-CN";
```

## 📈 性能优化

### 配置优化
```yaml
server:
  max_concurrent: 200        # 增加并发数
  timeout: 15               # 减少超时时间
  load_balance:
    strategy: "round_robin"  # 负载均衡策略
    health_check_interval: 30 # 健康检查间隔
```

### Provider 优化
```yaml
providers:
  deepseek:
    accounts:
      - name: "high-performance"
        max_concurrent: 20    # 提高并发限制
        health_check_interval: 15 # 更频繁的健康检查
        models: ["deepseek-v4-flash"] # 仅使用高性能模型
```

## 🤝 贡献指南

### 开发环境设置
```bash
# 克隆项目
git clone https://github.com/your-repo/WebAPI.git
cd WebAPI

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装开发依赖
pip install -r requirements.txt
pip install pytest black flake8

# 运行测试
pytest tests/ -v

# 代码格式化
black src/
flake8 src/
```

### 添加新 Provider
1. 在 `src/provider/` 目录下创建新的 Provider 类
2. 在 `config.py` 中注册 Provider
3. 在 `admin.py` 中添加管理接口
4. 更新文档和测试

## 📄 许可证

本项目采用 GPL-3.0 许可证。详情请参阅 [LICENSE](LICENSE) 文件。

## 📞 支持

- 📧 **邮箱**: your-email@example.com
- 💬 **讨论**: [GitHub Discussions](https://github.com/your-repo/WebAPI/discussions)
- 🐛 **问题报告**: [GitHub Issues](https://github.com/your-repo/WebAPI/issues)
- 📖 **文档**: [项目文档](https://github.com/your-repo/WebAPI/wiki)

---

**WebAPI** - 让 AI 调用更简单、更自由！ 🚀