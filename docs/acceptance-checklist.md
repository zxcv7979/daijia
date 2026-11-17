# 量化验收

这是整场演示的正式标准。能在测试或脚本里卡住的，以测试为准。这台机器量不到的，只写步骤，标成 **待实机验收**。没有把没跑过的项目写成通过。

## 总表

| 条款 | 标准 | 怎么验 | 这次能说的 |
| --- | --- | --- | --- |
| 模拟源端到端延迟 | 同一台机器 < 300ms | 自动化。`test_event_to_ws_latency_under_100ms` 把 p99 卡在 100ms，比 300ms 更严 | 本次 30 条：管线 p50/p99 1.540/4.406 ms，HTTP 到 WS p50/p99 17.491/24.612 ms。低于 300ms |
| 10 倍事件、1080p | ≥55fps，帧时间 ≤12ms | 脚本 `python scripts/benchmark_overlay.py --seconds 12 --rate 20`。OBS 里看帧率 | **待实机验收**。无头浏览器的绘制耗时不能代替 OBS 的 55fps |
| 8 小时浸泡 | 内存增长 < 20%，WebGL 上下文丢失不崩溃 | `bash scripts/soak_8h.sh 28800`。短跑只报告比例，不判这条通过 | **待实机验收** |
| 重连 | ≤5 秒，30 秒缓冲里的事件不丢 | 自动化。`ReconnectBackoff` 上限 5 秒；`test_buffer_keeps_30s_and_replays_cursor` | 退避公式和缓冲都有测试 |
| 同屏特效 | ≤8 个，粒子 ≤20000；弹幕洪水自动降档 | 自动化。`tests/test_quality.py`、`tests/test_acceptance_bar.py` | 超 12ms 连续 8 帧会降档 |
| 聚合和连击 | 相同文本窗口 200ms；连击显示 combo | 自动化。`tests/test_normalize.py`，窗口被配置锁死 | 窗口不是 200 时配置直接拒绝 |
| 预设表情 | 切换 ≤300ms，待机自然；GLB 加载 ≤2s | 自动化：淡入常量 0.28 秒，权重计算 < 300ms，解析 < 2s。观感看画面 | 待机是否自然 **待实机验收** |
| 照片到角色 | 本地 GPU 60 秒内出 GLB；失败要有明确原因 | 无 GPU 时 `reconstruction_ran` 必须是 false，并回到预设。不把回退写成成功 | **待实机验收**（本机没有 NVIDIA GPU） |
| 打印动画 | 30–60 秒可配，能拖到任意进度，层纹和揭晓不穿模 | 时长和拖动进度有测试。穿模看画面 | 穿模 **待实机验收** |
| 进度情绪 | 25/50/75/90/100 与情绪演出一一对应 | 自动化。`test_print_duration_seek_and_cue_map` | 每个进度点的情绪和特效名必须等于配置 |
| 20 条队列 | 切台不黑屏、不泄漏 | 脚本 `python scripts/print_queue_bench.py --jobs 20` 看进程内是否跑完。黑屏看画面 | 本次进程内 20 条都完成，`rebuilds=0`，tracemalloc 增量 143137 字节、峰值 143785 字节。黑屏和浏览器泄漏 **待实机验收** |
| 人脸删除 | 接口马上能删，周期硬删，审计可查 | 自动化。`DELETE /api/avatars/{id}`，每 60 秒 `purge_expired_photos`，`GET /api/audit` | 删除和审计在测试里检查 |
| 真实源 | 默认关闭；打开要二次确认并留审计 | 自动化。`tests/test_real_source.py` | 没有确认就不会写 `real_source_enabled` |
| 本场回放 | 管理页一键回放整场，用于回看和回归 | 自动化。`POST /api/replay/session`，按钮「回放本场」 | 按入库时间重放，不连接平台 |

## 实机步骤

### 1080p、10 倍事件

1. `bash scripts/start.sh`。
2. OBS 浏览器源指向 `http://127.0.0.1:8787/overlay/`，画布 1920×1080，背景透明。
3. 管理页点「突发 200 条/秒」，或 `python scripts/benchmark_overlay.py --seconds 12 --rate 20` 只作参考。
4. 看 OBS 的帧率和特效页 HUD。要 ≥55fps，单帧绘制 ≤12ms。做不到就记实际数字，不要改记录。
5. 弹幕很多时应该降档，而不是卡住。

### 8 小时和上下文丢失

1. `bash scripts/soak_8h.sh 28800`。
2. 同时开着 OBS 源。开始和结束各记一次进程内存，增幅要 < 20%。
3. 在特效页控制台调用场景的 `recoverContext()`，或让显卡复位。画面应恢复，进程不退出。
4. 短跑 `python3 scripts/soak_hook.py --duration 30 --interval 0.5` 只会打印当时的 `rss_growth_ratio`。它不能代替 8 小时。

### 预设待机和 GLB

1. 打开 `http://127.0.0.1:8787/overlay/?preview=1&hud=1`。
2. 看呼吸、眨眼、轻微摇头是否顺，而不是抽动。
3. 管理页切换圆圆、青青、禾禾。淡入应在 300ms 内结束，文件没好时上一帧还在。
4. 浏览器里第一次出现模型应在 2 秒内。解析测试只保证读文件，不代替这一步。

### 照片、60 秒 GPU

1. 只有本机有 NVIDIA GPU 时才做。
2. 用本人同意过的样张提交。60 秒内应得到 GLB。
3. 失败要在接口的 `reasons` 里写中文原因。
4. 没有 GPU 时结果必须是参数化回退，`reconstruction_ran` 为 false。不要把它记成重建成功。

### 打印穿模和 20 条切台

1. 建一条 45 秒任务，把调试台时间轴拖到 10%、50%、90%、100%。
2. 层生长时不看见空心内壁；揭晓时模型是实体。
3. 连续建 20 条。切到下一条时不黑屏，内存不一直涨。
4. `python scripts/print_queue_bench.py --jobs 20` 只说明进程内队列能走完。

### 重连

1. 播放中关掉服务再打开，5 秒内特效页应重新连上。
2. 断开不到 30 秒时，错过的弹幕和打印进度还会补上。超过 30 秒允许出现 `buffer_gap`。
