import os
import threading
from collections import deque
from datetime import datetime

from loguru import logger

from app.config import config
from app.controllers.manager.base_manager import TaskQueueFullError
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm
from app.utils import utils
from app.utils.logging_utils import format_log_record


_task_logs_lock = threading.RLock()
_MAX_LOG_RECORDS_PER_TASK = 1000
# Streamlit 无法由后台线程直接推送组件更新，只能通过 Fragment 轮询。0.5 秒
# 足以让 WebUI 日志接近终端实时输出，又不会像高频刷新那样持续占用浏览器资源。
TASK_LOG_REFRESH_INTERVAL_SECONDS = 0.5


def _job_root() -> str:
    configured_root = os.getenv("MPT_WEBUI_JOB_ROOT", "").strip()
    if configured_root:
        os.makedirs(configured_root, exist_ok=True)
        return os.path.realpath(configured_root)
    return utils.storage_dir("webui_jobs", create=True)


def task_log_path(task_id: str) -> str:
    return os.path.join(utils.task_dir(task_id), "task.log")


def _append_task_log(task_id: str, message: str) -> None:
    """把日志追加到任务目录，页面断开或进程重启后仍可读取。"""
    normalized_message = message.rstrip()
    if not normalized_message:
        return

    log_path = task_log_path(task_id)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with _task_logs_lock:
        with open(log_path, mode="a", encoding="utf-8") as handle:
            for line in normalized_message.splitlines():
                handle.write(f"[task_id={task_id}] {line}\n")
            handle.flush()


def get_task_logs(
    task_id: str,
    limit: int = _MAX_LOG_RECORDS_PER_TASK,
) -> list[str]:
    """从任务日志尾部返回有限快照，避免大日志拖慢页面。"""
    log_path = task_log_path(task_id)
    if not os.path.isfile(log_path):
        return []

    bounded_limit = max(1, min(int(limit), _MAX_LOG_RECORDS_PER_TASK))
    with _task_logs_lock:
        with open(log_path, mode="r", encoding="utf-8", errors="replace") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=bounded_limit)]


def _run_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool,
    voice_preview: dict | None = None,
) -> dict:
    """
    在后台线程中执行现有视频流水线。

    Loguru 的 sink 是进程级资源，因此必须按当前工作线程过滤。否则同时运行的
    API 任务或其它页面日志会混入当前任务。页面只读取普通列表快照，不会从后台
    线程访问 Streamlit session_state，从根源上避免刷新时的 delta 路径错乱。
    """
    log_handler_id = None
    worker_thread_id = threading.get_ident()
    try:
        _append_task_log(
            task_id,
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | INFO | "
            "background worker - task started",
        )
        if capture_logs:
            log_handler_id = logger.add(
                lambda message: _append_task_log(task_id, str(message)),
                level="DEBUG",
                format=format_log_record,
                colorize=False,
                filter=lambda record: record["thread"].id == worker_thread_id,
            )

        # 完整任务仍使用原来的配置锁，防止另一个 WebUI 会话在生成中途修改
        # Provider、密钥等进程级配置，造成同一条视频前后使用不同设置。
        with config.runtime_config_lock():
            result = tm.start(
                task_id=task_id,
                params=params,
                voice_preview=voice_preview,
            )
        _append_task_log(
            task_id,
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | INFO | "
            "background worker - task finished",
        )
        return result
    except Exception as exc:
        # tm.start 已负责把流水线异常转换成失败状态；这里额外保护日志 sink、
        # 配置锁等 WebUI 包装层。任何后台线程异常都必须留下终态，不能让任务
        # 管理器在工作线程退出后仍永久显示“生成中”。
        error = f"{type(exc).__name__}: {exc}"
        failure = {
            "task_id": task_id,
            "state": const.TASK_STATE_FAILED,
            "progress": 0,
            "failed_stage": "webui_worker",
            "error": error,
        }
        sm.state.update_task(
            task_id,
            state=failure["state"],
            progress=failure["progress"],
            failed_stage=failure["failed_stage"],
            error=failure["error"],
        )
        logger.exception(
            f"unexpected WebUI generation worker failure, "
            f"task_id={task_id}, error={exc}"
        )
        _append_task_log(
            task_id,
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ERROR | "
            f"background worker - {error}",
        )
        return failure
    finally:
        if log_handler_id is not None:
            try:
                logger.remove(log_handler_id)
            except ValueError:
                logger.debug(
                    f"WebUI task log handler already removed: task_id={task_id}"
                )


def submit_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool = True,
    voice_preview: dict | None = None,
) -> None:
    """
    持久化 WebUI 视频生成任务，调用后立即返回。

    任务状态和队列文件都必须在页面本次脚本执行结束前落盘。独立 worker 服务
    随后领取任务，因此浏览器关闭、WebSocket 断开和 Streamlit rerun 都不会
    终止流水线。
    """
    task_params = params.model_copy(deep=True)
    # 预览载荷只包含不可变音频路径、参数快照和只读字幕时间轴。复制外层字典，
    # 避免页面后续 rerun 替换缓存字段时影响已经提交到后台队列的任务。
    voice_preview_snapshot = dict(voice_preview) if voice_preview else None
    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_PROCESSING,
        progress=0,
        video_subject=task_params.video_subject or task_params.video_script or task_id,
        submitted_at=datetime.now().isoformat(timespec="seconds"),
        log_file=task_log_path(task_id),
    )
    try:
        from app.services import webui_worker

        job_root = _job_root()
        pending_dir = os.path.join(job_root, "pending")
        running_dir = os.path.join(job_root, "running")
        os.makedirs(pending_dir, exist_ok=True)
        os.makedirs(running_dir, exist_ok=True)
        queued_count = sum(
            1
            for directory in (pending_dir, running_dir)
            for name in os.listdir(directory)
            if name.endswith(".pkl")
        )
        max_queued_tasks = max(1, int(config.app.get("max_queued_tasks", 100)))
        if queued_count >= max_queued_tasks:
            raise TaskQueueFullError("task queue is full, please try again later")

        job_path = os.path.join(pending_dir, f"{task_id}.pkl")
        webui_worker.write_job(
            job_path,
            {
                "task_id": task_id,
                "params": task_params,
                "capture_logs": capture_logs,
                "voice_preview": voice_preview_snapshot,
            },
        )
        _append_task_log(
            task_id,
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | INFO | "
            "webui - task queued for background worker",
        )
    except Exception as exc:
        # 调度失败与流水线失败一样必须成为可查询状态，避免任务管理器永久显示
        # “生成中”。保留异常类型便于从 Docker 或本机日志快速定位队列问题。
        error = f"{type(exc).__name__}: {exc}"
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=0,
            failed_stage="scheduling",
            error=error,
        )
        logger.exception(
            f"failed to submit WebUI generation task, task_id={task_id}, error={exc}"
        )
        raise
