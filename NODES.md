# ComfyUI Flyway — 节点说明与注意事项

版本 1.6.0 · 共 12 个节点 · 全部位于节点菜单 `flyway` 分类下 · 文档依据代码实际行为编写（2026-09-20）

> 本文档同时记录"已知问题"。带 ⚠️ / ❌ 的条目是读代码和已安装插件源码后发现的，**尚未在 ComfyUI 里实跑验证**，遇到时请以实际报错为准。

## 一、节点总览

| # | 显示名 | 类名（ID） | 一句话用途 | 来源 | 状态 |
|---|--------|-----------|-----------|------|------|
| 1 | 🐦‍🔥 Image List ↔ Directory | `ImageListDirectory` | 批量保存/读取目录图片 | flyway | ❌ 目前是占位实现 |
| 2 | 🐦‍🔥 逻辑过滤 | `ImageBatchLogicFilter` | 按整数条件放行图片批次 | flyway | ⚠️ |
| 3 | 🐦‍🔥 多行文本轮询 | `MultiLineTextInput` | 从多行文本里取一行 | flyway | ⚠️ 模式选项不生效 |
| 4 | 🐦‍🔥 Fish S2 Token 估算 | `FishS2TokenEstimator` | 估算 Fish S2 的 max_tokens 与时长 | flyway | ✅ |
| 5 | 🐦‍🔥 Audio Save | `FlywayAudioSave` | 音频预览/保存为多种格式 | flyway | ✅ |
| 6 | 🐦‍🔥 Subtitle & Translate | `FlywaySubtitleTranslate` | 词级时间戳 → 字幕 →（可选）翻译 | flyway | ⚠️ |
| 7 | 🐦‍🔥 Ollama Translate | `FlywayOllamaTranslate` | 用 Ollama 翻译现成字幕（可带图） | flyway | ⚠️ |
| 8 | 🐦‍🔥 TTS Merge | `FlywayTTSMerge` | 逐句 TTS 并按字幕时间轴合成音轨 | flyway | ❌ 与当前 FishAudioS2 不兼容 |
| 9 | 🐦‍🔥 Batch Image Save To Path | `BatchImageSaveToPath` | 批量存图到任意目录，循环内安全 | test-comfyui | ✅ |
| 10 | 🐦‍🔥 Select Every Nth Image | `SelectEveryNthImage` | 每 N 张取 1 张 | test-comfyui | ✅ |
| 11 | 🐦‍🔥 Florence2 Label Dedup | `Florence2LabelDedup` | 多帧检测标签合并去重 | test-comfyui | ⚠️ |
| 12 | 🐦‍🔥 Lyric Align -> LRC/SRT/ASS | `LyricAlignLRC` | 歌词对齐 / 无歌词直接转写 | test-comfyui | ⚠️ 依赖外部工具 |

- **类名（ID）没有改动**：旧工作流里保存的是类名，不是显示名，所以合并前存的工作流仍能正常加载。
- 中文标题来自 `locales/zh/main.json`（新前端下显示中文），英文显示名是回退。

## 二、先看这几条已知问题

1. **❌ TTS Merge 与当前安装的 ComfyUI-FishAudioS2 对不上**（见节点 8）。按源码推断，现在每一句都会报错，输出会是一条静音轨。
2. **❌ Image List ↔ Directory 是占位代码**：`flyway_nodes.py` 里 `process()` 只返回一张 64×64 黑图、空路径、0。README 旧版描述的"保存/读取/清空目录"功能在代码里并不存在。需要批量存图请用节点 9。
3. **⚠️ 多行文本轮询的 `output_mode` 不起作用**：代码始终按 `line_index` 取行（见节点 3）。
4. **⚠️ 示例工作流依赖第三方插件版本**（见第五节）。
5. `locales/*/main.json` 和 `js/flyway_audio.js` 里还留着已删除的 `FlywayAudioTimeAlign`（以及 js 里的 `FlywayFishAudioAlign`、`FlywayTranslateAndAlign`），无害，但对应节点已不存在。

---

## 三、节点详解

### 1. 🐦‍🔥 Image List ↔ Directory　`ImageListDirectory`　❌

**设计意图（来自旧 README）**：把图片批次存到目录并从目录按序号读回原图；`clear_directory` 在保存前清空目录；没有 `images` 输入时不清目录。

