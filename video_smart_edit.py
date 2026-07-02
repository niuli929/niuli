"""
视频智能剪辑 - 基于 Whisper 词级时间戳 + 静音间隙检测
========================================================
输入: 视频文件
输出: 去掉气口/废话间隙的精简视频

管线:
  视频 → ffmpeg提取WAV(16kHz mono) → faster-whisper(word_timestamps) 
       → 间隙分析(>gap_threshold则切开) → EDL → ffmpeg分段拼接

用法:
  python video_smart_edit.py <视频路径> [选项]
  
示例:
  python video_smart_edit.py input.mp4
  python video_smart_edit.py input.mp4 --gap 0.8 --padding 0.05 --min-dur 0.5
  python video_smart_edit.py input.mp4 --preview        # 只生成EDL不实际剪辑
  python video_smart_edit.py input.mp4 --model large-v3  # 用大模型(更准但更慢)
"""

import os
import sys
import json
import argparse
import subprocess
import time
from pathlib import Path

# ── 路径配置 ─────────────────────────────────────────────
FFMPEG = r"C:\Users\niu\Tools\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg.exe"
PYTHON = r"C:\Users\niu\.workbuddy\binaries\python\versions\3.13.12\python.exe"

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


def run(cmd, description=""):
    """运行命令，出错即停"""
    print(f"  [{description}] {' '.join(cmd) if isinstance(cmd, list) else cmd[:80]}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ 失败: {result.stderr[:300]}")
        sys.exit(1)
    return result


def extract_audio(video_path, wav_path):
    """用ffmpeg提取16kHz单声道WAV"""
    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
        wav_path
    ]
    run(cmd, "提取音频")
    return wav_path


def transcribe_word_level(wav_path, model_name="small"):
    """
    faster-whisper 词级转写，返回 [(word, start_time, end_time), ...]
    """
    print(f"  📥 加载模型: {model_name}")
    from faster_whisper import WhisperModel
    t0 = time.time()
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    print(f"  ✅ 加载完成 ({time.time()-t0:.0f}s), 开始转写...")

    segments, info = model.transcribe(
        wav_path,
        language="zh",
        beam_size=5,
        word_timestamps=True,      # ← 关键: 词级时间戳
        vad_filter=False,
    )
    print(f"  检测语言: {info.language} (概率: {info.language_probability:.2f})")

    words = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                text = w.word.strip()
                if text:
                    words.append((text, w.start, w.end))

    print(f"  ✅ 转写完成, 共 {len(words)} 个词, 跨度 {words[0][1]:.1f}s ~ {words[-1][2]:.1f}s")
    return words


def detect_gaps(words, gap_threshold=0.5, min_duration=0.5, padding=0.05):
    """
    检测词间间隙，返回保留区间列表
    
    gap_threshold: 间隙超过此值(秒)就切开
    min_duration: 保留段最小长度(秒)，太短的扔掉
    padding: 切口两侧保留缓冲(秒)，避免切太狠
    """
    # 按词顺序计算间隙
    gaps = []
    for i in range(1, len(words)):
        prev_end = words[i-1][2]
        curr_start = words[i][1]
        gap = curr_start - prev_end
        if gap > gap_threshold:
            gaps.append((i, prev_end, curr_start, gap))

    print(f"\n  📊 检测到 {len(gaps)} 个间隙 >{gap_threshold}s:")
    for idx, prev_end, curr_start, gap in gaps:
        prev_word = words[idx-1][0]
        curr_word = words[idx][0]
        print(f"    [{prev_end:.2f}s → {curr_start:.2f}s] 间隙 {gap:.2f}s  |  {prev_word} ... {curr_word}")

    # 生成保留区间
    ranges = []
    segment_start = words[0][1] - padding  # 第一个词前加padding
    cut_points = [g[1] for g in gaps]  # 所有切点的结束时间
    cut_starts = [g[2] for g in gaps]  # 所有切点的开始时间

    if segment_start < 0:
        segment_start = 0.0

    # 第一个区间: 开头到第一个切点
    if gaps:
        segment_end = gaps[0][1] + padding
        dur = segment_end - segment_start
        if dur >= min_duration:
            ranges.append((segment_start, segment_end))
        
        # 中间区间
        for i in range(len(gaps) - 1):
            seg_start = gaps[i][2] - padding
            seg_end = gaps[i+1][1] + padding
            dur = seg_end - seg_start
            if dur >= min_duration:
                ranges.append((seg_start, seg_end))
        
        # 最后一个区间: 最后一个切点之后到结尾
        seg_start = gaps[-1][2] - padding
        seg_end = words[-1][2] + padding
        dur = seg_end - seg_start
        if dur >= min_duration:
            ranges.append((seg_start, seg_end))
    else:
        # 没有间隙，全保留
        ranges.append((segment_start, words[-1][2] + padding))

    # 确保不越界
    ranges = [(max(0, s), e) for s, e in ranges]
    
    total_kept = sum(e - s for s, e in ranges)
    total_span = words[-1][2] - words[0][1]
    print(f"  📐 {total_span:.1f}s 原片 → {total_kept:.1f}s 保留 ({total_kept/total_span*100:.0f}%), "
          f"剪掉 {total_span-total_kept:.1f}s")

    return ranges


