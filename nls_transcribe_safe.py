"""
阿里云 NLS 实时语音识别 — 安全版
- 使用 SafeCollector 增量保存，每句话立刻落盘
- 信号处理，Ctrl+C 不丢数据
"""
import json
import hmac
import hashlib
import base64
import time
import uuid
import urllib.parse
import requests
import websocket
import wave
import sys
import os
import threading

from safe_store import SafeCollector, install_signal_handler

AK_ID = os.environ.get("ALIYUN_AK_ID", "")
AK_SECRET = os.environ.get("ALIYUN_AK_SECRET", "")
APP_KEY = os.environ.get("ALIYUN_NLS_APP_KEY", "")
WAV_FILE = r"C:\工作区\Claw\test_douyin.wav"
OUTPUT_FILE = r"C:\工作区\Claw\test_douyin_transcript.txt"

def gen_32hex():
    return uuid.uuid4().hex

def get_nls_token(ak_id, ak_secret):
    params = {
        "AccessKeyId": ak_id,
        "Action": "CreateToken",
        "Version": "2019-02-28",
        "Format": "JSON",
        "RegionId": "cn-shanghai",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    canonical_query = urllib.parse.urlencode(sorted_params)
    string_to_sign = "GET" + "&" + urllib.parse.quote("/", safe="") + "&" + urllib.parse.quote(canonical_query, safe="")
    key = (ak_secret + "&").encode("utf-8")
    h = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1)
    signature = base64.b64encode(h.digest()).decode("utf-8")
    all_params = dict(params)
    all_params["Signature"] = signature
    url = "https://nls-meta.cn-shanghai.aliyuncs.com/?" + urllib.parse.urlencode(all_params)
    print(f"[Token] 请求中...")
    r = requests.get(url, timeout=10)
    data = r.json()
    if "Token" in data:
        print(f"[Token] ✅ 获取成功")
        return data["Token"].get("Id")
    print(f"[Token] ❌ 失败: {data}")
    return None