| 输入 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `path` | STRING | `output/frames` | 目录 |
| `clear_directory` | BOOLEAN | True | 保存前清空 |
| `filename_prefix` | STRING | `frame` | 文件名前缀 |
| `skip_count` | INT | 0 | 读取时跳过数量 |
| `max_count` | INT | 0 | 读取上限，0=不限 |
| `images`（可选） | IMAGE | — | 要保存的批次 |

输出：`images`(IMAGE)、`path`(STRING)、`count`(INT)

**注意**
- **当前代码不做任何保存/读取**，恒返回 `(1×64×64×3 全零图, "", 0)`。别把它放进正式流程。
- 要存图：用节点 9。要读目录图：用别的 Load Images From Directory 类节点。
- 想恢复功能需要重新实现 `process()`（git 历史里也没有完整版本，`flyway_nodes.py` 只在 init 提交里出现过）。

---

### 2. 🐦‍🔥 逻辑过滤　`ImageBatchLogicFilter`　⚠️

**简介**：拿 `any_input` 转成整数，和 `target_index` 比较，相等就放行图片批次并输出 True，否则输出占位图并输出 False。

| 输入 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `images` | IMAGE | — | 待过滤批次 |
| `target_index` | INT | 0 | 目标值 |
| `any_input`（可选） | `*` | — | 任意类型，需能被 `int()` 转换 |

输出：`IMAGE`、`布尔`(BOOLEAN)

**注意**
- 不匹配时返回的是 **1×1 的黑色占位图**，不是空批次。下游如果依赖图片尺寸会出问题，请用输出的布尔值配合开关/路由节点绕开。
- 没接 `any_input` 时按 `-1` 处理，只有 `target_index=-1` 才会放行。
- `any_input` 内容不能转成整数（例如普通文字）会直接报 `ValueError`。

---

### 3. 🐦‍🔥 多行文本轮询　`MultiLineTextInput`　⚠️

（中文语言包里标题为"多行文本输入"）

**简介**：忽略空白行，从多行文本中取出一行。

| 输入 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `text` | STRING(多行) | — | 原文 |
| `output_mode` | `sequential` / `random` / `index` | — | **目前不生效** |
| `line_index` | INT | 0 | 取第几行（从 0 开始） |

输出：`full_text`（原文）、`line_text`（选中的行）、`line_count`（非空行数）

**注意**
- **`output_mode` 被代码忽略**：无论选什么都执行 `lines[line_index % 行数]`。所以 `random` 不会随机，`sequential` 也不会自动前进——要轮询只能自己让 `line_index` 变化（例如接计数器/循环索引）。
- 索引对行数取模，超出范围会从头循环。
- 每行会去掉首尾空白；文本全空时返回 `(text, "", 0)`。

---

### 4. 🐦‍🔥 Fish S2 Token 估算　`FishS2TokenEstimator`　✅

**简介**：给 Fish Audio S2-Pro 估算 `max_new_tokens` 和大致时长，用来接 TTS 节点的 token 上限。

| 输入 | 类型 | 默认 | 范围 |
|------|------|------|------|
| `text` | STRING(多行) | `[inhales] 输入文本...` | — |
| `char_multiplier` | FLOAT | 2.0 | 0.5–10 |
| `tag_weight` | INT | 15 | 0–100 |
| `base_padding` | INT | 100 | 0–500 |
| `token_offset` | INT | 200 | -500–2000 |

输出：`max_tokens`(INT)、`est_duration_sec`(FLOAT)、`text`（原样透传）、`report`（文字报告）

**公式**：`max_tokens = int(纯文本字数 × char_multiplier + 标签数 × tag_weight + base_padding + token_offset)`；`时长 = round(max_tokens / 40, 1)`
例：100 字 + 2 个标签 → 100×2.0 + 2×15 + 100 + 200 = 530 tokens ≈ 13.2 秒。

**注意**
- 标签 = 形如 `[inhales]` 的方括号内容；统计字数时会先把标签去掉，其余字符（含空格、标点、换行）都按 1 个字算。
- **时长是 token 预算换算出来的上限估计，不是真实音频时长**（40 tokens/秒是经验值）。实测偏差大就调 `char_multiplier`。
- 中英文用同一套系数；语言差别大时要分别调。
- 文本为空返回 `(0, 0.0, text, "⚠️ 输入文本为空")`。

