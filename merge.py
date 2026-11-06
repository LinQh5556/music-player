import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.id3 import ID3, SYLT, Encoding


# ---------------- 音频信息读取（MP3 / FLAC） ----------------

_INFO_CACHE = {}


def _parse_track_number(value):
    if not value:
        return None
    num_part = str(value).split("/")[0].strip()
    return int(num_part) if num_part.isdigit() else None


def _load_info(path: Path):
    """读取标题、音轨号、时长和编码参数；读取失败返回 None。

    MP3 读 ID3 的 TIT2/TRCK；FLAC 读 Vorbis 注释的 title/tracknumber。
    params 为 (采样率, 声道数, 比特率kbps)，FLAC 为无损，不记录比特率（None）。
    """
    key = str(path)
    if key in _INFO_CACHE:
        return _INFO_CACHE[key]
    info = None
    try:
        if path.suffix.lower() == ".flac":
            flac = FLAC(path)
            titles = flac.get("title")
            numbers = flac.get("tracknumber")
            info = {
                "title": str(titles[0]) if titles else "",
                "track": _parse_track_number(numbers[0]) if numbers else None,
                "duration_ms": int(flac.info.length * 1000),
                "params": (flac.info.sample_rate, flac.info.channels, None),
            }
        else:
            audio = MP3(path)
            tit2 = audio.tags.get("TIT2") if audio.tags else None
            trck = audio.tags.get("TRCK") if audio.tags else None
            info = {
                "title": str(tit2) if tit2 else "",
                "track": _parse_track_number(trck),
                "duration_ms": int(audio.info.length * 1000),
                "params": (audio.info.sample_rate, audio.info.channels,
                           int(audio.info.bitrate // 1000)),
            }
    except Exception:
        info = None
    _INFO_CACHE[key] = info
    return info


def read_title_tag(path: Path) -> str:
    info = _load_info(path)
    return info["title"] if info else ""


def read_track_tag(path: Path):
    info = _load_info(path)
    return info["track"] if info else None


def sort_key_by_metadata(path: Path, source: str = "track"):
    """排序依据。
    source="track"   ：优先音轨号（MP3 TRCK / FLAC TRACKNUMBER），缺失时按文件名；
    source="filename"：始终按文件名（不区分大小写）。
    """
    if source == "filename":
        return (0, 0, path.name.lower())
    track = read_track_tag(path)
    if track is not None:
        return (0, track, path.name.lower())
    return (1, 0, path.name.lower())


def chapter_title_of(path: Path, source: str = "metadata") -> str:
    """返回章节标题。
    source="metadata"：优先用元数据标题（MP3 TIT2 / FLAC TITLE），缺失时回退文件名；
    source="filename"：始终用文件名（去掉扩展名）。
    """
    if source == "filename":
        return path.stem
    title = read_title_tag(path)
    return title if title else path.stem


def get_duration_ms(file_path: Path) -> int:
    info = _load_info(file_path)
    if info is None:
        print(f"错误：无法读取 {file_path.name} 的时长")
        sys.exit(1)
    return info["duration_ms"]


def generate_ffmetadata(chapters, output_path: Path, album_title="合辑"):
    lines = [";FFMETADATA1", f"title={album_title}", ""]
    for title, start, end in chapters:
        safe_title = (title.replace("\\", "\\\\")
                           .replace("=", "\\=")
                           .replace(";", "\\;"))
        lines.extend([
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start}",
            f"END={end}",
            f"title={safe_title}",
            ""
        ])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def generate_concat_list(audio_files, output_path: Path):
    def escape(p: Path) -> str:
        return p.as_posix().replace("'", "'\\''")
    lines = [f"file '{escape(f)}'" for f in audio_files]
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------- 子进程调用：统一处理编码 ----------------

def run_ffmpeg(cmd, check=True):
    """统一处理 ffmpeg 子进程调用，避免 Windows 下 GBK 解码错误。"""
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# ---------------- 统一编码参数 ----------------

def get_audio_params(path: Path):
    """返回 (sample_rate, channels, bitrate_kbps)；失败返回 None。"""
    info = _load_info(path)
    return info["params"] if info else None


def needs_normalization(audio_files) -> bool:
    """检查所有文件的 (采样率, 声道数, 平均比特率) 是否一致。"""
    params = [get_audio_params(p) for p in audio_files]
    if any(p is None for p in params):
        print("  警告：部分文件无法读取音频参数，将强制归一化")
        return True
    first = params[0]
    for p, param in zip(audio_files[1:], params[1:]):
        if param != first:
            return True
    return False


def infer_normalize_params(audio_files):
    """根据源文件推断归一化目标参数，返回 (bitrate_str, sample_rate, channels)。
    采样率/声道数取各源文件最大值；比特率取 MP3 源文件最大值，
    包含 FLAC 时默认按 320k 转码（FLAC 为无损，不记录比特率）。
    """
    params = [get_audio_params(p) for p in audio_files]
    params = [p for p in params if p is not None]
    has_flac = any(p.suffix.lower() == ".flac" for p in audio_files)
    bitrates = [p[2] for p in params if p[2]]
    if has_flac:
        bitrate = "320k"
    elif bitrates:
        bitrate = f"{max(bitrates)}k"
    else:
        bitrate = "192k"
    if not params:
        return (bitrate, 44100, 2)
    max_sr = max(p[0] for p in params)
    max_ch = max(p[1] for p in params)
    return (bitrate, max_sr, max_ch)


# MP3（libmp3lame）支持的采样率和最大声道数
MP3_SAMPLE_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)


