"""
NLS 实时语音识别 - 实时速率版
"""
import json, hmac, hashlib, base64, time, uuid, urllib.parse
import requests, websocket, wave, sys, os, threading

AK_ID = os.getenv("ALIYUN_AK_ID", "your-ak-id")
AK_SECRET = os.getenv("ALIYUN_AK_SECRET", "your-ak-secret")
APP_KEY = "ULB8ezBMOvfcRjDu"
WAV_FILE = r"C:\工作区\Claw\test_douyin.wav"

def gen_32hex():
    return uuid.uuid4().hex

def get_token():
    params = {
        "AccessKeyId": AK_ID, "Action": "CreateToken",
        "Version": "2019-02-28", "Format": "JSON",
        "RegionId": "cn-shanghai", "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    sp = sorted(params.items(), key=lambda x: x[0])
    cq = urllib.parse.urlencode(sp)
    sts = "GET&%2F&" + urllib.parse.quote(cq, safe="")
    h = hmac.new((AK_SECRET+"&").encode(), sts.encode(), hashlib.sha1)
    sig = base64.b64encode(h.digest()).decode()
    ap = dict(params); ap["Signature"] = sig
    url = "https://nls-meta.cn-shanghai.aliyuncs.com/?" + urllib.parse.urlencode(ap)
    r = requests.get(url, timeout=10)
    d = r.json()
    return d.get("Token", {}).get("Id") if "Token" in d else None

def transcribe():
    with wave.open(WAV_FILE, "rb") as wf:
        sr, ch, sw, nf = wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes()
        dur = nf / sr
    print(f"\n音频: {sr}Hz {ch}ch {sw*8}bit, {dur:.0f}s")

    token = get_token()
    if not token: print("Token失败"); return
    print(f"Token: OK")

    ws = websocket.create_connection(
        f"wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1?appkey={APP_KEY}&token={token}",
        timeout=10)
    print("WS: 已连接")

    task_id = gen_32hex()
    ws.send(json.dumps({
        "header": {
            "message_id": gen_32hex(), "task_id": task_id,
            "namespace": "SpeechTranscriber", "name": "StartTranscription",
            "appkey": APP_KEY,
        },
        "payload": {
            "format": "pcm", "sample_rate": sr,
            "enable_intermediate_result": True,
            "enable_punctuation_prediction": True,
            "enable_inverse_text_normalization": True,
        },
    }))

    ws.settimeout(5.0)
    resp = json.loads(ws.recv())
    name = resp["header"]["name"]
    print(f"WS: {name}")
    if name == "TaskFailed":
        print(f"失败: {resp['header'].get('status_text')}")
        return

    final_lines = []
    done = threading.Event()

    def recv_loop():
        ws.settimeout(1.0)
        while not done.is_set():
            try:
                msg = ws.recv()
                if not msg: break
                data = json.loads(msg)
                h = data.get("header", {})
                n = h.get("name", "")
                if n == "TranscriptionResultChanged":
                    t = data.get("payload", {}).get("result", "")
                    if t.strip(): print(f"  ⏳ {t}")
                elif n == "SentenceEnd":
                    t = data.get("payload", {}).get("result", "")
                    idx = data.get("payload", {}).get("index", 0)
                    if t.strip():
                        print(f"  ✅ [{idx}] {t}")
                        final_lines.append(t)
                elif n == "TranscriptionCompleted":
                    print("WS: 完成")
                    done.set()
                    break
                elif n == "TaskFailed":
                    print(f"WS失败: {h.get('status_text')}")
                    done.set()
                    break
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                if not done.is_set(): print(f"WS错误: {e}")
                break

    t = threading.Thread(target=recv_loop, daemon=True)
    t.start()
    time.sleep(0.3)

    # === 实时速率发送 ===
    chunk_frames = 3200
    start_time = time.time()
    print(f"\n开始发送音频 (实时速率, 预计{dur:.0f}s)...")
    
    with wave.open(WAV_FILE, "rb") as wf:
        sent = 0; chunk_count = 0
        while True:
            chunk = wf.readframes(chunk_frames)
            if not chunk: break
            ws.send_binary(chunk)
            sent += len(chunk); chunk_count += 1
            
            # 实时速率: 200ms chunk → sleep 200ms
            time.sleep(0.2)
            
            if chunk_count % 25 == 0:  # 每5秒报进度
                elapsed = time.time() - start_time
                pct = min(100, elapsed / dur * 100)
                print(f"  进度: {pct:.0f}% ({elapsed:.0f}s/{dur:.0f}s)")

    elapsed = time.time() - start_time
    print(f"发送完毕 ({sent} bytes, {elapsed:.0f}s)")

    ws.send(json.dumps({
        "header": {
            "message_id": gen_32hex(), "task_id": task_id,
            "namespace": "SpeechTranscriber", "name": "StopTranscription",
            "appkey": APP_KEY,
        },
        "payload": {},
    }))

    done.wait(timeout=30)
    t.join(timeout=5)
    try: ws.close()
    except: pass

    return "\n".join(final_lines)

if __name__ == "__main__":
    print("=" * 50)
    print("NLS 实时语音识别")
    print("=" * 50)
    result = transcribe()
    print("\n" + "=" * 50)
    print("结果:")
    print("=" * 50)
    if result:
        print(result)
        out = os.path.splitext(WAV_FILE)[0] + "_transcript.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"\n保存: {out}")
    else:
        print("(无结果)")
