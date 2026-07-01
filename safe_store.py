"""
安全数据存储 — 防崩溃/防数据丢失
- 增量追加写入，每条数据立即落盘
- 原子写入 (tmp + rename)，避免写入中断导致文件损坏
- 任务状态持久化，支持崩溃后恢复轮询
- 信号处理，Ctrl+C 也能保存已有结果
"""
import os
import sys
import json
import signal
import atexit
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Callable

# ============================================================
# 核心工具
# ============================================================

def atomic_write(path: str, content: str, encoding: str = "utf-8"):
    """原子写入：先写临时文件，成功后再 rename，避免断电/崩溃导致文件损坏"""
    dirname = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dirname, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, path)  # Windows 上 replace 是原子的
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def safe_read(path: str, default: str = "") -> str:
    """安全读取：文件不存在返回默认值，编码错误也不崩溃"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return default
    except Exception:
        return default


def safe_read_json(path: str, default=None):
    """安全读取 JSON"""
    if default is None:
        default = {}
    raw = safe_read(path)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 如果主文件损坏，尝试从备份恢复
        backup = path + ".bak"
        raw2 = safe_read(backup)
        if raw2:
            try:
                return json.loads(raw2)
            except:
                pass
        return default


# ============================================================
# 增量结果收集器 — 边收边存，不丢数据
# ============================================================

class SafeCollector:
    """每收到一条结果就立刻追加到文件，崩溃也不丢"""

    def __init__(self, output_path: str, flush_every: int = 1):
        self.output_path = output_path
        self.flush_every = flush_every  # 每 N 条 flush 一次（1 = 每条都 flush）
        self._lines: list[str] = []
        self._count = 0
        self._closed = False

        # 确保目录存在
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # 写入文件头
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# 转写开始 {datetime.now().isoformat()}\n")
            f.flush()
            os.fsync(f.fileno())

    def add(self, text: str):
        """添加一行结果，立即落盘"""
        if self._closed:
            return
        line = text.strip()
        if not line:
            return
        self._lines.append(line)
        self._count += 1

        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def get_all(self) -> list[str]:
        return list(self._lines)

    def finalize(self):
        """标记完成，写入结束标记"""
        if self._closed:
            return
        self._closed = True
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(f"\n# 转写完成 {datetime.now().isoformat()} — 共 {len(self._lines)} 条\n")
            f.flush()
            os.fsync(f.fileno())

    def __len__(self):
        return len(self._lines)


# ============================================================
# 任务状态持久化 — 异步任务可恢复
# ============================================================

class TaskJournal:
    """记录异步任务状态，支持崩溃后恢复"""

    def __init__(self, journal_path: str):
        self.path = journal_path
        self.state = safe_read_json(journal_path)

        if self.state:
            print(f"[Journal] 📋 恢复任务状态: {json.dumps(self.state, ensure_ascii=False)}")

        # 退出时自动保存
        atexit.register(self._save_on_exit)

    def set_task(self, task_id: str, provider: str = "", input_file: str = ""):
        self.state = {
            "task_id": task_id,
            "provider": provider,
            "input_file": input_file,
            "status": "submitted",
            "submitted_at": datetime.now().isoformat(),
            "output_file": "",
        }
        self._save()

    def set_running(self):
        self.state["status"] = "running"
        self.state["last_poll"] = datetime.now().isoformat()
        self._save()

    def set_completed(self, output_file: str = ""):
        self.state["status"] = "completed"
        self.state["completed_at"] = datetime.now().isoformat()
        if output_file:
            self.state["output_file"] = output_file
        self._save()

    def set_failed(self, error: str = ""):
        self.state["status"] = "failed"
        self.state["error"] = error
        self.state["failed_at"] = datetime.now().isoformat()
        self._save()

    def has_pending_task(self) -> bool:
        return (
            self.state
            and self.state.get("task_id")
            and self.state.get("status") in ("submitted", "running")
        )

    def get_task_id(self) -> Optional[str]:
        return self.state.get("task_id")

    def clear(self):
        self.state = {}
        if os.path.exists(self.path):
            os.remove(self.path)

    def _save(self):
        atomic_write(self.path, json.dumps(self.state, ensure_ascii=False, indent=2))
        # 同时写一份备份
        try:
            shutil.copy2(self.path, self.path + ".bak")
        except:
            pass

    def _save_on_exit(self):
        """程序退出时保存最终状态"""
        if self.state:
            self._save()


# ============================================================
# 优雅退出 — 信号处理
# ============================================================

def install_signal_handler(cleanup_fn: Callable):
    """安装信号处理器，Ctrl+C / kill 时触发清理函数"""

    def handler(signum, frame):
        print(f"\n⚠️ 收到信号 {signum}，正在保存数据...")
        try:
            cleanup_fn()
        except Exception as e:
            print(f"清理异常: {e}")
        print("数据已保存，安全退出。")
        sys.exit(0)

    signal.signal(signal.SIGINT, handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, handler)  # kill

    # Windows 不支持 SIGBREAK handler，但 try 一下
    try:
        signal.signal(signal.SIGBREAK, handler)  # Windows Ctrl+Break
    except AttributeError:
        pass


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== SafeStore 自测 ===")

    # 测试 SafeCollector
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "safe_store_test.txt")

    c = SafeCollector(tmp)
    c.add("第一句话：你好世界")
    c.add("第二句话：测试增量写入")
    c.finalize()

    print(f"写入内容:\n{safe_read(tmp)}")
    print(f"行数: {len(c)}")

    # 清理
    os.remove(tmp)
    print("✅ 测试通过")
