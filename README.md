# music-player

本地 MP3 专辑播放器，包含三部分：

- `music-player.html`：单文件网页播放器，无需安装任何依赖，用浏览器打开即可使用。
- `merge.py`：把一个文件夹里的多个 MP3 合并成一个带章节的单文件 MP3，配合网页播放器使用。
- `merge_gui.py`：`merge.py` 的桌面图形界面（可选，不想敲命令行时用）。

## 使用方法

### 网页播放器

直接用浏览器打开 `music-player.html`，手机和桌面浏览器都可以。

添加音频有两种方式：

- 输入 `file:///` 地址保存，地址会持久化到浏览器本地，下次打开还在；
- 从本机选择文件，属于临时播放，关闭页面后失效。

点击左侧专辑文件后会自动解析 MP3 内嵌的 CHAP 章节帧，歌曲列表显示在右侧；没有章节信息的文件按单个音频播放。长按专辑条目可以拖动排序，条目右侧的 ⋯ 菜单可以重命名、删除。

### merge.py

依赖 Python 3、mutagen 和 ffmpeg（ffmpeg 需在 PATH 中）。

```bash
pip install mutagen
python merge.py D:\music 合辑.mp3
```

脚本会按顺序合并文件夹下的 MP3，并在输出文件里写入章节帧。常用参数（详见 `python merge.py --help`）：

- `--sort-by track|filename`：按 ID3 音轨号排序（默认），或按文件名排序
- `--chapter-title-source metadata|filename`：章节标题取 ID3 标题还是文件名
- `--no-lyrics`：跳过歌词处理
- `--normalize auto|always|never`：源文件比特率/采样率不一致时是否先统一编码
- `--title`：合并后文件的标题

如果每首歌有内嵌 SYLT 歌词或同名 `.lrc` 文件，脚本会按章节时间偏移合并成一条同步歌词写入输出文件。

### merge_gui.py（图形界面）

依赖与 `merge.py` 相同（tkinter 为 Python 自带）。

```bash
python merge_gui.py
```

运行后选择 MP3 文件夹，输出文件会自动填为文件夹下的 `合辑.mp3`，点「开始合并」即可，日志区域实时显示脚本输出，完成后可一键打开输出位置。排序、章节标题、归一化、歌词等选项与命令行参数一一对应。

用 `pythonw merge_gui.py` 启动可以不显示控制台窗口。

## 主要功能

- 播放模式：顺序播放、列表循环、单曲循环、随机播放
- 定时暂停（15 / 30 / 60 / 90 分钟），可选到点后播完当前歌曲再暂停
- 深色模式、自定义主题颜色
- 播放卡片可放大为全屏界面
- 按住音量按钮左右滑动调节音量
- 支持系统媒体通知控制（Media Session），播放时保持屏幕常亮

## 数据说明

所有设置和播放数据只保存在本机浏览器的 localStorage 中，不会上传。

## 已知问题和待完善功能

- 放大界面简陋
- 没有收藏功能