def clamp_mp3_sample_rate(rate: int) -> int:
    """把采样率夹到 MP3 支持的最近档位（向下取）。"""
    if rate in MP3_SAMPLE_RATES:
        return rate
    lower = [r for r in MP3_SAMPLE_RATES if r < rate]
    return max(lower) if lower else min(MP3_SAMPLE_RATES)


def normalize_file(src: Path, dst: Path, bitrate: str,
                   sample_rate: int, channels: int, codec: str):
    """把单个 MP3 重新编码为统一参数。"""
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-map", "0:a",
        "-c:a", codec,
        "-b:a", bitrate,
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-map_metadata", "-1",
        str(dst),
    ]
    try:
        run_ffmpeg(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"  错误：归一化失败 {src.name}")
        print("STDERR:", e.stderr)
        raise
    except FileNotFoundError:
        print("错误：找不到 ffmpeg，请确认已安装并在 PATH 中")
        raise


def normalize_all(audio_files, temp_dir: Path, bitrate: str,
                  sample_rate: int, channels: int, codec: str):
    """把所有文件重新编码到 temp_dir，返回新路径列表（顺序与输入一致）。"""
    normalized = []
    total = len(audio_files)
    for idx, src in enumerate(audio_files, 1):
        dst = temp_dir / f"{idx:04d}_{src.name}.mp3"
        print(f"  归一化 {idx}/{total}: {src.name}")
        normalize_file(src, dst, bitrate, sample_rate, channels, codec)
        normalized.append(dst)
    return normalized


# ---------------- 歌词处理 ----------------

LRC_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
LRC_META_RE = re.compile(r"^\[(ti|ar|al|by|offset|length|re|ve|tool):", re.IGNORECASE)


def parse_lrc_file(lrc_path: Path):
    """解析 LRC 文件，返回 [(text, ms), ...]；解析失败返回 None。"""
    try:
        raw = lrc_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            raw = lrc_path.read_text(encoding="gbk")
        except Exception as e:
            print(f"  警告：无法读取 LRC {lrc_path.name} - {e}")
            return None
    except Exception as e:
        print(f"  警告：无法读取 LRC {lrc_path.name} - {e}")
        return None

    offset_ms = 0
    m = re.search(r"\[offset:\s*([+-]?\d+)\s*\]", raw, re.IGNORECASE)
    if m:
        offset_ms = int(m.group(1))

    result = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or LRC_META_RE.match(line):
            continue
        times = LRC_TIME_RE.findall(line)
        if not times:
            continue
        text = LRC_TIME_RE.sub("", line).strip()
        for mm, ss, frac in times:
            total_ms = int(mm) * 60_000 + int(ss) * 1000
            if frac:
                if len(frac) == 1:
                    total_ms += int(frac) * 100
                elif len(frac) == 2:
                    total_ms += int(frac) * 10
                else:
                    total_ms += int(frac)
            # LRC 的 offset 正数通常表示歌词提前显示，这里按“减 offset”处理
            total_ms = max(0, total_ms - offset_ms)
            result.append((text, total_ms))

    if not result:
        return None
    result.sort(key=lambda x: x[1])
    return result


