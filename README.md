# ComfyUI Flyway 插件

Flyway 的 ComfyUI 工具集：字幕翻译、TTS 合成、音频保存、歌词对齐、批量图片保存、Florence2 视频标签等，共 12 个节点，全部在节点菜单的 `flyway` 分类下。

**每个节点的介绍、参数和注意事项见 [NODES.md](NODES.md)。**

## 节点一览

| 节点 | 类名 |
|------|------|
| 🐦‍🔥 Image List ↔ Directory（目前为占位实现） | `ImageListDirectory` |
| 🐦‍🔥 逻辑过滤 | `ImageBatchLogicFilter` |
| 🐦‍🔥 多行文本轮询 | `MultiLineTextInput` |
| 🐦‍🔥 Fish S2 Token 估算 | `FishS2TokenEstimator` |
| 🐦‍🔥 Audio Save | `FlywayAudioSave` |
| 🐦‍🔥 Subtitle & Translate | `FlywaySubtitleTranslate` |
| 🐦‍🔥 Ollama Translate | `FlywayOllamaTranslate` |
| 🐦‍🔥 TTS Merge（与当前 FishAudioS2 不兼容，详见 NODES.md） | `FlywayTTSMerge` |
| 🐦‍🔥 Batch Image Save To Path | `BatchImageSaveToPath` |
| 🐦‍🔥 Select Every Nth Image | `SelectEveryNthImage` |
| 🐦‍🔥 Florence2 Label Dedup | `Florence2LabelDedup` |
| 🐦‍🔥 Lyric Align -> LRC/SRT/ASS | `LyricAlignLRC` |

## 安装

1. 将此文件夹放到 ComfyUI 的 `custom_nodes` 目录下
2. `pip install -r requirements.txt`（可选依赖见该文件内注释）
3. 重启 ComfyUI

## 示例工作流

`example_workflows/video_object_tags_workflow.json`：视频 → Florence2 检测 → 整段视频物体标签去重。

## 版本记录

- **1.6.0**：并入原 `test-comfyui` 插件（批量图片保存、每 N 张取一张、Florence2 标签去重、歌词对齐）；统一分类与命名；新增 NODES.md。
- 1.5.0：Audio Save、Subtitle & Translate、Ollama Translate、TTS Merge。