---

### 5. 🐦‍🔥 Audio Save　`FlywayAudioSave`　✅

**简介**：预览或保存 AUDIO 为 wav / flac / mp3 / aac / ogg / m4a / opus。节点上带播放器（由 `js/flyway_audio.js` 提供）。

| 输入 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `audio` | AUDIO | — | |
| `save_file` | BOOLEAN | **False（Preview only）** | 关=只预览，开=存盘 |
| `format` | 下拉 | wav | 7 种格式 |
| `quality` | 下拉 | default | 有损格式的码率/质量 |
| `filename_prefix` | STRING | `audio/output` | 可带子目录 |

输出：`filepath`、`filename`（OUTPUT_NODE，无需下游也会执行）

**注意**
- **默认不保存！** 必须把 `save_file` 打开才会写到 `output/`；预览文件放在 temp 目录，此时 `filepath` 输出为空字符串。
- `filename_prefix` 里的**末尾 `.xxx` 会被当成扩展名去掉**：`my.song` → `my`，`v1.2` → `v1`。文件名里的非法字符会换成 `_`。
- 同名文件不覆盖，自动加 `_0001`、`_0002`…。
- `wav`/`flac` 是无损，`quality` 被忽略（wav 以 24 位写出）。`mp3/aac/m4a/opus` 只认 `320k…64k` 这类码率，选 `default` 或 `qN` 时按 192k；`ogg` 只认 `q9/q7/q5/q3`，选码率会退回 q7。
- 依赖：wav/flac 用 `soundfile`；其余格式要 `pydub` + 系统 **ffmpeg**（`requirements.txt` 里 pydub 默认不自动装，见文件注释）。
- `filename_prefix` 的子目录部分没有做安全限制，写 `../` 或绝对路径可以存到 output 之外；这种情况下节点上的播放器可能播不了（前端 `/view` 只服务 output/temp/input）。

---

### 6. 🐦‍🔥 Subtitle & Translate　`FlywaySubtitleTranslate`　⚠️

**简介**：把"词级时间戳文本"切成字幕行（SRT / WebVTT），可选再整体翻译。分句有两种模式：`punctuation`（纯标点/停顿规则，不调 LLM）和 `llm`（让 LLM 分组）。

| 输入 | 默认 | 说明 |
|------|------|------|
| `timestamps` | 示例文本 | 每行 `开始-结束: 词`，如 `0.08-0.24: It's` |
| `segment_mode` | punctuation | `punctuation` / `llm` |
| `subtitle_format` | SRT | `SRT` / `WebVTT` |
| `api_base_url` | `http://127.0.0.1:11434` | OpenAI 兼容服务（Ollama 可用） |
| `model_list` / `custom_model` | — | 自定义模型名优先于下拉 |
| `temperature` `top_p` `top_k` `repeat_penalty` | 0.2 / 0.9 / 40 / 1.05 | 仅用于翻译 |
| `num_ctx` | 8192 | **实际被当作 `max_tokens`（输出上限）发送** |
| `timeout_seconds` | 300 | |
| `target_language` | Chinese | **留空 = 不翻译** |
| `translate_system_prompt` | 内置 | 可用 `{target_language}` 占位符 |
| `unload_after` | False | 结束后让 Ollama 卸载模型 |
| `source_text`（可选） | — | 仅 `llm` 分句时作为参考文本 |

输出：`subtitle`（源语言字幕）、`translated_subtitle`（译文字幕，不翻译时为空）、`plain_lines`（纯文本，有译文用译文）

