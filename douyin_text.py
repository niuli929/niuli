"""
抖音文案提取 — 一站式
用法: python douyin_text.py "https://v.douyin.com/xxxxx/"
流程: 下载视频 → 提取音频 → Whisper small 转写 → 输出文案
"""
import os
import sys
import time
import shutil
import tempfile
import subprocess
import argparse

PROJECT_DIR = r"C:\工作区\Claw"
FFMPEG = r"C:\Users\niu\Tools\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg.exe"

# 用国内镜像下载模型
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


def run(cmd, timeout=120):
    """运行命令，打印输出"""
    print(f"  🔧 {' '.join(cmd[:4])}...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        err = result.stderr.strip()
        if err:
            print(f"  ❌ {err[-300:]}")
    return result


def step1_download(url, output_dir):
    """下载抖音视频"""
    print("\n📥 [1/3] 下载抖音视频...")
    
    output_template = os.path.join(output_dir, "%(title).50s.%(ext)s")
    
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--cookies-from-browser", "chrome",
        "--no-playlist",
        "--merge-output-format", "mp4",
        "-o", output_template,
        url
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    
    # 找下载的文件
    files = [f for f in os.listdir(output_dir) 
             if f.endswith(('.mp4', '.mkv', '.webm', '.flv'))]
    
    if not files:
        print(f"  ❌ 下载失败，没有找到视频文件")
        print(f"  yt-dlp 输出:\n{result.stdout[-500:]}")
        print(f"  错误:\n{result.stderr[-500:]}")
        return None
    
    video_path = os.path.join(output_dir, files[0])
    size_mb = os.path.getsize(video_path) / 1024 / 1024
    print(f"  ✅ 下载完成: {os.path.basename(video_path)} ({size_mb:.1f}MB)")
    return video_path


def step2_extract_audio(video_path, output_dir):
    """提取音频为 16kHz mono WAV"""
    print("\n🎵 [2/3] 提取音频...")
    
    audio_path = os.path.join(output_dir, "audio.wav")
    
    cmd = [
        FFMPEG, "-y",
        "-i", video_path,
        "-vn",               # 不要视频
        "-ac", "1",          # 单声道
        "-ar", "16000",      # 16kHz
        "-sample_fmt", "s16",
        audio_path
    ]
    
    result = run(cmd, timeout=120)
    if result.returncode != 0:
        return None
    
    size_mb = os.path.getsize(audio_path) / 1024 / 1024
    duration = os.path.getsize(audio_path) / (16000 * 2)
    print(f"  ✅ 音频提取完成: {size_mb:.1f}MB, 约 {duration:.0f} 秒")
    return audio_path


def step3_transcribe(audio_path, output_dir):
    """Whisper small 转写"""
    print("\n🎙️ [3/3] Whisper small 转写...")
    
    from faster_whisper import WhisperModel
    
    print("  加载 small 模型（首次需缓存约30秒）...")
    t0 = time.time()
    model = WhisperModel("small", device="cpu", compute_type="int8")
    print(f"  模型就绪 ({time.time()-t0:.0f}s)")
    
    t1 = time.time()
    segments, info = model.transcribe(
        audio_path,
        language="zh",
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
        ),
    )
    
    print(f"  检测语言: {info.language} ({info.language_probability:.2f})")
    
    lines = []
    for seg in segments:
        text = seg.text.strip()
        if text and len(text) >= 2:  # 过滤太短的
            lines.append(text)
            print(f"  [{seg.start:.0f}s] {text}")
    
    elapsed = time.time() - t1
    
    # 保存结果
    output_file = os.path.join(output_dir, "文案.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    print(f"\n⏱️ 转写耗时: {elapsed:.0f}s")
    print(f"📝 共 {len(lines)} 句")
    print(f"📄 已保存: {output_file}")
    
    return lines


def main():
    parser = argparse.ArgumentParser(description="抖音文案提取")
    parser.add_argument("url", nargs="?", help="抖音分享链接")
    parser.add_argument("--file", "-f", help="或直接指定本地视频文件")
    parser.add_argument("--audio-only", "-a", help="或直接指定音频文件")
    args = parser.parse_args()
    
    # 创建临时工作目录
    work_dir = os.path.join(PROJECT_DIR, "douyin_output")
    os.makedirs(work_dir, exist_ok=True)
    
    print("=" * 60)
    print("  抖音文案提取 🎬→📝")
    print("=" * 60)
    
    # 获取视频
    if args.audio_only:
        audio_path = args.audio_only
        if not os.path.exists(audio_path):
            print(f"❌ 音频文件不存在: {audio_path}")
            sys.exit(1)
        print(f"📁 直接使用音频: {os.path.basename(audio_path)}")
    elif args.file:
        video_path = args.file
        if not os.path.exists(video_path):
            print(f"❌ 视频文件不存在: {video_path}")
            sys.exit(1)
        print(f"📁 本地视频: {os.path.basename(video_path)}")
        audio_path = step2_extract_audio(video_path, work_dir)
    elif args.url:
        video_path = step1_download(args.url, work_dir)
        if not video_path:
            sys.exit(1)
        audio_path = step2_extract_audio(video_path, work_dir)
    else:
        print("请提供抖音链接或本地文件")
        print("用法: python douyin_text.py <抖音链接>")
        print("      python douyin_text.py -f <本地视频>")
        print("      python douyin_text.py -a <音频文件>")
        sys.exit(1)
    
    if not audio_path or not os.path.exists(audio_path):
        print("❌ 音频提取失败")
        sys.exit(1)
    
    # 转写
    lines = step3_transcribe(audio_path, work_dir)
    
    if not lines:
        print("\n⚠️ 未识别到有效文案（可能视频中没有人声）")
        sys.exit(1)
    
    # 输出
    print("\n" + "=" * 60)
    print("📝 提取文案:")
    print("=" * 60)
    for line in lines:
        print(f"  {line}")
    print("=" * 60)
    
    # 同时保存到项目根目录方便查看
    final_output = os.path.join(PROJECT_DIR, "douyin_文案.txt")
    shutil.copy(os.path.join(work_dir, "文案.txt"), final_output)
    print(f"📄 另存: {final_output}")


if __name__ == "__main__":
    main()
