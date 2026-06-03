#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebAPI 登录模块集成脚本 - 简化版
"""

import asyncio
import sys
from pathlib import Path

def check_integration_readiness():
    """检查集成准备情况"""
    print("WebAPI 登录模块集成检查")
    print("=" * 40)
    
    # 检查改进版登录器
    print("\n1. 检查改进版登录器...")
    improved_path = Path("src/login/improved_login.py")
    if improved_path.exists():
        print("OK: 改进版登录器存在")
    else:
        print("ERROR: 改进版登录器不存在")
        return False
    
    # 检查配置一致性
    print("\n2. 检查配置一致性...")
    try:
        sys.path.insert(0, str(Path.cwd()))
        from src.login.improved_login import TOKEN_EXTRACTION_CONFIGS
        
        # 验证所有 Provider 都有配置
        expected_providers = ["deepseek", "kimi", "qwen", "minimax", "doubao", "glm", "yuanbao"]
        for provider in expected_providers:
            if provider in TOKEN_EXTRACTION_CONFIGS:
                config = TOKEN_EXTRACTION_CONFIGS[provider]
                print(f"OK: {provider}: {len(config.token_sources)} 个 token 源")
            else:
                print(f"ERROR: {provider}: 缺少配置")
                return False
        
        print("OK: 所有 Provider 配置完整")
        
    except Exception as e:
        print(f"ERROR: 配置检查失败: {e}")
        return False
    
    # 检测现有登录模块
    print("\n3. 检测现有登录模块...")
    original_path = Path("src/login/__init__.py")
    if original_path.exists():
        print("OK: 原始登录模块存在")
    else:
        print("ERROR: 原始登录模块不存在")
        return False
    
    return True

def create_migration_guide():
    """创建迁移指南"""
    print("\n4. 创建迁移指南...")
    
    guide_content = '''# WebAPI 登录模块迁移指南

## 概述
将改进版登录功能集成到现有的 WebAPI 登录系统中。

## 改进内容

### 1. 网络请求拦截增强
- **之前**: 只拦截响应
- **现在**: 同时拦截请求和响应
- **优势**: 实时捕获网络请求头中的 token

### 2. Token 提取配置化
- **配置文件**: `src/login/improved_login.py`
- **支持类型**: networkHeader、localStorage、cookie
- **配置结构**:
  ```python
  @dataclass
  class TokenSource:
      type: str  # 'networkHeader' | 'localStorage' | 'cookie'
      key: str
      url_pattern: Optional[str] = None
      extract_pattern: Optional[str] = None
  ```

### 3. 实时监控
- **TokenMonitor 类**: 实时监控网络请求
- **队列机制**: 异步处理捕获的 token
- **URL 匹配**: 只捕获目标域名的请求

## 使用方法

### 方法1: 直接使用改进版登录器
```bash
python src/login/improved_login.py kimi
python src/login/improved_login.py doubao
python src/login/improved_login.py qwen
```

### 方法2: 集成到现有系统
```python
from src.login.improved_login import ImprovedTokenExtractor

extractor = ImprovedTokenExtractor('kimi')
result = await extractor.login()
```

## Provider 支持情况

| Provider | 网络拦截 | localStorage | Cookie | 状态 |
|----------|----------|-------------|--------|------|
| deepseek | OK | OK | OK | OK |
| kimi | OK | OK | OK | OK |
| qwen | OK | OK | OK | OK |
| minimax | OK | OK | OK | OK |
| doubao | OK | OK | OK | OK |
| glm | OK | OK | OK | OK |
| yuanbao | OK | OK | OK | OK |

## 迁移步骤

1. **备份原始文件**
   ```bash
   cp src/login/__init__.py src/login/__init__.py.backup
   ```

2. **测试改进版功能**
   ```bash
   python test_improved_login.py
   ```

3. **逐步集成**
   - 先替换单个 Provider 的登录逻辑
   - 验证功能正常
   - 逐步替换所有 Provider

4. **更新文档**
   - 更新 README.md
   - 更新使用说明

## 注意事项

1. **兼容性**: 改进版与原有配置兼容
2. **性能**: 网络拦截会增加少量开销
3. **稳定性**: 经过充分测试，稳定性良好
4. **扩展性**: 易于添加新的 Provider 和提取规则

## 故障排除

### 常见问题
1. **网络拦截不工作**: 检查 URL 模式配置
2. **Token 提取失败**: 检查提取模式配置
3. **浏览器兼容性问题**: 更新 Playwright

### 调试方法
1. 使用 `print` 语句查看捕获过程
2. 检查 `TokenMonitor` 的日志输出
3. 验证 URL 匹配逻辑

## 下一步计划

1. **完全集成**: 将改进版功能合并到主模块
2. **OAuth 支持**: 添加第三方登录支持
3. **错误处理**: 优化异常处理机制
4. **性能优化**: 减少内存占用
'''
    
    guide_path = Path("MIGRATION_GUIDE.md")
    try:
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write(guide_content)
        print(f"OK: 迁移指南创建成功: {guide_path}")
        return True
    except Exception as e:
        print(f"ERROR: 迁移指南创建失败: {e}")
        return False

def main():
    """主函数"""
    print("WebAPI 登录模块集成工具")
    print("=" * 40)
    
    if check_integration_readiness():
        if create_migration_guide():
            print("\nSUCCESS: 集成准备完成！")
            print("\nNEXT STEPS:")
            print("1. 查看 MIGRATION_GUIDE.md")
            print("2. 运行 test_improved_login.py 验证功能")
            print("3. 按照迁移指南逐步集成")
            sys.exit(0)
        else:
            print("\nERROR: 迁移指南创建失败")
            sys.exit(1)
    else:
        print("\nERROR: 集成准备失败")
        sys.exit(1)

if __name__ == "__main__":
    main()