**注意**
- **时间戳格式必须严格匹配** `数字-数字: 词`，不匹配的行被**静默忽略**；一行都没有则返回三个空字符串（控制台有日志）。
- `punctuation` 规则写死、界面不可调：句末标点必断；与下一词间隔 ≥0.35 秒断；逗号类标点且已有 ≥3 个词断；每行最多 18 个词。中日文词之间不加空格。
- `llm` 分句：LLM 输出解析失败会自动回退到 `punctuation`；但**若 LLM 漏掉了某些词的编号，这些词会直接从字幕里消失**（不会补回）。分句时采样参数固定（0.1/0.95/20/1.0）。
- **`num_ctx` 并不设置 Ollama 的上下文窗口**（只作为 `max_tokens`）。走 `/v1/chat/completions` 时上下文长度由 Ollama 服务端/模型决定，长字幕可能被截断。需要真正控制 `num_ctx` 请用节点 7。
- **翻译是把整份字幕一次性发给模型**，没有分块，也不校验译文的字幕块数/时间码是否与原文一致——长视频容易超长或错位，请抽查。
- 只会清掉 `<|...|>` 形式的特殊标记；**思考型模型输出的 `<think>…</think>` 不会被清除**，可能混进字幕。
- 模型下拉列表是 ComfyUI 启动、加载节点定义时按**默认地址**查询一次并缓存的：Ollama 没开着时启动，下拉里就只有 `(no models found)`；改 `api_base_url` 不会刷新下拉。此时请填 `custom_model`，或先开 Ollama 再重启 ComfyUI。
- `unload_after` 只对 Ollama 有效（调用 `/api/generate` 的 `keep_alive=0`）；翻译请求失败时会先抛错，不会执行卸载。

---

### 7. 🐦‍🔥 Ollama Translate　`FlywayOllamaTranslate`　⚠️

**简介**：独立的 Ollama 翻译节点，直接翻译一份现成的 SRT/WebVTT 文本，可选附一张图给多模态模型当上下文。

| 输入 | 默认 | 说明 |
|------|------|------|
| `subtitle_text` | — | 完整 SRT/WebVTT（可接节点 6 的 `subtitle`） |
| `ollama_url` | `http://127.0.0.1:11434` | |
| `model_list` / `custom_model` | — | 自定义优先 |
| `system_prompt` | 内置字幕翻译提示词 | 要求保留时间码与块数 |
| `target_language` | Chinese | 会以 `Target language: xxx` 追加到系统提示词末尾 |
| `temperature` `top_p` `top_k` `repeat_penalty` | 0.3 / 0.9 / 40 / 1.1 | |
| `num_ctx` | 4096 | 通过 Ollama 原生 `options.num_ctx` 真正生效 |
| `timeout_seconds` | 300 | |
| `unload_after` | False | 结束后卸载模型 |
| `image`（可选） | — | 只取批次里的**第一张**，转 PNG(base64) 发送 |

输出：`translated_subtitle`（含时间码）、`plain_lines`（只有文字行）

**注意**
- 走的是 Ollama **原生** `/api/chat`（节点 6 走 OpenAI 兼容接口），所以只能连 Ollama，不能连 vLLM 等。
- 模型下拉同样在启动时按默认地址查询一次；连**远程 Ollama** 时请直接填 `custom_model`。
- 图片要求 RGB；转换失败只会在控制台打印一行，然后不带图继续。
- 同样不会清除思考型模型的 `<think>` 内容，也没有分块与校验。
- 与节点 6 重叠的部分：都能翻译字幕。区别是本节点支持图片、`num_ctx` 生效，但不能做分句；`target_language` 留空**不会**跳过翻译。
- `subtitle_text` 为空直接返回两个空字符串。

---

### 8. 🐦‍🔥 TTS Merge　`FlywayTTSMerge`　❌（先读这一节）

**简介**：读取翻译后的 SRT，逐句调用 FishAudioS2 生成语音，按每句的时间槽对齐，拼成一条完整音轨，可混入背景音。

| 输入 | 默认 | 说明 |
|------|------|------|
| `translated_subtitle` | — | SRT / WebVTT 文本 |
| `checkpoint` | 扫描得到 | 见下文兼容性问题 |
| `precision` | half | `float32`/`half`/`bfloat16` |
| `compile` | False | |
| `seed` | 42 | 每一句用同一个 seed |
| `overflow_mode` | stretch | `stretch` 拉伸到时间槽 / `trim` 截断 / `overflow` 原样放置可重叠 |
| `tts_volume` | 1.0 | 0–2 |
| `ref_audio` `ref_text`（可选） | — | 声音克隆 |
| `bg_audio` `mix_background` `bg_volume`（可选） | — / False / 0.4 | 背景音 |
| `per_segment_json`（可选） | 空 | 逐句覆盖，如 `[{"index":3,"speed":1.15},{"index":7,"volume":0.6}]`（index 从 1 起） |

输出：`audio`(AUDIO)、`report`(每句状态报告)。不是 OUTPUT_NODE，需接下游（如节点 5）才会执行。

