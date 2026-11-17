# 上线检查

这场演示不连接直播平台，也不连接真实打印机。开播前按下面核对。

## 配置

- [ ] `config/default.yaml` 里 `live.collection_enabled` 和 `live.real_source` 仍是 `false`，除非已经单独做过二次确认。
- [ ] `adapters.official.enabled` 仍是 `false`。
- [ ] `config/compliance.yaml` 的 `retention.retention_days` 和 `avatar.photo_retention_days` 符合这次授权期限，默认 7 天。
- [ ] `overlay.sfx` 空路径保持静音；要出声再放文件。
- [ ] 打印时长、层纹、环绕和揭晓灯按这场的节奏调过。

## 合规确认

- [ ] 真实采集开关保持关闭，或打开时审计里能看到 `collection_enabled` / `real_source_enabled`。
- [ ] 管理页能打开审计列表，关键操作有记录：映射重载、打印触发、角色通过、角色删除、照片访问。
- [ ] 跑过一次 `POST /api/ops/retention`，`dry_run: true`，确认候选数量符合预期，再决定是否真的删。

## 隐私和授权，给主播念的话

照片只用于这场虚拟形象，不公开原图。观众或嘉宾要出镜生成角色时，先说明：

- 需要本人同意。未成年人不出镜，敏感主体不出镜。
- 原图加密保存，默认 7 天后删除，也可以马上在管理页删掉照片和生成结果。
- 画面上的打印机是动画，不会真的打印东西。
- 不同意就用预设角色：圆圆、青青、禾禾。

## 应急

中途卡住或被投诉时：

- 静音特效：管理页勾「静音特效」，或 `POST /api/ops/mode`，`{"mute": true}`。
- 只留预设：勾「仅预设角色」，或 `{"preset_only": true}`。照片角色不会再被换上去。
- 断网：特效页用本地罐头动画继续播，不把画面清黑。30 秒内恢复时，WebSocket 用 `since_seq` 把错过的消息补上。
- 生成超时或失败：自动回到预设圆圆，不要空等 GPU。
- 上下文丢失：特效页会重建 WebGL 上下文并保留当前进度。也可以在管理端看到 `alert_context_loss`。
- 投诉照片：立刻删除该角色。删除会清照片和生成的 GLB，并写 `avatar_deleted` 和 `face_access`。

回退就是上面两个开关加上停掉回放：`POST /api/replay/stop`。不需要改代码。

## 浸泡

短检查：

```bash
python3 scripts/soak_hook.py --duration 30 --interval 0.5
```

接近开播前可以跑 5–10 分钟：

```bash
bash scripts/soak_8h.sh 600
```

8 小时实机：

```bash
bash scripts/soak_8h.sh 28800
```

完整 8 小时数字若还没在 OBS 里跑过，按 `docs/p6-soak-report.md` 标成待实机验收。
