# MP3 专辑播放器

一个零构建、单文件的本地 MP3 专辑播放器，配套 `merge.py` 把文件夹里的歌曲合并成“一个 MP3 + CHAP 章节”的专辑文件。

- 播放器：`music-player.html`，直接用浏览器打开即可，无需安装、无需联网。
- 合并工具：`merge.py`，需要 Python、ffmpeg 和 mutagen。
- 所有播放列表和设置只保存在本机浏览器的 localStorage 中，没有服务端。

## 目录

- [播放器功能](#播放器功能)
- [快速开始](#快速开始)
- [播放器使用说明](#播放器使用说明)
- [merge.py 用法](#mergepy-用法)
- [数据与持久化](#数据与持久化)
- [项目结构](#项目结构)
- [已知限制](#已知限制)
- [许可证](#许可证)

## 播放器功能

- **专辑即文件**：一个 MP3 文件视为一张专辑，文件内的 ID3v2 `CHAP` 章节视为歌曲。
- **章节解析**：自动读取章节标题和起止时间；没有 `CHAP` 时，整个文件作为一个“虚拟章节”。
- **歌曲列表**：显示章节标题、时长和数量，点击切歌，当前章节高亮。
- **四种播放模式**：顺序播放、列表循环、单曲循环、随机播放。
- **章节级进度**：进度条和时间显示的是当前章节内部的进度。
- **音量手势**：按住音量按钮左右滑动调节，松手收起；音量持久化。
- **暂停淡出**：暂停、定时到点、锁屏暂停时约 300ms 淡出。
- **定时暂停**：15 / 30 / 60 / 90 分钟循环切换，可选择“播完当前歌曲再暂停”。
- **专辑管理**：长按拖动排序（带边缘自动滚动）、重命名、删除。
- **外观**：深色模式、自定义 16 进制主题色（保留最近 4 个）。
- **两种全屏**：
  - 播放卡片上的放大按钮：页面内的卡片放大模式，隐藏专辑列表和页头。
  - 设置里的“全屏显示”：向浏览器申请真正的全屏。
- **放大界面**：中间显示唱片图标，播放时旋转、暂停时停止，带同心圆环。
- **系统集成**：Media Session 锁屏控制、Wake Lock 屏幕常亮（浏览器支持时）。
- **移动端适配**：设置菜单在键盘弹出时固定到键盘上方；窗口高度不足时菜单内部滚动。

## 快速开始

1. 用浏览器打开 `music-player.html`（Chrome / Edge / Safari / Firefox 均可）。
2. 点击左侧列表底部的“添加文件”：
   - 输入 `file:///` 地址，例如 `file:///D:/music/合辑.mp3`，会保存到 localStorage；
   - 或点“从本机选择文件”，选择一个或多个音频文件（仅当前会话有效）。
3. 在左侧点击专辑，右侧会出现歌曲列表，点击歌曲或播放按钮开始播放。

> 浏览器对 `file://` 页面读取本地文件有安全限制。如果地址添加成功但歌曲列表一直为空，通常是浏览器阻止了本地 XHR；此时改用“从本机选择文件”，或使用允许本地文件访问的浏览器/WebView。

## 播放器使用说明

### 添加与管理专辑

- 左侧“专辑文件”列表是播放器的资料库。
- 点击条目加载专辑；长按约 450ms 后可拖动排序，拖到列表顶部/底部会自动滚动。
- 条目右侧的 `⋯` 菜单可以重命名或删除。
- 地址添加的专辑会持久化；本机选择的文件使用临时 Blob 地址，刷新页面后失效。

### 播放控制

- 上一首 / 下一首在当前专辑的章节内切换。
- 播放模式按钮循环切换：顺序 → 列表循环 → 单曲循环 → 随机。
- 音量按钮按住后滑动调节，松手自动收起。
- 定时按钮循环切换 15 / 30 / 60 / 90 分钟；设置里可开启“定时到点后播完当前歌曲”。

### 设置

- **深色模式**：立即生效并持久化。
- **全屏显示**：请求浏览器全屏，开关状态跟随实际全屏状态（Esc 或系统手势退出也会同步）。
- **主题颜色**：输入 `#rrggbb` 后点“应用”；最近使用的 4 个颜色会显示在输入框左侧。
- **定时到点后播完当前歌曲**：开启后，定时到点不会立刻暂停，而是等当前章节播完。
- **关于与使用说明**：查看功能摘要。

### 放大模式

- 点击播放卡片左上角的放大按钮，进入页面内的放大布局；按 `Esc` 或再次点击退出。
- 放大界面中间会显示唱片图标：播放时旋转，暂停时停在当前角度。
- 这与设置里的“全屏显示”是两个独立功能：前者改变页面布局，后者调用浏览器 Fullscreen API。

## merge.py 用法

`merge.py` 用于把**同一个文件夹下的多个 MP3** 合并成一个 MP3，并写入：

- ID3v2 `CHAP` 章节帧（章节标题、起止时间），让本播放器把每首歌识别为一个章节；
- 可选的 `SYLT` 同步歌词（把每首歌的歌词按章节起始时间拼接）；
- 统一的音频编码参数（可选，避免采样率/比特率/声道不一致导致合并失败）。

### 环境要求

- Python 3.8+（推荐 3.9+）
- `ffmpeg` 已安装并在 `PATH` 中
- Python 包 `mutagen`

安装依赖：

```bash
python -m pip install mutagen
ffmpeg -version
```

ffmpeg 安装方式：

```bash
# Windows（winget）
winget install Gyan.FFmpeg

# macOS
brew install ffmpeg

# Debian / Ubuntu
sudo apt install ffmpeg
```

### 基本用法

```bash
python merge.py <folder> <output> [选项]
```

- `folder`：要扫描的文件夹，**只扫描第一层**，不会递归子文件夹，只处理 `.mp3`。
- `output`：输出文件名。
  - 不带 `.mp3` 后缀会自动补上。
  - 绝对路径按原样使用；相对路径会拼在 `folder` 下面。
  - 例如 `python merge.py ./music 合辑.mp3` 输出到 `./music/合辑.mp3`。
  - 输出目录必须已存在，否则报错退出。
  - 如果输出文件已存在，ffmpeg 会直接覆盖。
  - 扫描时会排除输出文件本身，避免把上一次的结果再次合并。

最简单的例子：

```bash
python merge.py "D:\music\专辑" "D:\music\合辑.mp3"
```

输出到扫描目录内：

```bash
cd D:\music
python merge.py "专辑" "合辑.mp3"
# 结果：D:\music\专辑\合辑.mp3
```

### 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `folder` | 必填 | 扫描 MP3 的文件夹 |
| `output` | 必填 | 输出文件；无 `.mp3` 后缀会自动补 |
| `--title` | `合辑` | 输出文件的全局标题（写入 FFMetadata/ID3） |
| `--sort-by` | `track` | `track`：优先按 ID3 音轨号 `TRCK`，缺失的排在后面按文件名；`filename`：始终按文件名 |
| `--chapter-title-source` | `metadata` | `metadata`：优先 ID3 `TIT2`，缺失回退文件名；`filename`：直接用文件名（去后缀） |
| `--normalize` | `auto` | `auto`：编码参数不一致时才归一化；`always`：总是归一化；`never`：直接流复制 |
| `--normalize-bitrate` | 自动 | 归一化目标比特率，如 `128k`、`256k`、`320k`；默认取源文件最大值 |
| `--normalize-sample-rate` | 自动 | 归一化目标采样率，如 `44100`；默认取源文件最大值 |
| `--normalize-channels` | 自动 | 归一化目标声道数，`1` 或 `2`；有声书可用 `1` |
| `--normalize-codec` | `libmp3lame` | 归一化使用的 ffmpeg 音频编码器 |
| `--lyrics-lang` | `chi` | 写入 SYLT 的语言代码（ISO-639-2，必须 3 个字符，否则改用 `und`） |
| `--chapter-markers` | 关闭 | 在每个有歌词的章节开头插入一行 `--- 章节名 ---` |
| `--no-lyrics` | 关闭 | 跳过歌词处理，只合并音频与章节 |

### 排序规则

默认 `--sort-by track`：

1. 有 `TRCK` 音轨号的文件排在前面，按音轨号升序；
2. 没有音轨号的文件排在所有有音轨号的文件之后，按文件名升序；
3. 如果所有文件都没有音轨号，则等同于按文件名排序。

`--sort-by filename`：始终按文件名（不区分大小写）排序。文件名建议用 `01`、`02` 这样的两位前缀，避免 `10` 排在 `2` 前面。

### 章节标题

- `--chapter-title-source metadata`（默认）：优先读取 ID3 `TIT2`，没有则用文件名去掉 `.mp3`。
- `--chapter-title-source filename`：始终用文件名去掉 `.mp3`。
- 章节的起止时间根据每个文件的实际时长累加计算；写入的是毫秒时间戳。

### 编码归一化

`--normalize auto` 会比较每个文件的：

- 采样率
- 声道数
- 平均比特率（kbps）

只要有任一参数不一致，或某个文件读不出参数，就把**所有文件**重新编码到统一参数。目标值默认取各维度的最大值，也可以用 `--normalize-bitrate`、`--normalize-sample-rate`、`--normalize-channels` 显式指定。

- `--normalize always`：无条件重新编码。适合源文件来源混杂、或有声书需要统一为单声道的情况。
- `--normalize never`：不重新编码，直接 `-c copy` 拼接。只有确认所有文件编码参数完全一致时才建议使用，否则可能出现合并失败、时长异常或播放杂音。
- 重新编码默认使用 `libmp3lame`，属于有损转码；不需要时优先用 `auto`。

### 歌词处理

对每个源文件，按以下顺序找歌词：

1. MP3 内嵌的 `SYLT` 帧（要求时间戳为毫秒格式）；
2. 同目录下同名的 `.lrc` 文件（例如 `01.mp3` 对应 `01.lrc`）。

LRC 解析支持：

- UTF-8（含 BOM）和 GBK 编码；
- `[mm:ss]`、`[mm:ss.xx]`、`[mm:ss.xxx]` 时间戳；
- 一行多个时间戳；
- `[offset:...]` 全局偏移（正数按“歌词提前”处理，从时间戳中减去）。

每首歌的歌词会按该章节的起始时间整体偏移，然后拼接成一条完整时间轴，写入输出文件的 `SYLT` 帧（UTF-16、ID3v2.3、类型为歌词、时间戳单位毫秒）。

- `--chapter-markers`：在每个有歌词的章节前插入一行 `--- 章节名 ---`，方便在歌词里看到分段。
- `--lyrics-lang chi`：指定语言代码；不是 3 个字符时会退化为 `und`。
- `--no-lyrics`：完全不处理歌词，章节仍然正常写入。
- 如果所有文件都没有带时间戳的歌词，会打印“没有可写入的同步歌词”，输出文件仍然可用。

> 注意：本播放器目前只读取 `CHAP` 章节，**不显示歌词**。`SYLT` 是写给支持同步歌词的播放器/设备的。

### 示例

```bash
# 最简：按音轨号排序并合并
python merge.py "D:\music\专辑" "D:\music\合辑.mp3"

# 指定全局标题，按文件名排序
python merge.py "D:\music\专辑" "D:\music\合辑.mp3" --title "我的精选集" --sort-by filename

# 章节名直接用文件名
python merge.py "D:\music\专辑" "D:\music\合辑.mp3" --chapter-title-source filename

# 强制统一为 128kbps
python merge.py "D:\music\专辑" "D:\music\合辑.mp3" --normalize always --normalize-bitrate 128k

# 有声书：单声道 96kbps
python merge.py "D:\audiobook" "D:\audiobook\合辑.mp3" --normalize always --normalize-channels 1 --normalize-bitrate 96k

# 章节标题也插入歌词，语言代码 chi
python merge.py "D:\music\专辑" "D:\music\合辑.mp3" --chapter-markers --lyrics-lang chi

# 只合并音频和章节，不处理歌词
python merge.py "D:\music\专辑" "D:\music\合辑.mp3" --no-lyrics

# 确认源文件参数完全一致，直接流复制
python merge.py "D:\music\专辑" "D:\music\合辑.mp3" --normalize never
```

### 输出与临时文件

- 输出是一个 MP3，包含音频、全局标题、`CHAP` 章节；有歌词时再包含 `SYLT`。
- 合并过程中会在扫描文件夹里创建：
  - `chapters_temp.ffmeta`
  - `concat_list_temp.txt`
- 归一化时会在系统临时目录创建中间文件。
- 正常结束或异常退出时，以上临时文件都会被清理；如果是强制终止进程，可能会残留，可以手动删除。
- 因此扫描文件夹需要**可写权限**。

### 注意事项

- 只扫描第一层 `.mp3`，子文件夹里的文件不会自动加入。
- 输出文件如果放在扫描文件夹内，下次运行会被自动排除，不会被当作输入。
- 章节边界按每个文件的时长累加，可能有几毫秒到几十毫秒的帧对齐偏差。
- 合并后的文件会变大。本播放器解析章节时需要把整个 MP3 读入内存，**超长的合并文件会加载较慢、占用较多内存**；合集特别大时，分成多个 part 反而更合适。
- 输出文件的封面图不会保留；标签来自脚本生成的 FFMetadata。
- `--title` 只是文件内部的标题，不会改变播放器左侧列表里显示的专辑名（列表名来自添加时的文件名或你手动重命名）。
- 如果 ffmpeg 报编码器不存在，检查安装是否带 `libmp3lame`，或用 `--normalize-codec` 指定其他可用编码器。

### 常见问题

- **`ModuleNotFoundError: No module named 'mutagen'`**：执行 `python -m pip install mutagen`。
- **`FileNotFoundError` 或提示找不到 ffmpeg**：确认 `ffmpeg -version` 能在当前终端运行；安装后需要重新打开终端。
- **合并时报 DTS/时长异常，或播放有杂音**：源文件编码参数不一致，改用 `--normalize always`。
- **播放器里没有章节**：确认输出文件确实包含 `CHAP`；如果是 `file://` 地址，浏览器可能阻止了本地读取，改用“从本机选择文件”验证。
- **歌词不显示**：本播放器不显示歌词；`SYLT` 需要用支持同步歌词的播放器查看。

## 数据与持久化

播放器使用以下 localStorage 键：

| 键 | 内容 |
|---|---|
| `mp3_album_player_tracks_v1` | 专辑文件数组（仅 `file:///` 等 URL 类型） |
| `mp3_album_player_volume` | 音量 0–100 |
| `mp3_album_player_mode` | 播放模式 |
| `mp3_album_player_theme` | `light` / `dark` |
| `mp3_album_player_sleep_finish` | 定时到点后是否播完当前歌曲 |
| `mp3_album_player_accent` | 自定义主题色 |
| `mp3_album_player_accent_recent` | 最近使用的主题色（最多 4 个） |

清除浏览器站点数据会同时清空播放列表和设置。

## 项目结构

```text
music-player.html   播放器（单文件，无构建）
merge.py            合并 MP3、写入章节和歌词的工具
README.md           本文档
LICENSE             MIT 许可证
doc.md              本地开发笔记（未纳入版本控制，部分内容可能滞后）
```

播放器没有构建步骤，修改 `music-player.html` 后刷新页面即可生效。

## 已知限制

- 播放器一次只加载一张专辑，没有跨专辑播放队列。
- 没有搜索、收藏、文件夹/合集分组功能。
- 章节解析会一次性读取整个 MP3；文件特别大时首次加载会慢。
- 本机文件导入使用 Blob URL，刷新后失效；只有 `file:///` 地址会持久化。
- 浏览器对本地文件的读取限制因浏览器/平台而异，`file://` 地址不保证在所有环境都能解析章节。
- 浏览器全屏 API 在部分设备（如 iPhone Safari）不可用，会提示不支持。
- `merge.py` 只处理 MP3，且不递归子文件夹。

## 许可证

MIT License，Copyright (c) 2026 ZHAqz。详见 [LICENSE](LICENSE)。
