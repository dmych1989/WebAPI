# WebAPI Phase 3 E2E 死锁修复

**时间**: 2026-06-01  
**目标**: 修复 `/stats` 端点挂起问题，完成 Phase 3 高级功能 E2E 验证

## 根因

`src/core/stats.py` 中 `StatsTracker.get_snapshot()` 调用 `self.get_current_qps()`，两者都尝试获取同一个 `threading.Lock()`。Python `Lock` 不可重入，导致死锁——`/stats` 端点无限挂起（连接建立后永不响应），其他端点（`/health`、`/stats2` 等）不受影响。

## 修复

### 1. `Lock` → `RLock`（核心修复）
- 文件: `src/core/stats.py`
- 将 `from threading import Lock` 改为 `from threading import RLock`
- `Lock()` → `RLock()`
- `RLock` 允许同一线程多次获取，解决 `get_snapshot()` 内部调用 `get_current_qps()` 的死锁

### 2. 测试修复
- 文件: `tests/test_phase3.py`
- 测试开始前调用 `POST /admin/stats/reset` 重置统计（避免前次残留）
- 修正断言: `total_requests == 1`（错误也算入总数），而非之前的 `== 0`

## E2E 结果

全部 12 个测试通过：
1. `GET /health` → 200
2. `POST /admin/stats/reset` → 200
3. `GET /stats` → `total_requests=0`
4. `GET /admin/stats` → 200
5. `GET /admin/providers` → registered=['deepseek','kimi','qwen']
6. `POST /v1/chat/completions` → 503 (无账号)
7. `GET /stats` → `total_requests=1, error_requests=1` ✅
8. `GET /admin/config` → API key disabled
9. `GET /v1/models` → 200
10. `POST /admin/config/reload` → 200
11. `GET /admin/pool` → 200
12. `POST /admin/stats/reset` → cleared

## 教训

Python 多线程中，永远用 `RLock()` 替代 `Lock()` 除非明确需要不可重入行为。任何调用链中可能递归获取锁的情况都需要可重入锁。