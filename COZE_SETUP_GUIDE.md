# Coze (扣子) 渠道无法打开网页登录解决方案

## 问题分析

用户报告 "Coze 扣子渠道 无法打开网页登录"，这是正常的，因为 Coze 使用的是 Personal Access Token (PAT) 认证方式，而不是通过浏览器自动登录。

## Coze 认证方式

Coze 使用 Personal Access Token (PAT) 认证，类似于 GitHub 的 PAT：

- **认证类型**: `manual_pat`
- **Token 类型**: Personal Access Token (PAT)
- **获取方式**: 手动从 Coze 官网获取
- **无需浏览器登录**: 直接输入 Token 即可

## 解决方案

### 方法1: 使用设置助手 (推荐)

```bash
# 运行 Coze PAT 设置助手
python setup_coze_pat.py
```

该脚本会：
1. 显示获取 PAT 的详细步骤
2. 验证 Token 有效性
3. 自动保存到 config.yaml

### 方法2: 手动配置

#### 1. 获取 PAT

1. 访问 https://www.coze.cn/home/
2. 登录你的扣子账号
3. 点击左下角头像 → 「个人设置」
4. 点击「访问令牌 (PAT)」
5. 点击「新建令牌」
6. 设置名称（如：WebAPI）和过期时间
7. 点击「创建」
8. 复制生成的 Token（⚠️ 只显示一次！）

#### 2. 配置 config.yaml

```yaml
coze:
  enabled: true
  accounts:
  - name: account-1
    token: your_personal_access_token_here
    models:
    - coze-chat
    max_concurrent: 5
    health_check_interval: 60
    enabled: true
```

### 方法3: 使用内置登录功能

```bash
# 使用 WebAPI 内置登录功能
python -m src.login coze
```

这会提示你手动输入 PAT。

## 权限要求

创建 PAT 时需要以下权限：
- **Bot 调用 (chat)**: 必需权限，用于对话

## 验证配置

运行测试脚本验证配置：

```bash
python test_coze_config.py
```

## 常见问题

### Q: 为什么 Coze 不支持自动登录？
A: Coze 的官方 API 设计就是使用 PAT 认证，类似于 GitHub 的 API 认证方式，不需要浏览器登录。

### Q: PAT 过期了怎么办？
A: 需要重新创建 PAT 并更新 config.yaml 中的 token。

### Q: 如何查看我的 Bot 列表？
A: 运行 `python test_coze_config.py` 会自动获取并显示可用的 Bot 列表。

### Q: Token 无效怎么办？
A: 检查：
1. Token 是否正确复制
2. Token 是否已过期
3. 是否有 Bot 调用权限
4. 网络连接是否正常

## 完整工作流程

1. **获取 PAT**
   ```bash
   python setup_coze_pat.py
   ```

2. **验证配置**
   ```bash
   python test_coze_config.py
   ```

3. **重启服务**
   ```bash
   # 重启 WebAPI 服务
   ```

4. **测试连接**
   - 使用 WebAPI 接口测试 Coze 连接
   - 检查日志确认正常工作

## 技术细节

### Coze Provider 特点

- **API 版本**: v3
- **Base URL**: https://api.coze.cn (国内) / https://api.coze.com (国际)
- **认证方式**: Bearer Token
- **流式支持**: SSE
- **工具调用**: 支持 Coze Plugin

### 配置参数

| 参数 | 说明 | 必需 |
|------|------|------|
| token | Personal Access Token | 是 |
| models | 模型列表 (Bot 名称) | 是 |
| max_concurrent | 最大并发数 | 否 |
| health_check_interval | 健康检查间隔 | 否 |

## 总结

Coze 渠道无法打开网页登录是正常现象，因为它使用 PAT 认证方式。用户只需要：

1. 获取 PAT
2. 配置到 config.yaml
3. 验证配置

即可正常使用 Coze 服务。