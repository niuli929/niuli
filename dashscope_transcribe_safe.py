"""
百炼 DashScope Paraformer 文件转写 — 安全版
- TaskJournal 持久化 task_id，崩溃后可恢复轮询
- 轮询过程中增量保存
- 支持 --resume 参数恢复未完成任务
"""
import requests
import json
import time
import os
import sys
import argparse

from safe_store import (
    SafeCollector, TaskJournal, install_signal_handler,
    safe_read_json, atomic_write
)

API_KEY = "sk-ws-H.RYHMIYL.ypz5.MEUCIQCz1-R4sTaFthskdn-_FYQqS44QAZJYXA9uah063n1UZQIgAIHxoJSlk4b8G-KnLsGo8DFBeeCMQiWjKO8_okUTwTo"
BASE_URL = "https://ws-wchslbn38z9tvuul.cn-beijing.maas.aliyuncs.com/api/v1"
WAV_FILE = r"C:\工作区\Claw\test_douyin.wav"
OUTPUT_FILE = r"C:\工作区\Claw\test_douyin_transcript.txt"
JOURNAL_FILE = r"C:\工作区\Claw\.task_journal.json"

# ============================================================
# 提交任务
# ============================================================

def submit_transcription(wav_path: str, journal: TaskJournal):
    """提交文件转写任务，并持久化 task_id"""
    url = f"{BASE_URL}/services/audio/asr/transcription"

    print(f"[提交] 上传文件: {os.path.basename(wav_path)}")
    file_size = os.path.getsize(wav_path)
    print(f"[提交] 文件大小: {file_size/1024/1024:.1f}MB")

    with open(wav_path, "rb") as f:
        files = {"file": (os.path.basename(wav_path), f, "audio/wav")}
        headers = {"Authorization": f"Bearer {API_KEY}"}
        data = {
            "model": "paraformer-v2",
            "parameters": json.dumps({
                "format": "wav",
                "sample_rate": 16000,
                "language_hints": ["zh"],
            }),
        }

        r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        print(f"[提交] 状态码: {r.status_code}")
        print(f"[提交] 响应: {r.text[:500]}")

        if r.status_code == 200:
            result = r.json()
            task_id = result.get("output", {}).get("task_id", "")
            if task_id:
                print(f"[提交] ✅ task_id: {task_id}")
                # 持久化任务
                journal.set_task(task_id, provider="dashscope", input_file=wav_path)
                return task_id
            # 直接返回结果
            if "output" in result and "results" in result["output"]:
                return result
        return None


# ============================================================
# 轮询结果（带增量保存）
# ============================================================

def poll_result(task_id: str, max_wait: int = 120, journal: TaskJournal = None,
                collector: SafeCollector = None):
    """轮询转写结果，边轮询边保存"""
    url = f"{BASE_URL}/services/audio/asr/transcription/{task_id}"
    headers = {"Authorization": f"Bearer {API_KEY}"}

    print(f"\n[轮询] 等待转写完成 (task_id: {task_id})...")
    last_text_count = 0

    for i in range(max_wait):
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            print(f"[轮询] HTTP {r.status_code}: {r.text[:200]}")
            time.sleep(2)
            continue

        result = r.json()
        status = result.get("output", {}).get("task_status", "UNKNOWN")

        if i == 0 or i % 5 == 0:
            print(f"  [{i}s] 状态: {status}")

        # 更新 journal
        if journal:
            journal.set_running()

        # 即使任务还在运行，也尝试提取已有文本
        if collector:
            partial_text = extract_text(result)
            partial_lines = partial_text.split("\n") if partial_text else []
            new_lines = partial_lines[last_text_count:]
            for line in new_lines:
                if line.strip():
                    collector.add(line)
            last_text_count = len(partial_lines)

        if status == "SUCCEEDED":
            print(f"[轮询] ✅ 转写完成!")
            # 确保完整结果写入
            full_text = extract_text(result)
            if collector:
                # 用完整结果覆盖增量文件
                atomic_write(collector.output_path, full_text)
                collector.finalize()
            if journal:
                journal.set_completed(collector.output_path if collector else "")
            return result
        elif status == "FAILED":
            print(f"[轮询] ❌ 转写失败: {result}")
            if journal:
                journal.set_failed(json.dumps(result, ensure_ascii=False))
            return None

        time.sleep(2)

    print(f"[轮询] ⚠️ 超时 ({max_wait}s)")
    # 超时时保存已有内容
    if collector and len(collector) > 0:
        collector.finalize()
        print(f"  💾 已保存 {len(collector)} 条部分结果")
    return None


def extract_text(result: dict) -> str:
    """从转写结果提取文本"""
    output = result.get("output", {})
    results = output.get("results", [])

    lines = []
    for item in results:
        sentences = item.get("sentences", item.get("transcription", []))
        if isinstance(sentences, list):
            for s in sentences:
                text = s.get("text", "")
                if text.strip():
                    lines.append(text)
        elif isinstance(sentences, dict):
            text = sentences.get("text", "")
            if text.strip():
                lines.append(text)

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="DashScope 安全转写")
    parser.add_argument("--resume", action="store_true", help="恢复未完成的任务")
    parser.add_argument("--clear", action="store_true", help="清除任务日记")
    args = parser.parse_args()

    journal = TaskJournal(JOURNAL_FILE)

    # 清除模式
    if args.clear:
        journal.clear()
        print("🧹 任务日记已清除")
        return

    # 恢复模式
    if args.resume:
        if journal.has_pending_task():
            task_id = journal.get_task_id()
            print(f"[恢复] 🔄 恢复任务: {task_id}")
            collector = SafeCollector(OUTPUT_FILE)
            result = poll_result(task_id, max_wait=120, journal=journal, collector=collector)

            if result:
                text = extract_text(result)
                print("\n" + "=" * 60)
                print("转写结果:")
                print("=" * 60)
                print(text)
                print(f"\n✅ 已保存: {OUTPUT_FILE}")
            else:
                print("❌ 恢复失败，请重新提交")
            return
        else:
            print("[恢复] 没有未完成的任务")
            return

    # 正常流程
    print("=" * 60)
    print("百炼 DashScope Paraformer 文件转写 (安全版 🔒)")
    print("=" * 60)

    if not os.path.exists(WAV_FILE):
        print(f"❌ 文件不存在: {WAV_FILE}")
        sys.exit(1)

    # 清理旧任务
    journal.clear()

    # 信号处理
    def cleanup():
        print("\n[清理] 保存当前状态...")
        journal._save()
        print("任务状态已保存，可用 --resume 恢复")

    install_signal_handler(cleanup)

    # 提交任务
    task_info = submit_transcription(WAV_FILE, journal)

    if isinstance(task_info, dict):
        # 直接拿到结果
        text = extract_text(task_info)
        if text:
            atomic_write(OUTPUT_FILE, text)
            journal.set_completed(OUTPUT_FILE)
            print("\n" + "=" * 60)
            print("转写结果:")
            print("=" * 60)
            print(text)
            print(f"\n✅ 已保存: {OUTPUT_FILE}")
            return

    if isinstance(task_info, str):
        # 异步任务，开始轮询
        collector = SafeCollector(OUTPUT_FILE)
        result = poll_result(task_info, max_wait=120, journal=journal, collector=collector)

        if result:
            text = extract_text(result)
            print("\n" + "=" * 60)
            print("转写结果:")
            print("=" * 60)
            print(text)
            print(f"\n✅ 已保存: {OUTPUT_FILE}")
        else:
            print("❌ 转写未完成，可用 --resume 恢复")
            return
    else:
        print("❌ 提交失败")


if __name__ == "__main__":
    main()