def extract_lyrics_from_mp3(mp3_path: Path):
    """读取 MP3 内嵌的同步歌词 SYLT；返回 [(text, ms), ...] 或 None。"""
    try:
        tags = ID3(mp3_path)
    except Exception:
        return None

    for frame in tags.getall("SYLT"):
        if getattr(frame, "format", 2) != 2:
            print(f"  警告：{mp3_path.name} 的 SYLT 不是毫秒格式，已跳过")
            continue
        text = getattr(frame, "text", None)
        if not text:
            continue
        normalized = []
        for item in text:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                try:
                    normalized.append((str(item[0]), int(item[1])))
                except (TypeError, ValueError):
                    continue
        if normalized:
            normalized.sort(key=lambda x: x[1])
            return normalized
    return None


def extract_lyrics(mp3_path: Path):
    """优先读 MP3 内嵌 SYLT，其次读同名 .lrc；都找不到返回 None。"""
    lyrics = extract_lyrics_from_mp3(mp3_path)
    if lyrics:
        return lyrics
    for sibling in mp3_path.parent.iterdir():
        if (sibling.is_file()
                and sibling.suffix.lower() == ".lrc"
                and sibling.stem == mp3_path.stem):
            return parse_lrc_file(sibling)
    return None


def build_sylt_data(audio_files, chapters, with_markers=False):
    """把每首歌的歌词按章节起始时间偏移，拼成一条完整时间轴。"""
    all_data = []
    for audio_path, (title, start_ms, _end_ms) in zip(audio_files, chapters):
        lyrics = extract_lyrics(audio_path)
        if not lyrics:
            print(f"  跳过（无带时间戳的歌词）：{audio_path.name}")
            continue
        if with_markers:
            all_data.append((f"--- {title} ---", start_ms))
        for text, rel_ms in lyrics:
            all_data.append((text, start_ms + rel_ms))
        print(f"  已合并歌词：{audio_path.name} -> {len(lyrics)} 行，偏移 +{start_ms} ms")
    return all_data


def write_sylt_to_output(output_path: Path, sylt_data, lang="chi"):
    """把完整的歌词时间轴写入输出 MP3 的 SYLT 帧。"""
    if not sylt_data:
        print("没有可写入的同步歌词。")
        return
    if len(lang) != 3:
        print(f"  警告：语言代码 {lang!r} 不是 3 字符，改用 'und'")
        lang = "und"

    try:
        tags = ID3(output_path)
    except Exception:
        tags = ID3()

    try:
        frame = SYLT(
            encoding=Encoding.UTF16,   # v2.3 兼容性更稳
            lang=lang,
            format=2,                  # 时间戳单位为毫秒
            type=1,                    # 1 = 歌词
            desc="",
            text=sylt_data,
        )
        tags.setall("SYLT", [frame])
        tags.save(output_path, v2_version=3)
        print(f"已写入 {len(sylt_data)} 行 SYLT 到 {output_path.name}（lang={lang}）")
    except Exception as e:
        print(f"  错误：写入 SYLT 失败 - {e}")


# ---------------- 命令行入口 ----------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="把文件夹下的 MP3/FLAC 排序后合并为一个带章节帧的 MP3，"
                    "并可选地把每首歌的歌词按章节时间偏移合并成一条 SYLT 同步歌词。"
                    "包含 FLAC 时会先转码为 MP3（章节写入 ID3 CHAP，网页播放器可直接识别）；"
                    "合并前可自动统一源文件的编码参数，避免比特率/采样率不一致导致合并失败。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python merge.py D:\\music 合辑.mp3
  python merge.py ./music ./out/合辑.mp3 --title "我的精选集"
  python merge.py ./music 合辑.mp3 --sort-by filename
  python merge.py ./music 合辑.mp3 --chapter-markers --lyrics-lang chi
  python merge.py ./music 合辑.mp3 --no-lyrics
  python merge.py ./music 合辑.mp3 --chapter-title-source filename
  python merge.py ./music 合辑.mp3 --normalize always --normalize-bitrate 128k
  python merge.py ./music 合辑.mp3 --normalize never
  python merge.py ./music 合辑.mp3 --normalize always --normalize-channels 1 --normalize-bitrate 96k
  python merge.py D:\\flacdir 合辑.mp3 --formats flac