def build_edl(video_path, ranges, words):
    """生成 EDL JSON"""
    edl = {
        "sources": {"main": str(Path(video_path).resolve())},
        "grade": "",
        "ranges": []
    }
    for i, (s, e) in enumerate(ranges):
        # 找该区间内的文本
        note_words = [w[0] for w in words if w[1] >= s and w[2] <= e]
        note = "".join(note_words[:15])
        if len(note_words) > 15:
            note += "..."
        edl["ranges"].append({
            "source": "main",
            "start": round(s, 2),
            "end": round(e, 2),
            "note": note
        })
    # 加一个区间注释方便阅读
    total_kept = sum(r["end"] - r["start"] for r in edl["ranges"])
    edl["_summary"] = f"{len(ranges)} clips, {total_kept:.1f}s total"
    return edl


def render_cut(video_path, ranges, output_dir, output_name="final.mp4"):
    """
    ffmpeg 分段提取 + concat 拼接
    用 segment 提取避免重编码
    """
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    
    concat_file = outdir / "_concat.txt"
    lines = []
    
    for i, (seg_start, seg_end) in enumerate(ranges):
        seg_file = outdir / f"seg_{i:02d}.mp4"
        dur = seg_end - seg_start
        cmd = [
            FFMPEG, "-y", "-ss", str(seg_start), "-i", video_path,
            "-t", str(dur), "-c", "copy", "-avoid_negative_ts", "make_zero",
            str(seg_file)
        ]
        run(cmd, f"提取片段 {i+1}/{len(ranges)} [{seg_start:.1f}s - {seg_end:.1f}s]")
        lines.append(f"file '{seg_file.name}'")

    # 写 concat 文件
    concat_file.write_text("\n".join(lines), encoding="utf-8")

    # 拼接
    final_path = outdir / output_name
    cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy",
        str(final_path)
    ]
    run(cmd, "拼接最终视频")
    
    final_size = final_path.stat().st_size
    print(f"\n  ✅ 输出: {final_path} ({final_size:,} bytes)")
    return final_path


def main():
    parser = argparse.ArgumentParser(
        description="视频智能剪辑 - Whisper词级时间戳 + 静音间隙检测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("video", help="输入视频文件路径")
    parser.add_argument("--gap", type=float, default=0.5,
                        help="间隙阈值(秒), 超过此值即切开 (默认0.5)")
    parser.add_argument("--padding", type=float, default=0.05,
                        help="切口两侧缓冲(秒) (默认0.05)")
    parser.add_argument("--min-dur", type=float, default=0.5,
                        help="保留段最小长度(秒) (默认0.5)")
    parser.add_argument("--model", default="small",
                        choices=["tiny", "small", "medium", "large-v3"],
                        help="Whisper模型 (默认small)")
    parser.add_argument("--preview", action="store_true",
                        help="仅预览EDL, 不实际剪辑")
    parser.add_argument("--output", default=None,
                        help="输出目录 (默认: 视频同目录/edit/)")
    parser.add_argument("--keep-audio", action="store_true",
                        help="保留中间WAV文件")

    args = parser.parse_args()
    video_path = Path(args.video).resolve()
    if not video_path.exists():
        print(f"❌ 视频不存在: {video_path}")
        sys.exit(1)

    video_name = video_path.stem
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = video_path.parent / f"{video_name}_edit"

    # ── Step 1: 提取音频 ──
    wav_path = output_dir / f"{video_name}.wav"
    
    print(f"\n{'='*60}")
    print(f"🎬 视频智能剪辑")
    print(f"{'='*60}")
    print(f"  输入: {video_path}")
    print(f"  模型: {args.model}  间隙阈值: {args.gap}s  缓冲: {args.padding}s")
    
    t_total = time.time()
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not wav_path.exists() or args.keep_audio:
        extract_audio(str(video_path), str(wav_path))
    else:
        print(f"  📁 复用已有WAV: {wav_path}")

    # ── Step 2: 词级转写 ──
    words = transcribe_word_level(str(wav_path), args.model)

    # ── Step 3: 间隙检测 ──
    ranges = detect_gaps(words, args.gap, args.min_dur, args.padding)

    if not ranges:
        print("❌ 没有找到可保留的片段！尝试降低 --gap 或 --min-dur")
        sys.exit(1)

    # ── Step 4: 生成 EDL ──
    edl = build_edl(str(video_path), ranges, words)
    edl_path = output_dir / "edl.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  📋 EDL: {edl_path}")
    print(f"  📋 {edl['_summary']}")

    # ── Step 5: 剪辑 ──
    if args.preview:
        print("\n  🔍 预览模式，跳过实际剪辑")
    else:
        final_path = render_cut(str(video_path), ranges, str(output_dir))

    # ── 清理临时WAV ──
    if not args.keep_audio and wav_path.exists():
        wav_path.unlink()
        print(f"  🧹 已清理临时WAV")

    print(f"\n{'='*60}")
    print(f"⏱️ 总耗时: {time.time() - t_total:.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
