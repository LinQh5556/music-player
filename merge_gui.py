# -*- coding: utf-8 -*-
"""MP3 专辑合并工具 —— merge.py 的桌面图形界面。

依赖与 merge.py 相同：Python 3（自带 tkinter）、mutagen、ffmpeg。
运行：python merge_gui.py   （或 pythonw merge_gui.py，不显示控制台窗口）
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
MERGE_SCRIPT = str(BASE_DIR / "merge.py")

ACCENT = "#4a9eff"
ACCENT_HOVER = "#3f8de6"
ACCENT_OFF = "#b7d4f5"
BG = "#f5f6f8"
FG = "#222222"
MUTED = "#7a8190"
BORDER = "#dfe3ea"
LOG_BG = "#ffffff"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

SORT_OPTIONS = [("按音轨号（缺失时按文件名）", "track"), ("按文件名", "filename")]
CHAPTER_OPTIONS = [("ID3 标题（缺失时用文件名）", "metadata"), ("文件名", "filename")]
NORMALIZE_OPTIONS = [
    ("自动（参数不一致时才归一化）", "auto"),
    ("总是归一化", "always"),
    ("从不（直接流复制）", "never"),
]
SORT_MAP = dict(SORT_OPTIONS)
CHAPTER_MAP = dict(CHAPTER_OPTIONS)
NORMALIZE_MAP = dict(NORMALIZE_OPTIONS)


def make_dpi_aware():
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MP3 专辑合并工具")
        self.configure(bg=BG)
        self.minsize(640, 540)

        win_w, win_h = 700, 620
        self.update_idletasks()
        x = (self.winfo_screenwidth() - win_w) // 2
        y = max(0, (self.winfo_screenheight() - win_h) // 3)
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")

        self.proc = None
        self.cancelled = False
        self.log_queue = queue.Queue()
        self.output_auto = False
        self.advanced_shown = False
        self.current_output = ""

        family = "Microsoft YaHei UI" if os.name == "nt" else "TkDefaultFont"
        self.f_title = tkfont.Font(family=family, size=14, weight="bold")
        self.f_btn = tkfont.Font(family=family, size=10, weight="bold")
        self.f_body = tkfont.Font(family=family, size=9)
        self.f_small = tkfont.Font(family=family, size=8)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(80, self._poll_log)

        # 供自动化测试使用：MERGE_GUI_REPORT=1 打印窗口位置并置顶，MERGE_GUI_AUTOCLOSE=毫秒 自动关闭
        if os.environ.get("MERGE_GUI_REPORT"):
            self.attributes("-topmost", True)
            self.after(600, self._report_geom)
        autoclose = os.environ.get("MERGE_GUI_AUTOCLOSE")
        if autoclose and autoclose.isdigit():
            self.after(int(autoclose), self.destroy)

    # ---------------- UI ----------------

    def _build(self):
        self.status = tk.Label(self, text="就绪", bg=BG, fg=MUTED, font=self.f_small, anchor="w")
        self.status.pack(side="bottom", fill="x", padx=20, pady=(6, 10))

        content = tk.Frame(self, bg=BG)
        content.pack(fill="both", expand=True, padx=20, pady=(16, 0))

        head = tk.Frame(content, bg=BG)
        head.pack(fill="x", pady=(0, 12))
        tk.Label(head, text="MP3 专辑合并", bg=BG, fg=FG, font=self.f_title).pack(anchor="w")
        tk.Label(head, text="把一个文件夹里的多个 MP3 合并为一个带章节的单文件",
                 bg=BG, fg=MUTED, font=self.f_body).pack(anchor="w", pady=(2, 0))

        form = tk.Frame(content, bg=BG)
        form.pack(fill="x")
        for col in (1, 3):
            form.columnconfigure(col, weight=1)

        def rlabel(row, text, col=0):
            tk.Label(form, text=text, bg=BG, fg=MUTED, font=self.f_body,
                     width=8, anchor="e").grid(row=row, column=col, sticky="e", padx=(0, 8), pady=4)

        # 文件夹
        self.folder_var = tk.StringVar()
        rlabel(0, "文件夹")
        ttk.Entry(form, textvariable=self.folder_var).grid(
            row=0, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Button(form, text="浏览", width=6, command=self.choose_folder).grid(
            row=0, column=4, sticky="e", padx=(8, 0), pady=4)
        self.mp3_count = tk.Label(form, text="", bg=BG, fg=MUTED, font=self.f_small)
        self.mp3_count.grid(row=0, column=5, sticky="w", padx=(8, 0))
        self.folder_var.trace_add("write", self._update_count)

        # 输出文件
        self.out_var = tk.StringVar()
        rlabel(1, "输出文件")
        ttk.Entry(form, textvariable=self.out_var).grid(
            row=1, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Button(form, text="选择", width=6, command=self.choose_output).grid(
            row=1, column=4, sticky="e", padx=(8, 0), pady=4)

        # 专辑标题
        self.title_var = tk.StringVar(value="合辑")
        rlabel(2, "专辑标题")
        ttk.Entry(form, textvariable=self.title_var).grid(
            row=2, column=1, columnspan=3, sticky="ew", pady=4)

        # 排序方式 / 章节标题
        self.sort_var = tk.StringVar(value=SORT_OPTIONS[0][0])
        self.chapter_var = tk.StringVar(value=CHAPTER_OPTIONS[0][0])
        rlabel(3, "排序方式")
        ttk.Combobox(form, textvariable=self.sort_var, values=[o[0] for o in SORT_OPTIONS],
                     state="readonly").grid(row=3, column=1, sticky="ew", pady=4)
        rlabel(3, "章节标题", col=2)
        ttk.Combobox(form, textvariable=self.chapter_var, values=[o[0] for o in CHAPTER_OPTIONS],
                     state="readonly").grid(row=3, column=3, sticky="ew", pady=4)

        # 编码归一化
        self.norm_var = tk.StringVar(value=NORMALIZE_OPTIONS[0][0])
        rlabel(4, "编码归一化")
        ttk.Combobox(form, textvariable=self.norm_var, values=[o[0] for o in NORMALIZE_OPTIONS],
                     state="readonly").grid(row=4, column=1, sticky="ew", pady=4)
        self.adv_link = tk.Label(form, text="归一化参数 ▸", bg=BG, fg=ACCENT,
                                 font=self.f_body, cursor="hand2")
        self.adv_link.grid(row=4, column=2, columnspan=2, sticky="w", padx=(12, 0))
        self.adv_link.bind("<Button-1>", lambda e: self.toggle_advanced())

        # 归一化参数（默认收起）
        self.adv = tk.Frame(form, bg=BG)
        self.adv.grid(row=5, column=0, columnspan=6, sticky="ew", padx=(36, 0), pady=(0, 4))
        self.bitrate_var = tk.StringVar()
        self.sr_var = tk.StringVar()
        self.ch_var = tk.StringVar()
        self.codec_var = tk.StringVar()

        def mini(label, var, width):
            box = tk.Frame(self.adv, bg=BG)
            box.pack(side="left", padx=(0, 14))
            tk.Label(box, text=label, bg=BG, fg=MUTED, font=self.f_small).pack(anchor="w")
            ttk.Entry(box, textvariable=var, width=width).pack(anchor="w", pady=(2, 0))

        mini("比特率（如 320k）", self.bitrate_var, 8)
        mini("采样率（如 44100）", self.sr_var, 8)
        mini("声道数（如 2）", self.ch_var, 6)
        mini("编码器", self.codec_var, 12)
        tk.Label(self.adv, text="留空则自动取各源文件中的最大值", bg=BG, fg=MUTED,
                 font=self.f_small).pack(side="left", pady=(14, 0))
        self.adv.grid_remove()

        # 歌词选项
        lyr = tk.Frame(content, bg=BG)
        lyr.pack(fill="x", pady=(8, 0))
        self.lyrics_var = tk.IntVar(value=1)
        self.markers_var = tk.IntVar(value=0)
        self.lang_var = tk.StringVar(value="chi")

        def check(parent, text, var):
            return tk.Checkbutton(parent, text=text, variable=var, bg=BG, fg=FG,
                                  font=self.f_body, activebackground=BG, activeforeground=FG,
                                  highlightthickness=0, anchor="w")

        check(lyr, "合并同步歌词（内嵌 SYLT 或同名 .lrc）", self.lyrics_var).pack(side="left")
        check(lyr, "歌词中插入章节标题", self.markers_var).pack(side="left", padx=(16, 0))
        tk.Label(lyr, text="语言", bg=BG, fg=MUTED, font=self.f_body).pack(side="left", padx=(16, 4))
        ttk.Entry(lyr, textvariable=self.lang_var, width=5).pack(side="left")

        tk.Frame(content, bg=BORDER, height=1).pack(fill="x", pady=(12, 0))

        # 操作按钮
        btns = tk.Frame(content, bg=BG)
        btns.pack(fill="x", pady=12)
        self.start_btn = tk.Button(btns, text="开始合并", command=self.start_merge, font=self.f_btn,
                                   bg=ACCENT, fg="#ffffff", activebackground=ACCENT_HOVER,
                                   activeforeground="#ffffff", relief="flat", bd=0,
                                   padx=24, pady=7, cursor="hand2", disabledforeground="#ffffff")
        self.start_btn.pack(side="left")
        self.start_btn.bind("<Enter>", lambda e: self._hover(True))
        self.start_btn.bind("<Leave>", lambda e: self._hover(False))
        self.cancel_btn = ttk.Button(btns, text="取消", command=self.cancel_merge, state="disabled")
        self.cancel_btn.pack(side="left", padx=(10, 0))
        self.open_btn = ttk.Button(btns, text="打开输出位置", command=self.open_output, state="disabled")
        self.open_btn.pack(side="right")

        # 日志
        logwrap = tk.Frame(content, bg=BORDER)
        logwrap.pack(fill="both", expand=True)
        inner = tk.Frame(logwrap, bg=LOG_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.log = tk.Text(inner, bg=LOG_BG, fg="#333333", relief="flat", bd=0, wrap="word",
                           font=self.f_body, state="disabled", insertwidth=0, padx=10, pady=8)
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("muted", foreground="#9aa1ad")
        self._set_log_text("运行 merge.py 的输出会显示在这里。", "muted")

    def _report_geom(self):
        self.update_idletasks()
        print(f"GEOM {self.winfo_rootx()} {self.winfo_rooty()} {self.winfo_width()} {self.winfo_height()}",
              flush=True)

    # ---------------- 选择路径 ----------------

    def choose_folder(self):
        d = filedialog.askdirectory(parent=self, title="选择 MP3 文件夹",
                                    initialdir=self.folder_var.get().strip() or str(Path.home()))
        if not d:
            return
        self.folder_var.set(d)
        if self.output_auto or not self.out_var.get().strip():
            self.out_var.set(str(Path(d) / "合辑.mp3"))
            self.output_auto = True

    def choose_output(self):
        f = filedialog.asksaveasfilename(parent=self, title="选择输出文件",
                                         defaultextension=".mp3",
                                         filetypes=[("MP3 文件", "*.mp3"), ("所有文件", "*.*")],
                                         initialfile="合辑.mp3",
                                         initialdir=self.folder_var.get().strip() or str(Path.home()))
        if not f:
            return
        self.out_var.set(f)
        self.output_auto = False

    def _update_count(self, *_):
        folder = self.folder_var.get().strip()
        n = 0
        if folder and Path(folder).is_dir():
            try:
                n = sum(1 for p in Path(folder).iterdir()
                        if p.is_file() and p.suffix.lower() == ".mp3")
            except OSError:
                n = 0
        self.mp3_count.config(text=f"共 {n} 个 MP3" if folder else "")

    def toggle_advanced(self, event=None):
        self.advanced_shown = not self.advanced_shown
        self.adv_link.config(text="归一化参数 ▾" if self.advanced_shown else "归一化参数 ▸")
        if self.advanced_shown:
            self.adv.grid()
        else:
            self.adv.grid_remove()

    def _hover(self, on):
        if self.proc is not None:
            return
        self.start_btn.config(bg=ACCENT_HOVER if on else ACCENT)

    # ---------------- 合并 ----------------

    def start_merge(self):
        if self.proc is not None:
            return
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("提示", "请先选择 MP3 文件夹", parent=self)
            return
        folder_path = Path(folder)
        if not folder_path.is_dir():
            messagebox.showwarning("提示", "文件夹不存在：\n" + folder, parent=self)
            return
        try:
            has_mp3 = any(p.is_file() and p.suffix.lower() == ".mp3" for p in folder_path.iterdir())
        except OSError:
            has_mp3 = False
        if not has_mp3:
            messagebox.showwarning("提示", "所选文件夹下没有找到 MP3 文件", parent=self)
            return

        output = self.out_var.get().strip()
        if not output:
            output = str(folder_path / "合辑.mp3")
            self.out_var.set(output)
            self.output_auto = True
        out_path = Path(output)
        if not out_path.is_absolute():
            out_path = folder_path / out_path
            output = str(out_path)
            self.out_var.set(output)
        if not out_path.parent.is_dir():
            messagebox.showwarning("提示", "输出目录不存在：\n" + str(out_path.parent), parent=self)
            return

        if not shutil.which("ffmpeg"):
            messagebox.showerror("缺少 ffmpeg", "未检测到 ffmpeg，请先安装并加入 PATH。", parent=self)
            return
        try:
            import mutagen  # noqa: F401
        except ImportError:
            messagebox.showerror("缺少 mutagen", "未检测到 mutagen，请先执行：\n\npip install mutagen",
                                 parent=self)
            return

        title = self.title_var.get().strip() or "合辑"
        norm_key = NORMALIZE_MAP[self.norm_var.get()]
        cmd = [sys.executable, MERGE_SCRIPT, str(folder_path), output,
               "--title", title,
               "--sort-by", SORT_MAP[self.sort_var.get()],
               "--chapter-title-source", CHAPTER_MAP[self.chapter_var.get()],
               "--normalize", norm_key]
        if norm_key != "never":
            for flag, var in (("--normalize-bitrate", self.bitrate_var),
                              ("--normalize-sample-rate", self.sr_var),
                              ("--normalize-channels", self.ch_var),
                              ("--normalize-codec", self.codec_var)):
                v = var.get().strip()
                if v:
                    cmd += [flag, v]
        if not self.lyrics_var.get():
            cmd.append("--no-lyrics")
        else:
            if self.markers_var.get():
                cmd.append("--chapter-markers")
            lang = self.lang_var.get().strip()
            if lang and lang != "chi":
                cmd += ["--lyrics-lang", lang]

        self._run(cmd, output)

    def _run(self, cmd, output):
        self.cancelled = False
        self.current_output = output
        self._set_log_text("")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         cwd=str(BASE_DIR), env=env,
                                         creationflags=CREATE_NO_WINDOW)
        except OSError as e:
            self.proc = None
            messagebox.showerror("启动失败", str(e), parent=self)
            return
        self._set_running(True)
        self.open_btn.config(state="normal")
        self.set_status("正在合并…")
        threading.Thread(target=self._read_output, args=(self.proc,), daemon=True).start()

    def _read_output(self, proc):
        try:
            for raw in iter(proc.stdout.readline, b""):
                if not raw:
                    break
                self.log_queue.put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            code = proc.wait()
            self.log_queue.put(("done", code))

    def cancel_merge(self):
        if self.proc is None:
            return
        self.cancelled = True
        self.set_status("正在取消…")
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True)
        else:
            try:
                self.proc.terminate()
            except OSError:
                pass

    def _finish(self, code):
        self.proc = None
        self._set_running(False)
        if self.cancelled:
            self.set_status("已取消")
            self.log_line("—— 已取消 ——")
            return
        if code == 0:
            self.set_status("合并完成")
            self.log_line("—— 合并完成 ——")
            messagebox.showinfo("完成", "合并完成：\n" + self.current_output, parent=self)
        else:
            self.set_status(f"合并失败（退出码 {code}）")
            self.log_line("—— 合并失败 ——")
            messagebox.showerror("失败", "合并失败，请查看日志。", parent=self)

    def open_output(self):
        out = self.out_var.get().strip()
        if out and Path(out).is_file():
            target = out
            arg = "/select,"
        else:
            folder = self.folder_var.get().strip()
            if not folder or not Path(folder).is_dir():
                return
            target = folder
            arg = ""
        if os.name == "nt":
            subprocess.Popen(["explorer", arg, os.path.normpath(target)] if arg
                             else ["explorer", os.path.normpath(target)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(Path(target).parent if arg else target)])
        else:
            subprocess.Popen(["xdg-open", str(Path(target).parent if arg else target)])

    # ---------------- 窗口与日志 ----------------

    def on_close(self):
        if self.proc is not None:
            if not messagebox.askyesno("退出", "正在合并，确定要退出吗？", parent=self):
                return
            self.cancel_merge()
        self.destroy()

    def _set_running(self, on):
        self.start_btn.config(state="disabled" if on else "normal",
                              bg=ACCENT_OFF if on else ACCENT)
        self.cancel_btn.config(state="normal" if on else "disabled")

    def set_status(self, text):
        self.status.config(text=text)

    def _set_log_text(self, text, tag=None):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        if text:
            self.log.insert("end", text, tag or ())
        self.log.config(state="disabled")

    def _append_log(self, line):
        self.log.config(state="normal")
        at_bottom = self.log.yview()[1] >= 0.999
        self.log.insert("end", line + "\n")
        if at_bottom:
            self.log.see("end")
        self.log.config(state="disabled")

    def log_line(self, text):
        self._append_log(text)

    def _poll_log(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "done":
                    self._finish(item[1])
                    continue
                self._append_log(item)
        except queue.Empty:
            pass
        self.after(80, self._poll_log)


def main():
    make_dpi_aware()
    App().mainloop()


if __name__ == "__main__":
    main()
