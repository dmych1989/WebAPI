# WebAPI 自动获取凭证使用指南

## 📋 概述

基于Chat2API-main项目的自动提取功能，为WebAPI提供了强大的自动获取凭证能力。支持多种Provider的自动Token提取，包括网络请求拦截、Cookie监控、LocalStorage提取等多种策略。

## 🚀 功能特性

### 核心功能
- **多Provider支持**: 支持Kimi、DeepSeek、GLM、Qwen、MiniMax、元宝、豆包、MiMo等8个主流Provider
- **多种提取策略**: 网络请求拦截、Cookie监控、LocalStorage提取、HTML内容解析
- **智能验证**: 自动验证提取的Token有效性
- **批量操作**: 支持批量自动提取多个Provider的凭证
- **错误处理**: 完善的错误处理和重试机制

### 技术特点
- **网络请求拦截**: 实时监控网络请求，自动提取Authorization头中的Token
- **Cookie监控**: 监控Cookie变化，自动提取登录相关的Cookie
- **LocalStorage提取**: 从LocalStorage中提取存储的Token
- **智能验证**: 使用Provider的API端点验证Token有效性
- **自动保存**: 提取成功后自动保存到config.yaml

## 🎯 支持的Provider

| Provider | 登录URL | 认证方式 | 提取策略 | 验证方式 |
|----------|---------|----------|----------|----------|
| **Kimi** | https://www.kimi.com/ | Token | 网络请求拦截 + Cookie + LocalStorage | Bearer Token |
| **DeepSeek** | https://chat.deepseek.com/ | Token | LocalStorage + 网络请求拦截 | Bearer Token |
| **GLM** | https://chatglm.cn | Token | Cookie + LocalStorage | Bearer Token |
| **Qwen** | https://www.qianwen.com | Token | Cookie + LocalStorage | Bearer Token |
| **MiniMax** | https://agent.minimaxi.com | Token | LocalStorage | Bearer Token |
| **元宝** | https://yuanbao.tencent.com/chat/ | Cookie | Cookie + 所有Cookie | Cookie |
| **豆包** | https://www.doubao.com/ | Cookie | Cookie + 所有Cookie | Cookie |
| **MiMo** | https://aistudio.xiaomimimo.com/ | Cookie | Cookie + LocalStorage | Cookie |
| **Coze** | https://coze.cn | PAT | 手动输入 | Bearer Token |

## 📖 使用方法

### 方法1: 命令行使用

#### 单个Provider提取
```bash
# 基本用法
python -m src.login.auto_extract_manager.py kimi

# 指定账户名称
python -m src.login.auto_extract_manager.py kimi my-account

# 无头模式（不显示浏览器）
python -m src.login.auto_extract_manager.py kimi --headless

# 完整示例
python -m src.login.auto_extract_manager.py deepseek my-account --headless
```

#### 批量提取
```bash
# 批量提取所有支持的Provider
python -m src.login.auto_extract_manager.py batch

# 批量提取（无头模式）
python -m src.login.auto_extract_manager.py batch --headless
```

### 方法2: Python脚本使用

```python
import asyncio
from src.login.auto_extract_manager import AutoExtractManager

async def extract_single_provider():
    manager = AutoExtractManager()
    
    # 提取单个Provider
    credentials = await manager.auto_extract_credentials("kimi")
    print(f"提取到的凭证: {credentials}")
    
    # 提取并保存
    success = await manager.auto_extract_and_save("kimi", "my-account")
    print(f"提取并保存: {success}")

async def batch_extract():
    manager = AutoExtractManager()
    
    # 批量提取
    results = await manager.batch_auto_extract(["kimi", "deepseek", "glm"])
    print(f"批量提取结果: {results}")

# 运行
asyncio.run(extract_single_provider())
# asyncio.run(batch_extract())
```

### 方法3: WebAPI集成使用

```python
from src.login.enhanced_token_extractor import EnhancedTokenExtractor

async def extract_with_custom_config():
    # 创建提取器
    extractor = EnhancedTokenExtractor("kimi", headless=True)
    
    # 运行提取
    credentials = await extractor.run()
    
    if credentials:
        print(f"成功提取: {credentials}")
        # 保存到配置
        await save_credentials_to_config("kimi", credentials)
    else:
        print("提取失败")

async def save_credentials_to_config(provider, credentials):
    from src.core.config import get_config, save_config, AccountConfig
    
    config = get_config()
    
    if provider not in config.providers:
        from src.core.config import ProviderConfig
        config.providers[provider] = ProviderConfig()
    
    # 创建新账户
    new_account = AccountConfig(
        name="auto-extracted",
        enabled=True,
        **credentials
    )
    
    config.providers[provider].accounts.append(new_account)
    save_config(config)
```

## 🔧 配置说明

### 自动提取配置文件

所有Provider的提取配置都定义在 `src/login/auto_extract_configs.py` 中：

```python
# 配置示例
"kimi": TokenExtractionConfig(
    name="Kimi (月之暗面)",
    login_url="https://www.kimi.com/",
    auth_type="token",
    token_sources=[
        TokenSource(
            type="networkHeader",
            key="token",
            url_pattern="*://*.kimi.com/*",
            extract_pattern="^Bearer\\s+(.+)$"
        ),
        TokenSource(
            type="cookie",
            key="kimi-auth"
        ),
        TokenSource(
            type="localStorage",
            key="access_token"
        ),
    ],
    target_domains=[".kimi.com", "kimi.com"],
    validate_url="https://kimi.com/api",
    validate_method="bearer",
    config_key="token"
)
```

