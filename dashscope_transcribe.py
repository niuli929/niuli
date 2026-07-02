"""
百炼 DashScope Paraformer 文件转写
使用 API Key 直接调用，提交 WAV 文件获取转写结果
"""
import requests
import json
import time
import os
import sys

API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
BASE_URL = "https://ws-wchslbn38z9tvuul.cn-beijing.maas.aliyuncs.com/api/v1"
WAV_FILE = r"C:\工作区\Claw\test_douyin.wav"

def submit_transcription(wav_path):
    """提交文件转写任务，返回 task_id"""
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
                return task_id
            # Alternative: direct result
            if "output" in result and "results" in result["output"]:
                return result
        return None

def poll_result(task_id, max_wait=120):
    """轮询转写结果"""
    url = f"{BASE_URL}/services/audio/asr/transcription/{task_id}"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    print(f"\n[轮询] 等待转写完成...")
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
        
        if status == "SUCCEEDED":
            print(f"[轮询] ✅ 转写完成!")
            return result
        elif status == "FAILED":
            print(f"[轮询] ❌ 转写失败: {result}")
            return None
        
        time.sleep(2)
    
    print(f"[轮询] ⚠️ 超时")
    return None

def extract_text(result):
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

# ============ 尝试多种调用方式 ============
def try_method_1(wav_path):
    """方法1: 文件上传到 transcription 端点"""
    print("\n" + "="*60)
    print("方法1: 文件上传 transcription 端点")
    print("="*60)
    return submit_transcription(wav_path)

def try_method_2(wav_path):
    """方法2: 文件上传到 asr/transcription (不同参数格式)"""
    print("\n" + "="*60)
    print("方法2: 不带 parameters 字段")
    print("="*60)
    
    url = f"{BASE_URL}/services/audio/asr/transcription"
    file_size = os.path.getsize(wav_path)
    print(f"文件: {file_size/1024/1024:.1f}MB")
    
    with open(wav_path, "rb") as f:
        files = {"file": (os.path.basename(wav_path), f, "audio/wav")}
        headers = {"Authorization": f"Bearer {API_KEY}"}
        data = {"model": "paraformer-v2"}
        
        r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        print(f"状态码: {r.status_code}")
        print(f"响应: {r.text[:500]}")
        
        if r.status_code == 200:
            result = r.json()
            task_id = result.get("output", {}).get("task_id", "")
            if task_id:
                return task_id
            return result
        return None

def try_method_3(wav_path):
    """方法3: OpenAI compatible 端点"""
    print("\n" + "="*60)
    print("方法3: OpenAI Compatible 端点")
    print("="*60)
    
    url = f"https://ws-wchslbn38z9tvuul.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/audio/transcriptions"
    
    with open(wav_path, "rb") as f:
        files = {"file": (os.path.basename(wav_path), f, "audio/wav")}
        headers = {"Authorization": f"Bearer {API_KEY}"}
        data = {"model": "paraformer-v2", "language": "zh"}
        
        r = requests.post(url, headers=headers, files=files, data=data, timeout=120)
        print(f"状态码: {r.status_code}")
        print(f"响应: {r.text}")
        
        if r.status_code == 200:
            return r.json()
        return None

def try_method_4(wav_path):
    """方法4: 异步 file transcription 完整流程"""
    print("\n" + "="*60)
    print("方法4: 异步转写 (提交 + 轮询)")
    print("="*60)
    
    task_id = try_method_1(wav_path)
    if isinstance(task_id, dict):
        # Got direct result
        text = extract_text(task_id)
        if text:
            return text
        # Try to get task_id from different path
        task_id = task_id.get("output", {}).get("task_id", "")
    
    if isinstance(task_id, str) and task_id:
        result = poll_result(task_id)
        if result:
            text = extract_text(result)
            if text:
                return text
            print(f"[调试] 完整结果: {json.dumps(result, ensure_ascii=False, indent=2)[:1000]}")
    return None

if __name__ == "__main__":
    print("=" * 60)
    print("百炼 DashScope Paraformer 文件转写")
    print("=" * 60)
    
    if not os.path.exists(WAV_FILE):
        print(f"❌ 文件不存在: {WAV_FILE}")
        sys.exit(1)
    
    # 先试异步流程
    result = try_method_4(WAV_FILE)
    if result:
        print("\n" + "=" * 60)
        print("转写结果:")
        print("=" * 60)
        print(result)
        out = os.path.splitext(WAV_FILE)[0] + "_transcript.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"\n✅ 已保存: {out}")
    else:
        # 回退: 试其他方法
        print("\n异步失败, 尝试其他方法...")
        result = try_method_3(WAV_FILE)
        if result:
            text = result.get("text", str(result))
            print(f"\n结果: {text}")
