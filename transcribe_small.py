"""
Whisper small 模型转写 test_douyin.wav
使用 hf-mirror.com 镜像下载模型
"""
import os
import sys
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import time

TEST_DIR = r"C:\工作区\Claw"
WAV_FILE = os.path.join(TEST_DIR, "test_douyin.wav")
OUTPUT_FILE = os.path.join(TEST_DIR, "test_douyin_transcript_small.txt")

if not os.path.exists(WAV_FILE):
    print(f"❌ 文件不存在: {WAV_FILE}")
    sys.exit(1)

file_size = os.path.getsize(WAV_FILE)
duration_est = file_size / (16000 * 2)
print(f"📁 音频: {os.path.basename(WAV_FILE)} ({file_size:,} bytes, 约 {duration_est:.0f} 秒)")
print(f"📥 加载 small 模型 (488MB)...")
start = time.time()

try:
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    load_time = time.time() - start
    print(f"✅ 模型加载完成 (耗时 {load_time:.0f} 秒)")
    
    print(f"🎙️ 开始转写...")
    transcribe_start = time.time()
    
    segments, info = model.transcribe(
        WAV_FILE, 
        language="zh",
        beam_size=5,
        vad_filter=False,
    )
    
    print(f"  检测语言: {info.language} (概率: {info.language_probability:.2f})")
    
    lines = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            line = f"[{seg.start:.1f}s-{seg.end:.1f}s] {text}"
            print(f"  {line}")
            lines.append(line)
    
    transcribe_time = time.time() - transcribe_start
    total_time = time.time() - start
    
    # 保存结果
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# 模型: Whisper small (faster-whisper)\n")
        f.write(f"# 文件: {os.path.basename(WAV_FILE)}\n")
        f.write(f"# 加载: {load_time:.0f}s  转写: {transcribe_time:.0f}s  总计: {total_time:.0f}s\n\n")
        for line in lines:
            f.write(line + "\n")
    
    print(f"\n⏱️ 加载: {load_time:.0f}s | 转写: {transcribe_time:.0f}s | 总计: {total_time:.0f}s")
    print(f"📄 结果已保存: {OUTPUT_FILE}")
    print(f"📝 共 {len(lines)} 段")
    
except Exception as e:
    print(f"❌ 失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