**❌ 兼容性问题（按源码对比得出，未实跑）**
节点通过 `nodes.NODE_CLASS_MAPPINGS` 取 `FishS2TTS` / `FishS2VoiceCloneTTS`，再按**参数名里是否含某个子串**去猜怎么传参。当前安装的 ComfyUI-FishAudioS2 与之不匹配：
- Fish 的 `generate()` 有 15 个**必填**参数（`model_path, text, language, device, precision, attention, max_new_tokens, chunk_length, temperature, top_p, repetition_penalty, seed, keep_model_loaded, offload_to_cpu, compile_model`），本节点只传了其中一部分，缺少的会触发 `TypeError`；
- 参数名里含 `model` 的 `keep_model_loaded`、`compile_model` 会被误塞进 `checkpoint` 字符串；
- `precision` 传的 `half` 不在 Fish 接受的 `auto/bfloat16/float16/float32` 里；
- `checkpoint` 下拉扫描的是 `custom_nodes/ComfyUI-FishAudioS2/checkpoints`，而 Fish 实际从 `ComfyUI/models/fishaudioS2/` 找模型；
- 克隆声音的 `reference_text` 是 Fish 的**可选**参数，本节点只遍历必填参数，所以永远不会传过去。

结果：每一句都会在 `report` 里显示 `ERROR`，最终输出是静音轨。要让它工作，需要改成按 Fish 当前的参数名显式传参（并补齐语言、设备、attention、采样参数等），这一步尚未做。

**其他注意（即使修好兼容性也适用）**
- **`speed` 在 `stretch` 模式下实际无效**：先按 speed 缩放，随后又被拉伸到时间槽长度，最终长度由时间槽决定；`speed` 只在 `trim` / `overflow` 下有意义。
- `per_segment_json` 里只写 `speed` 时，`volume` 会被当成 **1.0**，**不会**沿用 `tts_volume`（反之亦然）。
- `stretch` 既压缩也拉长：一句很短的话放进很长的时间槽会被明显拉慢。依赖 `librosa`；没有 librosa 时退化为最近邻重采样（音高会变）。
- `trim` 是硬截断，没有淡出。
- 解析字幕时，**纯数字的文字行会被丢弃**（会被当成序号），例如整句只有 `2024` 的字幕。字幕块按出现顺序重新编号（`per_segment_json` 的 index 就是这个顺序号），不使用 SRT 自带序号。
- 输出采样率：接了 `bg_audio` 就用它的采样率和时长（即使 `mix_background` 关着），否则 44100Hz、时长 = 最后一句结束 + 1 秒。峰值超过 1.0 会整体归一化。
- 单句失败不会中断，只在 `report` 里记录，所以**一定要看 report**。
- `checkpoint` 列表在 ComfyUI 启动时扫描一次，新增模型需重启。

---

### 9. 🐦‍🔥 Batch Image Save To Path　`BatchImageSaveToPath`　✅

**简介**：把图片批次存到任意目录，可选"先清空"或"接着已有编号续存"。**每次运行必定真正执行**，专为循环内反复调用设计。

| 输入 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `images` | IMAGE | — | |
| `save_path` | STRING | 空 | 目录，不存在会创建；**为空会报错** |
| `clear_before_save` | BOOLEAN | False | True=先删光目录里的图片再从 00000 开始 |
| `filename_prefix`（可选） | STRING | `image` | |
| `file_format`（可选） | png/jpg/webp | png | jpg/webp 质量固定 95 |

输出：`output_path`（原样回传 `save_path`，可直接接"从目录加载图片"节点）。OUTPUT_NODE。

**为什么单独做这个**：一些社区节点在 Loop 里只会重复保存第一轮的批次，原因是 ComfyUI 缓存认为输入没变而跳过执行。本节点的 `IS_CHANGED` 恒返回 NaN（永不等于自身），所以每轮都会真的保存。

**注意**
- **`clear_before_save=True` 会删除目录里所有图片文件**（png/jpg/jpeg/webp/bmp/tif/tiff，不看前缀，不递归）。别指向存有其他图片的目录。
- **在循环里要设为 False**，否则每一轮都会清掉上一轮，最后只剩最后一批。需要"循环开始前清空一次"时，可在循环外先用另一个节点清一次。
- 续存模式下，编号接在该前缀已有的最大编号之后；文件名形如 `image_00007.png`。
- 因为永远重新执行，**依赖它输出的下游节点每次也会重新运行**。
- `save_path` 用相对路径时相对于 ComfyUI 进程的工作目录，建议写绝对路径。
- `jpg` 会把 RGBA 转 RGB；图片需为 RGB/RGBA（单通道会报错）。
- 与节点 1 的关系：节点 1 是占位实现，存图请用本节点。