"""
    )
    parser.add_argument("folder", help="要扫描音频文件的文件夹路径")
    parser.add_argument("output", help="输出文件名；不带 .mp3 后缀会自动补上")
    parser.add_argument("--title", default="合辑", help="合并后文件的全局标题（默认：合辑）")
    parser.add_argument("--formats", default="mp3,flac",
                        help="参与合并的音频格式，逗号分隔（默认 mp3,flac）")
    parser.add_argument("--lyrics-lang", default="chi",
                        help="写入 SYLT 的语言代码（ISO-639-2，默认 chi）")
    parser.add_argument("--chapter-markers", action="store_true",
                        help="在每章歌词前插入一行章节标题（便于在歌词中看到分段）")
    parser.add_argument("--no-lyrics", action="store_true",
                        help="跳过歌词处理，只合并音频与章节")
    parser.add_argument(
        "--chapter-title-source",
        choices=["metadata", "filename"],
        default="metadata",
        help="章节标题命名来源：metadata=元数据标题（MP3 TIT2 / FLAC TITLE，默认，缺失时回退文件名），"
             "filename=文件名（去扩展名）"
    )
    parser.add_argument(
        "--sort-by",
        choices=["track", "filename"],
        default="track",
        help="合并排序方式：track=音轨号优先（MP3 TRCK / FLAC TRACKNUMBER，默认，缺失时按文件名），"
             "filename=始终按文件名"
    )
    parser.add_argument(
        "--normalize",
        choices=["auto", "always", "never"],
        default="auto",
        help="合并前是否统一源文件编码参数：auto=参数不一致时才归一化（默认），"
             "always=总是归一化，never=从不归一化（直接流复制）"
    )
    parser.add_argument(
        "--normalize-bitrate", default=None,
        help="归一化目标比特率（默认自动取源文件最大值，如 320k；"
             "也可显式写 128k / 256k / 320k）"
    )
    parser.add_argument(
        "--normalize-sample-rate", type=int, default=None,
        help="归一化目标采样率（默认自动取源文件最大值，如 44100）"
    )
    parser.add_argument(
        "--normalize-channels", type=int, default=None,
        help="归一化目标声道数（默认自动取源文件最大值，如 2；"
             "有声书可显式指定 1）"
    )
    parser.add_argument(
        "--normalize-codec", default="libmp3lame",
        help="归一化使用的音频编码器（默认 libmp3lame）"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"错误：文件夹不存在 -> {folder}")
        sys.exit(1)

    output_arg = Path(args.output).expanduser()
    if output_arg.suffix.lower() != ".mp3":
        output_arg = output_arg.with_suffix(".mp3")
    output_path = output_arg.resolve() if output_arg.is_absolute() else (folder / output_arg).resolve()

    if output_path.parent != folder and not output_path.parent.is_dir():
        print(f"错误：输出目录不存在 -> {output_path.parent}")
        sys.exit(1)

    formats = {"." + s.strip().lower().lstrip(".") for s in args.formats.split(",") if s.strip()}
    if not formats:
        formats = {".mp3", ".flac"}

    audio_files = [
        p for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() in formats
        and p.resolve() != output_path
    ]

    if not audio_files:
        print(f"错误：在 {folder} 下没有找到音频文件（{', '.join(sorted(formats))}）")
        sys.exit(1)

    audio_files.sort(key=lambda p: sort_key_by_metadata(p, args.sort_by))
    has_flac = any(p.suffix.lower() == ".flac" for p in audio_files)

    print(f"\n文件夹: {folder}")
    print(f"输出文件: {output_path}")
    print(f"音频格式: {', '.join(ext.lstrip('.').upper() for ext in sorted(formats))}")
    print(f"排序方式: {args.sort_by}")
    print(f"章节标题来源: {args.chapter_title_source}")
    if args.sort_by == "filename":
        print("将按以下顺序合并（按文件名）：")
    else:
        print("将按以下顺序合并（依据音轨号，缺失时按文件名）：")
    for i, p in enumerate(audio_files, 1):
        track = read_track_tag(p)
        kind = "FLAC" if p.suffix.lower() == ".flac" else "MP3"
        if args.sort_by == "filename":
            source = "按文件名"
        else:
            source = f"音轨号 {track}" if track is not None else "无音轨号，按文件名"
        print(f"  {i}. {p.name}  [{kind} / {source}]  -> 章节名: "
              f"{chapter_title_of(p, args.chapter_title_source)}")

    temp_dir = None
    metadata_path = folder / "chapters_temp.ffmeta"
    concat_list_path = folder / "concat_list_temp.txt"

    try:
        # ---- 决定是否归一化（包含 FLAC 时必须转码为 MP3） ----
        if args.normalize == "always":
            use_normalize = True
        elif args.normalize == "never":
            if has_flac:
                print("\n警告：包含 FLAC 文件，无法直接流复制合并，已改为转码。")
                use_normalize = True
            else:
                use_normalize = False
        else:
            use_normalize = has_flac or needs_normalization(audio_files)

        if use_normalize:
            inferred_br, inferred_sr, inferred_ch = infer_normalize_params(audio_files)
            bitrate = args.normalize_bitrate or inferred_br
            sample_rate = args.normalize_sample_rate or inferred_sr
            channels = args.normalize_channels or inferred_ch

            clamped_rate = clamp_mp3_sample_rate(sample_rate)
            if clamped_rate != sample_rate:
                print(f"  警告：MP3 不支持 {sample_rate}Hz 采样率，已改为 {clamped_rate}Hz")
                sample_rate = clamped_rate
            if channels > 2:
                print(f"  警告：MP3 最多支持 2 声道，已把 {channels} 声道改为 2")
                channels = 2

            print(f"\n统一编码参数：{bitrate} / "
                  f"{sample_rate}Hz / {channels}ch / {args.normalize_codec}")
            if args.normalize_bitrate is None:
                print(f"  （比特率自动确定：{bitrate}）")
            if args.normalize_sample_rate is None:
                print(f"  （采样率自动取源文件最大值：{sample_rate}Hz）")
            if args.normalize_channels is None:
                print(f"  （声道数自动取源文件最大值：{channels}）")
            if has_flac:
                print("  （包含 FLAC：全部转码为 MP3，章节写入 ID3 CHAP）")

            temp_dir = Path(tempfile.mkdtemp(prefix="mp3_merge_norm_"))
            merge_files = normalize_all(
                audio_files, temp_dir,
                bitrate=bitrate,
                sample_rate=sample_rate,
                channels=channels,
                codec=args.normalize_codec,
            )
        else:
            print("\n源文件编码参数一致，直接流复制合并。")
            merge_files = audio_files

        # ---- 计算章节（基于实际参与合并的文件时长） ----
        chapters = []
        current_start = 0
        for src_path, merge_path in zip(audio_files, merge_files):
            duration_ms = get_duration_ms(merge_path)
            current_end = current_start + duration_ms
            chapters.append((
                chapter_title_of(src_path, args.chapter_title_source),
                current_start,
                current_end,
            ))
            current_start = current_end

        generate_ffmetadata(chapters, metadata_path, args.title)
        generate_concat_list(merge_files, concat_list_path)

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list_path),
            "-i", str(metadata_path),
            "-map", "0:a",
            "-map_metadata", "1",
            "-map_chapters", "1",
            "-c", "copy",
            str(output_path)
        ]

        print("\n正在执行 FFmpeg 命令：")
        print("  " + " ".join(cmd))
        try:
            run_ffmpeg(cmd, check=True)
            print(f"\n合并完成，输出文件：{output_path}")
        except subprocess.CalledProcessError as e:
            print("\nFFmpeg 执行失败：")
            print("STDOUT:", e.stdout)
            print("STDERR:", e.stderr)
            sys.exit(1)

        # ---- 合并歌词为 SYLT ----
        if args.no_lyrics:
            return
        print("\n正在处理歌词（SYLT）...")
        sylt_data = build_sylt_data(audio_files, chapters,
                                    with_markers=args.chapter_markers)
        write_sylt_to_output(output_path, sylt_data, lang=args.lyrics_lang)
    finally:
        metadata_path.unlink(missing_ok=True)
        concat_list_path.unlink(missing_ok=True)
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
