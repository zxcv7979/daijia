# 浸泡报告

本环境没有 OBS，也没有独立 GPU。下面是短跑数字。完整 8 小时、OBS 重连和显存曲线标成 **待实机验收**。

## 这次短跑

命令：

```bash
python3 scripts/soak_hook.py --duration 30 --interval 0.5
```

工作负载：模拟弹幕、预设角色回退（不上传照片）、虚拟打印队列轮换、断线罐头帧计算、到期照片预演。官方桩保持降级，不计入不健康告警。

本次短跑 JSON：

- 时长 30.256 秒，60 个采样。
- RSS 增量 668 KB，文件句柄增量 0。
- `gpu_seen` 为 false（没有 nvidia-smi）。
- `breaches` 为空，`ok` 为 true。
- 罐头帧 60 步。保留期预演：7 天，候选 0，未删除。
- `full_8h` 为 false。

预算：内存增量超过 256MB，或文件句柄增量超过 40，记 `alert` 意义上的 breach，退出码 1。

## 实机 8 小时

```bash
bash scripts/soak_8h.sh 28800
```

同时用 OBS 浏览器源打开 `http://127.0.0.1:8787/overlay/`。中途断一次网卡或关掉服务再打开，确认 30 秒内的弹幕和打印进度能补上，画面不黑。浏览器控制台可调用场景的 `recoverContext()` 模拟 WebGL 上下文丢失。

记录：

| 项 | 短跑 | 8 小时实机 |
| --- | --- | --- |
| 时长 | 30.256 秒 | 待实机验收 |
| RSS 增量 | 668 KB | 待实机验收 |
| FD 增量 | 0 | 待实机验收 |
| GPU | false | 待实机验收 |
| 黑屏 / 卡死 | 无头脚本不覆盖画面 | 待实机验收 |

## 模板

若只准备表格、还没跑：

```json
{"duration_sec": null, "samples": 0, "growth": {"rss_kb": null, "fds": null}, "gpu_seen": false, "breaches": [], "full_8h": false, "note": "待实机验收"}
```