---

### 10. 🐦‍🔥 Select Every Nth Image　`SelectEveryNthImage`　✅

**简介**：从图片批次里每隔 N 张取 1 张（索引 0、N、2N…），作为抽帧与逐帧模型（如 Florence2）之间明确可见的降采样步骤。

| 输入 | 默认 | 范围 |
|------|------|------|
| `images` (IMAGE) | — | — |
| `n` (INT) | 1 | 1–10000 |

输出：`images`、`count`

**注意**
- 一定包含第 0 张，不保证包含最后一张；`n` 大于帧数时只剩第 0 张。
- 视频加载节点自己也能按帧率抽帧（示例工作流用 `force_rate` 做到 1 帧/秒）；本节点适合"已经有一整批帧，再降采样"。

---

### 11. 🐦‍🔥 Florence2 Label Dedup　`Florence2LabelDedup`　⚠️

**简介**：把 Florence2 在整段视频各帧上检测出的物体标签合并成一份去重、排序后的英文标签列表，如 `car, dog, person`。

| 输入（全部可选） | 类型 | 说明 |
|------|------|------|
| `florence2_data` | `*`（任意） | Florence2Run 的 `data` 输出 |
| `caption_text` | STRING | Florence2Run 的 `caption` 输出 |

输出：`unique_labels`（逗号+空格分隔）、`unique_count`

**处理规则**：全部转小写 → 合并空白 → 去掉首尾 `. , ; :` → 精确去重 → 按字母序排序。

**注意（按已安装的 comfyui-florence2 源码推断）**
- **检测类任务要用 `caption_text` 这一路**。`region_caption`（即 Florence-2 的 `<OD>` 目标检测）和 `dense_region_caption` 的 `data` 输出里**只有边框坐标，没有标签**，所以 `florence2_data` 对它们提不出任何标签。`data` 里带标签的只有 `caption_to_phrase_grounding`（标签是你输入的短语）等少数任务。
- `caption` 的原始文本形如 `person<loc_12><loc_30>…car<loc_5>…`。本节点现在会先把所有 `<...>` 特殊标记当分隔符去掉再拆分（合并进来时新增的处理；原版没有，会得到一整串带 `<loc_>` 的垃圾标签）。
- 已安装版本里**没有 `object_detection` 这个任务名**（旧文档/旧工作流里的写法），用 `region_caption`。
- 去重只做字符串精确匹配：`person` 与 `persons`、`car` 与 `cars` 会同时保留；小写化后专有名词大小写丢失。
- 两路都不接则返回 `("", 0)`。
- `florence2_data` 用的是"接受任意类型"的输入（`AnyType`），合并时补了 `__hash__`，避免该类型字符串不可哈希。

---

### 12. 🐦‍🔥 Lyric Align -> LRC/SRT/ASS　`LyricAlignLRC`　⚠️

**简介**：两种工作方式——
1. **提供歌词**：调用外部命令行 `lyric-align`，把已知歌词对齐到音频，输出带时间戳的歌词；
2. **不提供歌词（`lyrics_text` 留空）**：直接用 faster-whisper 转写，输出按句时间戳。

| 输入 | 默认 | 说明 |
|------|------|------|
| `audio` | — | 只取批次里的第 1 条 |
| `lyrics_text` | 空 | 一行一句；空行、`# 注释`、`[Verse 1]` 这类段落标记会被忽略 |
| `language` | zh | `zh`/`ja`/`en`…；CJK 会自动用更低的匹配阈值 |
| `asr_model` | `<ComfyUI>/models/whisper/lyric-align-large-v3-ct2` | faster-whisper 模型名或本地 CTranslate2 目录 |
| `asr_device` | cpu | `cpu` / `cuda` |
| `output_format` | lrc | `lrc elrc srt vtt ass ttml` |
| `no_vad`（可选） | False | 关闭人声检测；慢速长音（抒情/圣歌）会被误判为静音时要开 |
| `karaoke`（可选） | False | 逐字卡拉 OK 时间戳（仅有歌词时） |
| `interpolate`（可选） | False | 没匹配上的行用插值补全（仅有歌词时） |
| `save_lyrics`（可选） | True | 是否存到磁盘 |
| `free_vram_first`（可选） | True | `cuda` 时先卸载 ComfyUI 已加载模型并清缓存 |
| `output_dir`（可选） | 空 | 空则用 `output/audio/` |
| `filename_prefix`（可选） | `lyric_align_out` | |

