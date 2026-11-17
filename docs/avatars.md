# 角色资产

预设角色是这个仓库自己生成的小 GLB，不下载别人的模型。照片任务默认在本机完成。没有 NVIDIA GPU 时，它做的是参数化头加照片贴图，不会假装跑过 InstantMesh、TripoSR 或 Hunyuan3D。照片不会发到云端接口。

## 预设

三个角色：圆圆、青青、禾禾。文件在 `data/avatars/presets/`。授权说明写在 GLB 里：原创参数化网格，可以随仓库使用和修改。来源脚本是 `scripts/build_preset_avatars.py`。

```bash
python scripts/build_preset_avatars.py
```

每个文件带齐 ARKit 的 52 个形变名。情绪引擎把 joy、awe 等映射到其中一部分，其余权重是 0。待机还有呼吸、眨眼和头的轻微摆动。弹幕会触发一个口型钩子：按字数把 `jawOpen` 抬一下，再自己落回去。这不是真正的语音口型。

管理页「角色」里点名字即可切换。新模型加载完成前，画面留着上一个角色，加载好以后交叉淡入，不会先黑屏。

体积大约 54KB。在这台机器上用 Python 读出 JSON 块大约 0.2 毫秒，远低于 2 秒。页面会预取当前角色并记下 `loadMs`。

可选压缩（Draco + KTX2），没有编码器也可以不跑：

```bash
python scripts/compress_avatars.py
```

它调用 `npx @gltf-transform/cli`。失败时未压缩的 GLB 仍然能加载。特效页默认读未压缩文件，这样新克隆仓库不依赖额外解码器。

## 照片任务

管理页勾选「已获得本人同意」，选 1 到 5 张正脸，再提交。质检不过会用中文写原因，例如太糊、不是正脸、多张脸、遮挡、太暗或太亮。换图再传就是重试。

勾选「未成年人或敏感主体」会直接拒绝。

通过质检后任务进入「待复核」。通过复核才会当成可用的写实资产。重做会换一个种子再出一版，状态回到待复核。删除会同时清掉加密原图和生成的 GLB。

原图用和 P2 一样的密钥加密后放在 SQLite，保留天数看 `avatar.photo_retention_days`，默认 7 天。接口不回传原图字节。

同一个 `avatar_id` 可以连着预设角色和后来的写实成品。再传一次照片仍然用这个 ID。

## 没有 GPU 时

`src/avatar/gpu.py` 只看本机有没有 `nvidia-smi`。没有就：

- `generator` 为 `parametric-fallback`
- `reconstruction_ran` 为 false
- GLB 的 extras 写明这不是神经重建

`avatar.gpu_enabled` 和 `avatar.cloud_api` 默认都是 false，而且配置不允许把 `cloud_api` 设成 true。

## 有 GPU 时怎么跑（待实机验收）

这些步骤留给有 NVIDIA 显卡的机器。本仓库不下载模型权重，也不在云环境里执行。

1. 安装你有授权的本地重建工具，并确认 `nvidia-smi` 能列出 GPU。
2. 固定种子用配置里的 `avatar.seed`（默认 42）。重做会在上一颗种子上加 1。
3. 目标是 60 秒内写出带贴图的 GLB。这一条在没有实测之前标成待实机验收。
4. 不要把原图交给未在配置里明确关闭的第三方接口。当前 `cloud_api: false`，代码里没有照片上传客户端。

即使以后接上本地 GPU 命令，人工复核仍然要先预览再通过。