### 配置参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | str | Provider显示名称 |
| `login_url` | str | 登录页面URL |
| `auth_type` | str | 认证类型（token/cookie/pat） |
| `token_sources` | List[TokenSource] | Token提取源配置 |
| `target_domains` | List[str] | 目标域名列表 |
| `success_url_patterns` | List[str] | 登录成功URL模式 |
| `validate_url` | str | 验证Token的API端点 |
| `validate_method` | str | 验证方法（bearer/cookie） |
| `config_key` | str | 配置文件中的键名 |

### TokenSource类型说明

| 类型 | 说明 | 用途 |
|------|------|------|
| `networkHeader` | 网络请求头拦截 | 从Authorization头提取Bearer Token |
| `cookie` | Cookie监控 | 从Cookie中提取登录凭证 |
| `localStorage` | LocalStorage提取 | 从LocalStorage中提取存储的Token |
| `html` | HTML内容解析 | 从HTML页面中提取Token |
| `all_cookies` | 所有Cookie | 提取所有Cookie作为凭证 |

## 🎨 界面体验

### 提取过程
```
============================================================
  开始自动提取 kimi 凭证...
============================================================
  [*] 打开登录页面: https://www.kimi.com/
  [*] 请在浏览器窗口中完成登录...
  [+] 发现Token (token): eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  [+] 发现Token (access_token): eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  [+] 检测到登录成功，开始提取Token...
  [+] 发现Token (refresh_token): eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  [+] 发现Token (kimi-auth): eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  [*] 进行最终Token提取...
  [✓] Token (token) 验证成功
  [✓] Token (access_token) 验证成功
  [✓] Token (refresh_token) 验证成功
  [✓] Token (kimi-auth) 验证成功

  [✓] 成功提取到凭证:
    token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    access_token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    refresh_token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    kimi-auth: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

  [✓] 凭证已保存到配置文件
  账户: kimi/auto-extracted
  请重启WebAPI服务以加载新配置
============================================================
  自动提取完成!
============================================================
```

### 错误处理
```
============================================================
  开始自动提取 kimi 凭证...
============================================================
  [*] 打开登录页面: https://www.kimi.com/
  [*] 请在浏览器窗口中完成登录...
  [!] 5分钟内未检测到登录成功，提取超时
  [*] 进行最终Token提取...
  [✗] Token (token) 验证失败: Token无效
  [✗] Token (access_token) 验证失败: Token无效

  [✗] 未能提取到有效凭证

  [✗] 提取失败: 提取超时
============================================================
  自动提取失败!
============================================================
```

## 🚨 注意事项

### 1. 浏览器要求
- **推荐使用**: Chrome、Chromium、Edge
- **版本要求**: 88+
- **网络要求**: 需要稳定的网络连接

### 2. 登录要求
- **账号要求**: 需要有效的账号和密码
- **登录方式**: 手动在浏览器中完成登录
- **时间限制**: 建议在5分钟内完成登录

### 3. 安全考虑
- **Token安全**: 提取的Token会自动保存到配置文件
- **敏感信息**: 配置文件中的Token会被加密存储
- **权限要求**: 需要文件系统写入权限

### 4. 性能优化
- **无头模式**: 使用`--headless`参数可以提高性能
- **批量操作**: 批量提取可以节省时间
- **缓存机制**: 浏览器状态会被缓存以提高下次速度

## 🔍 故障排除

### 常见问题

#### 1. 提取超时
**问题**: 提取过程超时
**解决**:
- 检查网络连接
- 确保在5分钟内完成登录
- 使用无头模式减少资源占用

#### 2. Token验证失败
**问题**: 提取的Token无法通过验证
**解决**:
- 确保登录成功
- 检查Token格式是否正确
- 尝试重新提取

#### 3. 浏览器启动失败
**问题**: 浏览器无法启动
**解决**:
- 安装最新版本的Chrome/Chromium
- 检查系统权限
- 使用无头模式

#### 4. 配置保存失败
**问题**: 凭证无法保存到配置文件
**解决**:
- 检查文件权限
- 确保config.yaml存在
- 检查磁盘空间

### 调试方法

#### 启用详细日志
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 或者在命令行中添加调试参数
python -m src.login.auto_extract_manager.py kimi --headless --debug
```

#### 手动验证Token
```python
from src.login.credential_manager import credential_manager

# 验证提取的Token
result = await credential_manager.validate_account_credentials("kimi", account_config)
print(f"验证结果: {result.valid}, 错误: {result.error}")
```

## 🎯 最佳实践

### 1. 使用建议
- **首次使用**: 建议先使用单个Provider测试
- **批量操作**: 确认单个Provider正常后再使用批量提取
- **无头模式**: 生产环境建议使用无头模式
- **定期更新**: 定期更新Provider配置以适应网站变化

### 2. 安全建议
- **权限控制**: 限制配置文件的访问权限
- **定期备份**: 定期备份配置文件
- **Token管理**: 定期检查和更新过期的Token

### 3. 性能建议
- **并发限制**: 避免同时运行多个提取任务
- **资源监控**: 监控系统资源使用情况
- **缓存利用**: 利用浏览器状态缓存提高效率

## 📞 技术支持

如果遇到问题，请：

1. **查看日志**: 检查详细的错误日志
2. **检查配置**: 验证Provider配置是否正确
3. **测试网络**: 确保网络连接正常
4. **更新版本**: 确保使用最新版本

---

**文档版本**: v1.0  
**更新时间**: 2026-06-03  
**兼容性**: WebAPI v1.0+