输出：`aligned_text`（歌词文本）、`output_path`（文件路径）。不是 OUTPUT_NODE，需接下游节点才会执行。

**外部依赖**
- 有歌词模式：`lyric-align` 命令必须在 **ComfyUI 进程的 PATH** 里。安装：`pip install uv`，然后 `uv tool install "lyric-align[asr]"`。便携版启动脚本常常看不到用户 PATH，找不到时从能运行 `lyric-align --version` 的终端启动 ComfyUI。
- 无歌词模式：由 ComfyUI 自己的 Python 运行 `flyway_transcribe_only.py`，需要该环境装有 `faster-whisper`。
- 使用 CUDA 时，如果存在 `<ComfyUI>/third_party/faster-whisper-cuda12` 目录，会把它加到子进程 PATH 前面（CTranslate2 的 CUDA12 DLL）。

**注意**
- **无歌词模式只支持 `lrc` / `srt` / `vtt`**。选 `elrc`、`ass`、`ttml` 时转写脚本会**改写成 LRC 内容，但文件仍按你选的扩展名保存**（例如一个内容是 LRC 的 `.ass` 文件）；`karaoke`、`interpolate` 在该模式下无效。
- 无歌词模式下 `asr_model` 若留空，用 `medium`（会从网络下载）。`cuda` 用 float16，`cpu` 用 int8；只输出句级时间戳。
- 每次运行都是**新开子进程重新加载模型**，比较慢；默认 `cpu`，长歌会更久。超时 1800 秒。
- 同一个 `filename_prefix` 每次运行会**覆盖**上一次的输出文件（不自动编号）。
- `save_lyrics=False` 时文件写在系统临时目录，`output_path` 指向临时文件。
- 每次运行创建的临时目录（含一份 WAV）**不会自动清理**，长期使用会在 `%TEMP%` 里堆积。
- `free_vram_first` 会调用 `unload_all_models()`：之后 ComfyUI 里的其他模型需要重新加载。
- 命令失败会把子进程的 stdout/stderr 全文放进报错信息里，排查时看这里。
- `asr_model` 默认路径和 CUDA DLL 路径现在由 ComfyUI 安装位置推算（合并前是写死的 `I:\AI\...`），在当前机器上结果一致。

---

## 四、辅助文件（不是节点）

### `flyway_transcribe_only.py`
无歌词模式下由节点 12 以子进程方式调用的转写脚本，**不会被 `__init__.py` 导入**。
命令行：`python flyway_transcribe_only.py <audio> <model> <device> <language> <no_vad 0|1> <format> <output_path>`。
用 faster-whisper 转写（`vad_filter = not no_vad`，`beam` 用默认值），写出 `lrc/srt/vtt/json`；其他格式回退到 lrc 并在 stderr 提示。

### `js/flyway_audio.js`
前端扩展：给 `FlywayAudioSave`（以及列表里已不存在的几个节点名）在执行后添加 `<audio>` 播放器，读取后端返回的 `ui.audio`。

### `locales/en|zh/main.json`
节点标题与简介的多语言文本。

---

## 五、示例工作流 `example_workflows/video_object_tags_workflow.json`

**目的**：一段视频 → 整段视频出现过的物体标签列表。
**链路**：`VHS_LoadVideoPath`（`force_rate=1`，每秒 1 帧）→ `Florence2Run`（`region_caption`）→ `Florence2LabelDedup`（接 `caption` 与 `data`）→ `ShowText|pysssss` 预览。

**依赖的第三方插件**：ComfyUI-VideoHelperSuite、comfyui-florence2（kijai）、ComfyUI-Custom-Scripts（仅用于预览文字，可换成别的显示节点）——这几个在当前机器上都已安装。

