import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, SYLT, Encoding


# ---------------- ID3 读取 ----------------

def read_title_tag(mp3_path: Path) -> str:
    try:
        audio = MP3(mp3_path)
        if audio.tags is None:
            return ""
        tit2 = audio.tags.get("TIT2")
        return str(tit2) if tit2 else ""
    except Exception:
        return ""


def read_track_tag(mp3_path: Path):
    try:
        audio = MP3(mp3_path)
        if audio.tags is None:
            return None
        trck = audio.tags.get("TRCK")
        if not trck:
            return None
        num_part = str(trck).split("/")[0].strip()
        return int(num_part) if num_part.isdigit() else None
    except Exception:
        return None


def sort_key_by_metadata(path: Path):
    title = read_title_tag(path)
    m = re.search(r"#(\d+)", title)
    if m:
        return (0, int(m.group(1)), path.name.lower())
    track = read_track_tag(path)
    if track is not None:
        return (1, track, path.name.lower())
    return (2, 0, path.name.lower())


def chapter_title_of(path: Path) -> str:
    title = read_title_tag(path)
    return title if title else path.stem


def get_mp3_duration_ms(file_path: Path) -> int:
    try:
        audio = MP3(file_path)
        return int(audio.info.length * 1000)
    except Exception as e:
        print(f"错误：无法读取 {file_path} 的时长 - {e}")
        sys.exit(1)


def get_mp3_audio_params(mp3_path: Path):
    """返回 (sample_rate, channels)；失败时回退到 (44100, 2)。"""
    try:
        audio = MP3(mp3_path)
        return audio.info.sample_rate, audio.info.channels
    except Exception:
        return 44100, 2


# ---------------- 静音生成 ----------------

