import argparse
import subprocess
import re
import sys
from pathlib import Path
from mutagen.mp3 import MP3


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


def generate_concat_list(mp3_files, output_path: Path):
    def escape(p: Path) -> str:
        return p.as_posix().replace("'", "'\\''")
    lines = [f"file '{escape(f)}'" for f in mp3_files]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(
        description="把文件夹下的 MP3 按 ID3 元数据中的 # 数字（或音轨号）排序后，合并为一个带章节帧的 MP3。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python merge_with_chapters.py D:\\music 合辑.mp3
  python merge_with_chapters.py ./music ./out/合辑.mp3 --title "我的精选集"
"""
    )
    parser.add_argument("folder", help="要扫描 MP3 的文件夹路径")
    parser.add_argument("output", help="输出文件名；不带 .mp3 后缀会自动补上")
    parser.add_argument("--title", default="合辑", help="合并后文件的全局标题（默认：合辑）")
    return parser.parse_args()


def main():
    args = parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"错误：文件夹不存在 -> {folder}")
        sys.exit(1)

    # 处理输出路径：无 .mp3 后缀自动补；无目录部分则放在 folder 内
    output_arg = Path(args.output).expanduser()
    if output_arg.suffix.lower() != ".mp3":
        output_arg = output_arg.with_suffix(".mp3")
    output_path = output_arg.resolve() if output_arg.is_absolute() else (folder / output_arg).resolve()

    if output_path.parent != folder and not output_path.parent.is_dir():
        print(f"错误：输出目录不存在 -> {output_path.parent}")
        sys.exit(1)

    # 扫描 MP3，排除输出文件本身
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

    # 计算章节
    chapters = []
    current_start = 0
    for mp3_path in mp3_files:
        duration_ms = get_mp3_duration_ms(mp3_path)
        current_end = current_start + duration_ms
        chapters.append((chapter_title_of(mp3_path), current_start, current_end))
        current_start = current_end

    metadata_path = folder / "chapters_temp.ffmeta"
    concat_list_path = folder / "concat_list_temp.txt"
    generate_ffmetadata(chapters, metadata_path, args.title)
    generate_concat_list(mp3_files, concat_list_path)

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


if __name__ == "__main__":
    main()