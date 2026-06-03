# -*- coding: utf-8 -*-
"""WebAPI — 请求统计追踪

轻量级内存统计，记录 QPS / 错误率 / 各 Provider 调用量。
用于 /stats 端点和管理 Dashboard。
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import RLock


@dataclass
class ProviderStats:
    """单个 Provider 的统计"""
    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    last_request_at: float = 0.0


@dataclass
class GlobalStats:
    """全局统计"""
    total_requests: int = 0
    error_requests: int = 0
    active_connections: int = 0
    start_time: float = field(default_factory=time.time)
    providers: dict[str, ProviderStats] = field(default_factory=lambda: defaultdict(ProviderStats))


class StatsTracker:
    """线程安全的轻量统计器"""

    def __init__(self):
        self._lock = RLock()
        self._stats = GlobalStats()
        # 按分钟的请求计数（用于 QPS 近似）
        self._minute_buckets: dict[int, int] = defaultdict(int)

    def record_request(self, provider: str, model: str, success: bool, latency_ms: float):
        """记录一次请求"""
        with self._lock:
            s = self._stats
            s.total_requests += 1
            if not success:
                s.error_requests += 1

            ps = s.providers[provider]
            ps.total_requests += 1
            if success:
                ps.success_count += 1
            else:
                ps.error_count += 1

            # 移动平均延迟
            if ps.total_requests == 1:
                ps.avg_latency_ms = latency_ms
            else:
                alpha = 1 / min(ps.total_requests, 100)  # 自适应平滑
                ps.avg_latency_ms = (1 - alpha) * ps.avg_latency_ms + alpha * latency_ms

            ps.last_request_at = time.time()

            # 分钟桶
            bucket = int(time.time() / 60)
            self._minute_buckets[bucket] += 1

    def record_error(self, provider: str, model: str, error_type: str):
        """记录一次错误"""
        self.record_request(provider, model, success=False, latency_ms=0)

    def increment_active(self):
        with self._lock:
            self._stats.active_connections += 1

    def decrement_active(self):
        with self._lock:
            self._stats.active_connections = max(0, self._stats.active_connections - 1)

    @property
    def active_connections(self) -> int:
        return self._stats.active_connections

    def get_current_qps(self) -> float:
        """当前 QPS（最近 1 分钟的请求数 / 60）"""
        with self._lock:
            now = time.time()
            current_bucket = int(now / 60)
            total = 0
            for bucket, count in list(self._minute_buckets.items()):
                if now - (bucket * 60) <= 60:
                    total += count
                else:
                    del self._minute_buckets[bucket]
            return total / 60.0 if total > 0 else 0.0

    def get_snapshot(self) -> dict:
        """获取统计快照"""
        with self._lock:
            s = self._stats
            uptime = time.time() - s.start_time

            providers_data = {}
            for name, ps in s.providers.items():
                error_rate = (ps.error_count / ps.total_requests * 100) if ps.total_requests > 0 else 0
                providers_data[name] = {
                    "total": ps.total_requests,
                    "success": ps.success_count,
                    "errors": ps.error_count,
                    "error_rate": round(error_rate, 1),
                    "avg_latency_ms": round(ps.avg_latency_ms, 1),
                    "last_request": ps.last_request_at,
                }

            return {
                "uptime_seconds": round(uptime, 1),
                "total_requests": s.total_requests,
                "error_requests": s.error_requests,
                "error_rate": round(s.error_requests / s.total_requests * 100, 1) if s.total_requests > 0 else 0,
                "active_connections": s.active_connections,
                "current_qps": round(self.get_current_qps(), 2),
                "providers": providers_data,
            }

    def reset(self):
        """重置统计"""
        with self._lock:
            self._stats = GlobalStats()
            self._minute_buckets.clear()


# 全局单例
stats_tracker = StatsTracker()