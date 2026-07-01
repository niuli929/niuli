"""
抖音 → 文案 全自动流水线
用法:
  python douyin_auto.py "https://v.douyin.com/xxx/"          # 单个链接
  python douyin_auto.py --user MS4wLjABAAAAxxx                # 博主主页批量
  python douyin_auto.py --login                                # 仅登录
"""
import subprocess
import sys
import os
import json
import shutil
import tempfile
import argparse
from pathlib import Path

DY_EXE = r"C:\Users\niu\.workbuddy\binaries\python\versions\3.13.12\Scripts\dy.exe"
OUTPUT_DIR = Path(__file__).parent / "douyin_output"
TEXT_OUTPUT = Path(__file__).parent / "douyin_文案.txt"


def run(cmd, timeout=120):
    """运行命令并返回结果"""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
    return result


def dy_login():
    """登录抖音（扫码方式，浏览器自动弹出）"""
    print("🔐 正在打开浏览器进行抖音扫码登录...")
    print("   如果浏览器已登录过抖音，会自动提取 Cookie")
    result = run([DY_EXE, "login", "--browser"], timeout=60)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        return False
    return True


def dy_download(url_or_id, user_mode=False, limit=20):
    """使用 dy-cli 下载视频"""
    cmd = [DY_EXE, "download", url_or_id]
    if user_mode:
        cmd.extend(["--user", "--limit", str(limit)])
    
    print(f"📥 正在下载: {url_or_id}")
    result = run(cmd, timeout=180)
    print(result.stdout)
    
    if result.returncode != 0:
        print(f"❌ 下载失败:\n{result.stderr}")
        return None
    
    # dy-cli 默认下载到当前目录，找到最新下载的 mp4 文件
    downloads = sorted(
        Path.cwd().glob("*.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    
    # 也检查子目录
    for d in Path.cwd().iterdir():
        if d.is_dir():
            downloads.extend(sorted(d.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True))
    
    if downloads:
        return str(downloads[0])
    
    # 可能下载到 Downloads 文件夹
    downloads_dir = Path.home() / "Downloads"
    if downloads_dir.exists():
        dl_files = sorted(downloads_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if dl_files:
            return str(dl_files[0])
    
    return None


def transcribe(video_path, output_path=None):
    """使用 Whisper small 转写"""
    if output_path is None:
        output_path = TEXT_OUTPUT
    
    print(f"🎙️ 正在转写: {video_path}")
    
    # 用 faster-whisper 转写
    script = '''
import sys
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
from faster_whisper import WhisperModel

video_path = sys.argv[1]
output_path = sys.argv[2]

model = WhisperModel("small", device="cpu", compute_type="int8")
segments, _ = model.transcribe(video_path, language="zh", beam_size=5, vad_filter=True)

with open(output_path, "w", encoding="utf-8") as f:
    for seg in segments:
        text = seg.text.strip()
        if text:
            f.write(text + "\\n")
            print(text)

print(f"\\n✅ 已保存到: {output_path}")
'''
    
    result = subprocess.run(
        [sys.executable, "-c", script, video_path, str(output_path)],
        capture_output=True, text=True, timeout=600
    )
    
    print(result.stdout)
    if result.returncode != 0:
        print(f"❌ 转写失败:\n{result.stderr}")
        return None
    
    return str(output_path)


def process_link(url, keep_video=False):
    """处理单个抖音链接：下载 → 转写 → 返回文案"""
    # 1. 下载
    video_path = dy_download(url)
    if not video_path:
        return None
    
    print(f"✅ 视频已下载: {video_path}")
    
    # 2. 转写
    text_path = transcribe(video_path)
    if not text_path:
        return None
    
    # 3. 读取文案
    with open(text_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 4. 清理下载的视频
    if not keep_video:
        try:
            os.remove(video_path)
            print(f"🗑️ 已清理: {video_path}")
        except:
            pass
    
    return content


def process_user(sec_uid, limit=20, keep_video=False):
    """处理博主主页：批量下载 → 逐个转写"""
    print(f"📦 批量下载博主作品 (最多 {limit} 个)...")
    
    video_path = dy_download(sec_uid, user_mode=True, limit=limit)
    
    # 批量下载会下到子目录，列出所有 mp4
    downloaded = list(Path.cwd().rglob("*.mp4"))
    downloaded.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not downloaded:
        print("❌ 未找到下载的视频文件")
        return None
    
    print(f"📁 找到 {len(downloaded)} 个视频文件")
    
    all_texts = []
    for i, vp in enumerate(downloaded[:limit], 1):
        print(f"\n--- [{i}/{min(len(downloaded), limit)}] 转写: {vp.name} ---")
        out = OUTPUT_DIR / f"{vp.stem}.txt"
        text_path = transcribe(str(vp), str(out))
        if text_path:
            with open(text_path, "r", encoding="utf-8") as f:
                all_texts.append({
                    "file": vp.name,
                    "text": f.read()
                })
        if not keep_video:
            try:
                os.remove(str(vp))
            except:
                pass
    
    # 汇总到 douyin_文案.txt
    with open(TEXT_OUTPUT, "w", encoding="utf-8") as f:
        for item in all_texts:
            f.write(f"### {item['file']}\n\n")
            f.write(item['text'])
            f.write("\n\n---\n\n")
    
    print(f"\n✅ 全部完成！文案已保存到: {TEXT_OUTPUT}")
    return TEXT_OUTPUT


def main():
    parser = argparse.ArgumentParser(description="抖音 → 文案 全自动流水线")
    parser.add_argument("url", nargs="?", help="抖音分享链接")
    parser.add_argument("--user", help="博主 sec_uid，批量下载主页作品")
    parser.add_argument("--limit", type=int, default=20, help="批量下载数量上限")
    parser.add_argument("--login", action="store_true", help="仅登录")
    parser.add_argument("--keep-video", action="store_true", help="保留下载的视频文件")
    parser.add_argument("-f", "--file", help="本地视频文件直接转写")
    
    args = parser.parse_args()
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    if args.login:
        dy_login()
        return
    
    if args.file:
        text_path = transcribe(args.file)
        if text_path:
            with open(text_path, "r", encoding="utf-8") as f:
                print(f.read())
        return
    
    if args.user:
        process_user(args.user, limit=args.limit, keep_video=args.keep_video)
        return
    
    if args.url:
        content = process_link(args.url, keep_video=args.keep_video)
        if content:
            print("\n" + "=" * 50)
            print(content)
            print("=" * 50)
            with open(TEXT_OUTPUT, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"\n✅ 文案已保存到: {TEXT_OUTPUT}")
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()