def create_silence_mp3(output_path: Path, duration_s: float,
                       sample_rate: int, channels: int):
    """用 anullsrc 生成一个静音 MP3，参数尽量匹配源文件。"""
    channel_layout = "mono" if channels == 1 else "stereo"
    base_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r={sample_rate}:cl={channel_layout}",
        "-t", f"{duration_s:.3f}",
        "-ar", str(sample_rate),
        "-ac", str(channels),
    ]
    # 优先指定 libmp3lame；失败再让 ffmpeg 按扩展名自动选择
    for extra in (["-c:a", "libmp3lame", "-q:a", "9"], []):
        cmd = base_cmd + extra + [str(output_path)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return
        except FileNotFoundError:
            print("错误：找不到 ffmpeg，请先安装并加入 PATH")
            sys.exit(1)
        except subprocess.CalledProcessError:
            continue
    print("错误：生成静音 MP3 失败，请确认 ffmpeg 支持 MP3 编码（libmp3lame）")
    sys.exit(1)


# ---------------- 元数据 / concat 列表 ----------------

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


def generate_concat_list(mp3_files, output_path: Path, silence_path: Path = None):
    """生成 concat 列表；若提供 silence_path，则在每两首歌之间插入该静音文件。"""
    def escape(p: Path) -> str:
        return p.as_posix().replace("'", "'\\''")

    lines = []
    for i, f in enumerate(mp3_files):
        lines.append(f"file '{escape(f)}'")
        if silence_path is not None and i < len(mp3_files) - 1:
            lines.append(f"file '{escape(silence_path)}'")
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------- 歌词处理 ----------------

LRC_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
LRC_META_RE = re.compile(r"^\[(ti|ar|al|by|offset|length|re|ve|tool):", re.IGNORECASE)


def parse_lrc_file(lrc_path: Path):
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
            total_ms = max(0, total_ms - offset_ms)
            result.append((text, total_ms))

    if not result:
        return None
    result.sort(key=lambda x: x[1])
    return result


def extract_lyrics_from_mp3(mp3_path: Path):
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
    lyrics = extract_lyrics_from_mp3(mp3_path)
    if lyrics:
        return lyrics
    for sibling in mp3_path.parent.iterdir():
        if (sibling.is_file()
                and sibling.suffix.lower() == ".lrc"
                and sibling.stem == mp3_path.stem):
            return parse_lrc_file(sibling)
    return None


def build_sylt_data(mp3_files, chapters, with_markers=False):
    all_data = []
    for mp3_path, (title, start_ms, _end_ms) in zip(mp3_files, chapters):
        lyrics = extract_lyrics(mp3_path)
        if not lyrics:
            print(f"  跳过（无带时间戳的歌词）：{mp3_path.name}")
            continue
        if with_markers:
            all_data.append((f"--- {title} ---", start_ms))
        for text, rel_ms in lyrics:
            all_data.append((text, start_ms + rel_ms))
        print(f"  已合并歌词：{mp3_path.name} -> {len(lyrics)} 行，偏移 +{start_ms} ms")
    return all_data


def write_sylt_to_output(output_path: Path, sylt_data, lang="chi"):
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
            encoding=Encoding.UTF16,
            lang=lang,
            format=2,
            type=1,
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
        description="把文件夹下的 MP3 按 ID3 元数据中的 # 数字（或音轨号）排序后，"
                    "合并为一个带章节帧的 MP3；可在相邻曲目间插入静音分隔，"
                    "并可把每首歌的歌词按章节时间偏移合并成一条 SYLT 同步歌词。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python merge.py D:\\music 合辑.mp3
  python merge.py ./music ./out/合辑.mp3 --title "我的精选集"
  python merge.py ./music 合辑.mp3 --gap 0.5 --chapter-markers --lyrics-lang chi
  python merge.py ./music 合辑.mp3 --gap 0          # 不插入静音
  python merge.py ./music 合辑.mp3 --no-lyrics      # 不处理歌词
"""
    )
    parser.add_argument("folder", help="要扫描 MP3 的文件夹路径")
    parser.add_argument("output", help="输出文件名；不带 .mp3 后缀会自动补上")
    parser.add_argument("--title", default="合辑", help="合并后文件的全局标题（默认：合辑）")
    parser.add_argument("--gap", type=float, default=0.5,
                        help="相邻曲目之间的静音间隔秒数（默认 0.5；设为 0 则禁用）")
    parser.add_argument("--lyrics-lang", default="chi",
                        help="写入 SYLT 的语言代码（ISO-639-2，默认 chi）")
    parser.add_argument("--chapter-markers", action="store_true",
                        help="在每章歌词前插入一行章节标题")
    parser.add_argument("--no-lyrics", action="store_true",
                        help="跳过歌词处理，只合并音频与章节")
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

    mp3_files = [
        p for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() == ".mp3"
        and p.resolve() != output_path
    ]

    if not mp3_files:
        print(f"错误：在 {folder} 下没有找到 MP3 文件")
        sys.exit(1)

    mp3_files.sort(key=sort_key_by_metadata)

    print(f"\n文件夹: {folder}")
    print(f"输出文件: {output_path}")
    print("将按以下顺序合并（依据 ID3 元数据中的 # 数字 / 音轨号）：")
    for i, p in enumerate(mp3_files, 1):
        title = read_title_tag(p)
        m = re.search(r"#(\d+)", title)
        track = read_track_tag(p)
        if m:
            source = f"标题 #{m.group(1)}"
        elif track is not None:
            source = f"音轨号 {track}"
        else:
            source = "无 # / 无音轨号"
        print(f"  {i}. {p.name}  [{source}]  -> 章节名: {chapter_title_of(p)}")

    # ---- 生成间隔静音 ----
    gap_s = args.gap
    silence_tmpdir = None
    silence_path = None
    gap_ms = 0
    if gap_s > 0 and len(mp3_files) > 1:
        sample_rate, channels = get_mp3_audio_params(mp3_files[0])
        silence_tmpdir = Path(tempfile.mkdtemp(prefix="mp3gap_"))
        silence_path = silence_tmpdir / "silence.mp3"
        print(f"\n正在生成 {gap_s}s 静音分隔音频（{sample_rate}Hz / {channels}ch）...")
        create_silence_mp3(silence_path, gap_s, sample_rate, channels)
        gap_ms = get_mp3_duration_ms(silence_path)
        print(f"  静音文件实际时长：{gap_ms} ms（用于章节/歌词时间轴对齐）")
    elif gap_s > 0:
        print("\n只有 1 个 MP3 文件，跳过静音分隔。")

    try:
        # ---- 计算章节（计入每段 gap）----
        chapters = []
        current_start = 0
        for i, mp3_path in enumerate(mp3_files):
            duration_ms = get_mp3_duration_ms(mp3_path)
            current_end = current_start + duration_ms
            chapters.append((chapter_title_of(mp3_path), current_start, current_end))
            current_start = current_end
            if i < len(mp3_files) - 1:
                current_start += gap_ms

        metadata_path = folder / "chapters_temp.ffmeta"
        concat_list_path = folder / "concat_list_temp.txt"
        generate_ffmetadata(chapters, metadata_path, args.title)
        generate_concat_list(mp3_files, concat_list_path, silence_path)

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
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"\n合并完成，输出文件：{output_path}")
        except subprocess.CalledProcessError as e:
            print("\nFFmpeg 执行失败：")
            print("STDOUT:", e.stdout)
            print("STDERR:", e.stderr)
            sys.exit(1)
        finally:
            metadata_path.unlink(missing_ok=True)
            concat_list_path.unlink(missing_ok=True)

        # ---- 合并歌词为 SYLT ----
        if args.no_lyrics:
            return
        print("\n正在处理歌词（SYLT）...")
        sylt_data = build_sylt_data(mp3_files, chapters,
                                    with_markers=args.chapter_markers)
        write_sylt_to_output(output_path, sylt_data, lang=args.lyrics_lang)
    finally:
        if silence_tmpdir is not None:
            shutil.rmtree(silence_tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()