def transcribe():
    # 读取 WAV 信息
    with wave.open(WAV_FILE, "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        nf = wf.getnframes()
        dur = nf / sr
    print(f"\n[WAV] {sr}Hz {ch}ch {sw*8}bit, {dur:.1f}s")

    # 获取 token
    token = get_nls_token(AK_ID, AK_SECRET)
    if not token:
        sys.exit(1)
    print(f"Token: {token[:20]}...")

    # === 安全收集器：每句话立即落盘 ===
    collector = SafeCollector(OUTPUT_FILE, flush_every=1)

    # === 信号处理：Ctrl+C 优雅退出 ===
    ws_ref = {"ws": None}

    def cleanup():
        print("\n[清理] 正在保存数据...")
        collector.finalize()
        if ws_ref["ws"]:
            try:
                stop = json.dumps({
                    "header": {
                        "message_id": gen_32hex(),
                        "task_id": task_id,
                        "namespace": "SpeechTranscriber",
                        "name": "StopTranscription",
                        "appkey": APP_KEY,
                    },
                    "payload": {},
                })
                ws_ref["ws"].send(stop)
            except:
                pass
            try:
                ws_ref["ws"].close()
            except:
                pass

    install_signal_handler(cleanup)

    # WebSocket
    ws_url = f"wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1?appkey={APP_KEY}&token={token}"
    print(f"[WS] 连接...")
    ws = websocket.create_connection(ws_url, timeout=10)
    ws_ref["ws"] = ws
    print(f"[WS] ✅ 已连接")

    task_id = gen_32hex()
    msg_id = gen_32hex()

    # StartTranscription
    start_cmd = json.dumps({
        "header": {
            "message_id": msg_id,
            "task_id": task_id,
            "namespace": "SpeechTranscriber",
            "name": "StartTranscription",
            "appkey": APP_KEY,
        },
        "payload": {
            "format": "pcm",
            "sample_rate": sr,
            "enable_intermediate_result": True,
            "enable_punctuation_prediction": True,
            "enable_inverse_text_normalization": True,
        },
    })
    print(f"[WS] >>> StartTranscription")
    ws.send(start_cmd)

    # 等待 TranscriptionStarted
    ws.settimeout(5.0)
    started = False
    try:
        resp = ws.recv()
        data = json.loads(resp)
        name = data["header"]["name"]
        print(f"[WS] <<< {name} status={data['header'].get('status')}")
        if name == "TranscriptionStarted":
            started = True
        elif name == "TaskFailed":
            print(f"❌ {data['header'].get('status_text')}")
            ws.close()
            return
    except Exception as e:
        print(f"[WS] 等待 Started 异常: {e}")

    if not started:
        print("[WS] ⚠️ 未收到 Started，尝试继续...")

    ws_closed = threading.Event()

    def recv_loop():
        ws.settimeout(1.0)
        while not ws_closed.is_set():
            try:
                msg = ws.recv()
                if not msg:
                    break
                data = json.loads(msg)
                h = data.get("header", {})
                name = h.get("name", "")
                if name == "TranscriptionResultChanged":
                    text = data.get("payload", {}).get("result", "")
                    if text.strip():
                        print(f"  ⏳ {text}")
                elif name == "SentenceEnd":
                    text = data.get("payload", {}).get("result", "")
                    idx = data.get("payload", {}).get("index", 0)
                    t_time = data.get("payload", {}).get("time", 0)
                    conf = data.get("payload", {}).get("confidence", 0)
                    if text.strip():
                        print(f"  ✅ [{idx}] ({t_time}ms, {conf:.0%}): {text}")
                        # === 🔒 立即落盘 ===
                        collector.add(text)
                elif name == "SentenceBegin":
                    pass
                elif name == "TranscriptionCompleted":
                    print(f"[WS] <<< TranscriptionCompleted")
                    ws_closed.set()
                    break
                elif name == "TaskFailed":
                    print(f"[WS] ❌ TaskFailed: {h.get('status_text')}")
                    ws_closed.set()
                    break
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                if not ws_closed.is_set():
                    print(f"[WS] recv error: {e}")
                break

    t = threading.Thread(target=recv_loop, daemon=True)
    t.start()

    # 发送音频
    time.sleep(0.3)
    chunk_frames = 3200
    chunk_sleep = 0.08
    start_time = time.time()

    with wave.open(WAV_FILE, "rb") as wf:
        sent = 0
        chunk_count = 0
        while True:
            chunk = wf.readframes(chunk_frames)
            if not chunk:
                break
            ws.send_binary(chunk)
            sent += len(chunk)
            chunk_count += 1
            time.sleep(chunk_sleep)
            if chunk_count % 25 == 0:
                elapsed = time.time() - start_time
                pct = min(100, (elapsed / dur) * 100)
                print(f"  发送进度: {pct:.0f}% (已保存 {len(collector)} 句)")

    elapsed = time.time() - start_time
    print(f"[WS] 音频发送完毕 ({sent} bytes, 耗时 {elapsed:.1f}s)")

    # StopTranscription
    stop_cmd = json.dumps({
        "header": {
            "message_id": gen_32hex(),
            "task_id": task_id,
            "namespace": "SpeechTranscriber",
            "name": "StopTranscription",
            "appkey": APP_KEY,
        },
        "payload": {},
    })
    print(f"[WS] >>> StopTranscription")
    ws.send(stop_cmd)

    # 等待完成
    ws_closed.wait(timeout=60)
    t.join(timeout=5)
    try:
        ws.close()
    except:
        pass

    # 标记完成
    collector.finalize()
    return collector.get_all()

if __name__ == "__main__":
    print("=" * 60)
    print("阿里云 NLS 实时语音识别 (安全版 🔒)")
    print("=" * 60)

    lines = transcribe()

    print("\n" + "=" * 60)
    print("最终结果:")
    print("=" * 60)
    if lines:
        full = "\n".join(lines)
        print(full)
        print(f"\n✅ 已安全保存: {OUTPUT_FILE}")
    else:
        print("(无结果)")