**注意**
- 使用前把 `VHS_LoadVideoPath` 里的 `PUT_VIDEO_PATH_HERE.mp4` 换成真实视频路径。
- 这份 JSON 是手写的（带自定义 `comment` 字段），`widgets_values` 按**位置**对应控件。合并时我已按当前安装的 comfyui-florence2 校正了 `Florence2Run`（任务改为 `region_caption`，控件顺序对齐），并把 `data` 输出的类型名改为 `JSON`；`VHS_LoadVideoPath` 和 `DownloadAndLoadFlorence2Model` 的控件值**没有改**，不同版本的插件控件顺序可能不同，加载后请逐个核对。
- 没有用到节点 10；视频很长时可在 `Florence2Run` 之前插入它进一步降采样。

---

## 六、合并记录（test-comfyui → comfyui-flyway）

| 原文件（test-comfyui） | 现位置（comfyui-flyway） | 改动 |
|------|------|------|
| `batch_image_save_to_path.py` | `flyway_batch_image_save.py` | 分类改为 `flyway`；显示名加 🐦‍🔥 |
| `florence2_label_dedup.py`（含 2 个节点） | `flyway_florence2_tools.py` | 同上；`AnyType` 补 `__hash__`；标签提取前剥掉 `<...>` 标记；文档字符串改用 `region_caption` |
| `lyric_align_node.py` | `flyway_lyric_align.py` | 同上；写死的 `I:\AI\…` 路径改为由 `folder_paths` 推算；辅助脚本改名引用 |
| `transcribe_only.py` | `flyway_transcribe_only.py` | 仅改名与文档字符串 |
| `video_object_tags_workflow.json` | `example_workflows/` | 见第五节 |
| `__init__.py` | 合并进 comfyui-flyway 的 `__init__.py` | 版本 1.5.0 → 1.6.0 |

- 12 个节点类名两两不冲突，未做任何类名改动。
- 旧的 `test-comfyui` 文件夹已**移到 `custom_nodes/.disabled/test-comfyui`**（ComfyUI 不会加载 `.disabled`，也是 ComfyUI-Manager 的禁用位置）。留着原目录会导致同名节点被加载两次、且后加载的旧版覆盖新版。确认无误后可自行删除，或从 Manager 里重新启用。
- 同步更新：`pyproject.toml`（版本与描述）、`requirements.txt`（更正"无额外依赖"的注释，补充可选依赖说明）、`locales/en|zh/main.json`（新增 4 个节点条目）、`README.md`（改为概览并指向本文）。

## 七、依赖速查

| 功能 | 需要 |
|------|------|
| 全部节点 | ComfyUI 自带的 torch / numpy / Pillow |
| 音频缩放/重采样（TTS Merge） | `librosa`（在 requirements.txt） |
| Audio Save 的 wav/flac | `soundfile`（在 requirements.txt） |
| Audio Save 的 mp3/aac/m4a/ogg/opus | `pydub` + ffmpeg |
| Subtitle & Translate / Ollama Translate | 可访问的 Ollama（或 OpenAI 兼容）服务 |
| TTS Merge | ComfyUI-FishAudioS2（且需先修复兼容性） |
| Lyric Align（有歌词） | `lyric-align` 命令行（`uv tool install`） |
| Lyric Align（无歌词） | `faster-whisper` |
| 示例工作流 | VideoHelperSuite、comfyui-florence2 |

## 八、目录结构

```
comfyui-flyway/
├─ __init__.py                     注册全部 12 个节点，声明 WEB_DIRECTORY
├─ NODES.md                        本文
├─ README.md                       概览
├─ flyway_nodes.py                 节点 1–4
├─ flyway_audio_save.py            节点 5
├─ flyway_subtitle_translate.py    节点 6
├─ flyway_ollama_translate.py      节点 7
├─ flyway_tts_merge.py             节点 8
├─ flyway_batch_image_save.py      节点 9   （来自 test-comfyui）
├─ flyway_florence2_tools.py       节点 10、11（来自 test-comfyui）
├─ flyway_lyric_align.py           节点 12  （来自 test-comfyui）
├─ flyway_transcribe_only.py       辅助脚本（非节点）
├─ js/flyway_audio.js              前端音频播放器
├─ locales/en|zh/main.json         多语言标题
├─ example_workflows/              示例工作流
├─ requirements.txt / pyproject.toml
```
