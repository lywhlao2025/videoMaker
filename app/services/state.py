import ast
import copy
import json
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod

from app.config import config
from app.models import const
from app.utils import utils


_PATCH_EXISTING_TASK_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 0 then
    return 0
end

for index = 1, #ARGV, 2 do
    redis.call("HSET", KEYS[1], ARGV[index], ARGV[index + 1])
end

return 1
"""


# Base class for state management
class BaseState(ABC):
    @abstractmethod
    def update_task(self, task_id: str, state: int, progress: int = 0, **kwargs):
        pass

    @abstractmethod
    def get_task(self, task_id: str):
        pass

    @abstractmethod
    def get_all_tasks(self, page: int, page_size: int):
        pass

    @abstractmethod
    def patch_task(self, task_id: str, **kwargs) -> bool:
        """只更新已有任务的指定字段；任务不存在时返回 False。"""
        pass


# Memory state management
class MemoryState(BaseState):
    def __init__(self):
        self._tasks = {}
        self._lock = threading.RLock()

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        with self._lock:
            tasks = [copy.deepcopy(task) for task in self._tasks.values()]
            total = len(tasks)
        return tasks[start:end], total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        with self._lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "state": state,
                "progress": progress,
                **kwargs,
            }

    def get_task(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id, None)
            return copy.deepcopy(task) if task is not None else None

    def patch_task(self, task_id: str, **kwargs) -> bool:
        # 异步发布只应补充发布状态，不能覆盖已经保存的视频、字幕等结果。
        # 在同一把锁内完成存在性判断和字段合并，也可避免任务删除后
        # 被后台线程重建。
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.update(copy.deepcopy(kwargs))
            return True

    def delete_task(self, task_id: str):
        with self._lock:
            self._tasks.pop(task_id, None)


class SQLiteState(BaseState):
    """跨线程、跨进程共享的轻量任务状态存储。"""

    def __init__(self, database_path: str):
        self.database_path = os.path.realpath(database_path)
        os.makedirs(os.path.dirname(self.database_path), exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_states (
                    task_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def _connect(self):
        return sqlite3.connect(self.database_path, timeout=30)

    @staticmethod
    def _serialize(task: dict) -> str:
        return json.dumps(
            task,
            ensure_ascii=False,
            separators=(",", ":"),
            default=lambda value: (
                value.model_dump(mode="json")
                if hasattr(value, "model_dump")
                else str(value)
            ),
        )

    @staticmethod
    def _deserialize(payload: str) -> dict:
        value = json.loads(payload)
        return value if isinstance(value, dict) else {}

    def get_all_tasks(self, page: int, page_size: int):
        offset = max(0, (page - 1) * page_size)
        with self._connect() as connection:
            total = int(
                connection.execute("SELECT COUNT(*) FROM task_states").fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT payload
                FROM task_states
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            ).fetchall()
        return [self._deserialize(row[0]) for row in rows], total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = max(0, min(100, int(progress)))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM task_states WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            task = self._deserialize(row[0]) if row else {}
            # 流水线每个阶段只提交本阶段字段。跨进程持久化时必须保留提交时间、
            # 主题和日志路径，否则 worker 的第一次进度更新会抹掉 WebUI 元数据。
            task.update(
                {
                    "task_id": task_id,
                    "state": state,
                    "progress": progress,
                    **kwargs,
                }
            )
            connection.execute(
                """
                INSERT INTO task_states(task_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (task_id, self._serialize(task), time.time()),
            )
            connection.commit()

    def get_task(self, task_id: str):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM task_states WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return self._deserialize(row[0]) if row else None

    def patch_task(self, task_id: str, **kwargs) -> bool:
        if not kwargs:
            return False

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM task_states WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                connection.rollback()
                return False

            task = self._deserialize(row[0])
            task.update(copy.deepcopy(kwargs))
            connection.execute(
                """
                UPDATE task_states
                SET payload = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (self._serialize(task), time.time(), task_id),
            )
            connection.commit()
        return True

    def delete_task(self, task_id: str):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_states WHERE task_id = ?",
                (task_id,),
            )


# Redis state management
class RedisState(BaseState):
    """
    Redis-backed task state.

    Trust boundary: Redis is expected to be private to this application. Task
    values are written by MoneyPrinterTurbo and converted back from strings for
    compatibility with existing state records. Do not expose this Redis database
    to untrusted writers without replacing deserialization with a stricter
    schema-based format.
    """

    def __init__(self, host="localhost", port=6379, db=0, password=None):
        import redis

        self._redis = redis.StrictRedis(host=host, port=port, db=db, password=password)

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        tasks = []
        cursor = 0
        total = 0
        while True:
            # Redis 数据库中除了任务 Hash，还可能存在 RedisTaskManager 使用的
            # List 队列。只扫描 Hash 可以避免对队列执行 HGETALL 时触发
            # WRONGTYPE，同时保证 total 只统计真正的任务记录。
            cursor, keys = self._redis.scan(
                cursor,
                count=page_size,
                _type="HASH",
            )
            batch_start = total
            batch_size = len(keys)
            total += batch_size

            # Redis SCAN 是分批返回 key。分页切片必须基于“当前批次起始索引”
            # 计算，而不能用累积后的 total 反推，否则第一页会切到空数组，
            # 第二页也可能只返回部分数据。
            if batch_start < end and total > start:
                slice_start = max(0, start - batch_start)
                slice_end = min(batch_size, end - batch_start)
                for key in keys[slice_start:slice_end]:
                    task_data = self._redis.hgetall(key)
                    task = {
                        k.decode("utf-8"): self._convert_to_original_type(v)
                        for k, v in task_data.items()
                    }
                    tasks.append(task)

            # 即使当前页已经取满，也要继续 SCAN 到 cursor=0，
            # 因为调用方需要准确 total 来渲染分页信息。
            if cursor == 0:
                break
        return tasks, total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        fields = {
            "task_id": task_id,
            "state": state,
            "progress": progress,
            **kwargs,
        }

        for field, value in fields.items():
            self._redis.hset(task_id, field, str(value))

    def get_task(self, task_id: str):
        task_data = self._redis.hgetall(task_id)
        if not task_data:
            return None

        task = {
            key.decode("utf-8"): self._convert_to_original_type(value)
            for key, value in task_data.items()
        }
        return task

    def patch_task(self, task_id: str, **kwargs) -> bool:
        if not kwargs:
            return False

        arguments = []
        for field, value in kwargs.items():
            arguments.extend((field, str(value)))

        # EXISTS 和 HSET 如果分成两条命令，后台发布线程与删除请求并发时，
        # HSET 可能在删除后重新创建一条残缺任务。Lua 脚本由 Redis 原子执行，
        # 可以保证任务不存在时不写入，且不会改变现有字段之外的数据。
        updated = self._redis.eval(
            _PATCH_EXISTING_TASK_SCRIPT,
            1,
            task_id,
            *arguments,
        )
        return bool(updated)

    def delete_task(self, task_id: str):
        self._redis.delete(task_id)

    @staticmethod
    def _convert_to_original_type(value):
        """
        Convert values written by this application back to common Python types.

        This compatibility parser assumes Redis is inside the application's
        trust boundary. If Redis can be written by untrusted clients, task state
        should move to a strict JSON/schema parser instead of open-ended literal
        conversion.
        """
        value_str = value.decode("utf-8")

        try:
            # try to convert byte string array to list
            return ast.literal_eval(value_str)
        except (ValueError, SyntaxError):
            pass

        if value_str.isdigit():
            return int(value_str)
        # Add more conversions here if needed
        return value_str


# Global state
_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)
_state_backend = os.getenv(
    "MPT_STATE_BACKEND",
    str(config.app.get("state_backend", "memory")),
).strip().lower()
_sqlite_database_path = os.getenv(
    "MPT_STATE_DB",
    os.path.join(utils.storage_dir(create=True), "task_state.sqlite3"),
)

state = (
    RedisState(
        host=_redis_host, port=_redis_port, db=_redis_db, password=_redis_password
    )
    if _enable_redis
    else (
        SQLiteState(_sqlite_database_path)
        if _state_backend == "sqlite"
        else MemoryState()
    )
)
