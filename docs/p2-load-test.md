# P2 模拟源压测

命令：

```bash
python scripts/load_test.py
python -m pytest -q tests/test_load.py
```

`scripts/load_test.py` 用进程内的 `mock` 源，在 1 秒内送入 1000 条互不合并的点赞。事件先进入治理队列，再进入 P1 管道，直到写进 WebSocket 总线。不连接任何平台。

背压策略是 **drop oldest**：队列满时丢掉最旧的一条，接纳新事件，并增加 `dropped_oldest` 与 `alert_count`。策略之外的丢失（`dropped_silent` 或管道 `dropped`）算失败。队列容量默认 4000，这一次 1000 条没有触发丢弃。

本次在当前环境测到：

| 项目 | 结果 |
| --- | --- |
| 条数 / 窗口 | 1000 / 1.0 秒 |
| 实际耗时 | 1.0 秒 |
| 送入速率 | 1000.5 条/秒 |
| 入队到总线 p50 / p95 / p99 | 0.36 ms / 0.93 ms / 1.24 ms |
| 管道内部 p50 / p95 / p99 | 0.32 ms / 0.86 ms / 1.16 ms |
| tracemalloc 峰值 | 1,557,327 字节（约 1.5 MB） |
| 发布 | 1000 |
| drop oldest | 0 |
| 静默丢弃 | 0 |
| 告警 | 0（没有丢弃，所以不告警） |

换机器这些数会变。测试断言账是平的：`offered = duplicates + enqueued`，并且 `enqueued = delivered + pending + dropped_oldest`。一旦 `dropped_oldest` 大于 0，就必须有背压告警。
