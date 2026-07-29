from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from core.errors import BusinessError
from core.standard_reply import accepted, success


def utc_now_text():
    return datetime.now(timezone.utc).isoformat()


class ProjectAsyncTaskService:
    FINAL = {"SUCCESS", "FAILED", "CANCELLED"}

    def __init__(self, repository):
        self.repository = repository

    def accept(self, *, action, trace_id, idempotency_key, request_payload, project_id=None, workflow_instance_id=None, node_id=None, source_message_id=None, task_id=None):
        existing = self.repository.get_async_task_by_idempotency(idempotency_key)
        if existing is not None:
            return accepted(trace_id=trace_id, data={"task": existing, "status_query_action":"project.task.query"}, message="任务已受理（幂等重放）")
        now = utc_now_text()
        task = {
            "task_id": task_id or ("TASK_" + uuid4().hex[:16].upper()),
            "action": action,
            "project_id": project_id,
            "workflow_instance_id": workflow_instance_id,
            "node_id": node_id,
            "task_status": "ACCEPTED",
            "progress_percent": 0,
            "status_message": "任务已登记，等待后续办理或流程回调",
            "request_payload": request_payload,
            "source_message_id": source_message_id,
            "idempotency_key": idempotency_key,
            "trace_id": trace_id,
            "created_at": now,
            "updated_at": now,
        }
        self.repository.create_async_task(task)
        return accepted(
            trace_id=trace_id,
            data={"task": self.repository.get_async_task(task["task_id"]), "status_query_action":"project.task.query", "progress_callback_action":"project.task.progress.record", "final_callback_action":"project.task.final.callback"},
            message="长任务已受理，后续按 task_id 查询进度和最终结果",
        )

    def progress(self, *, task_id, progress_percent, status_message, trace_id, message_id=None, parent_message_id=None):
        task = self._require(task_id)
        self._validate_parent(task, parent_message_id)
        if task["task_status"] in self.FINAL:
            raise BusinessError("TASK_ALREADY_FINAL", "任务已经终态，不能再更新进度", http_status=409)
        progress = int(progress_percent)
        if progress < task["progress_percent"] or progress < 0 or progress > 99:
            raise BusinessError("INVALID_TASK_PROGRESS", "进度必须在当前进度至 99 之间", http_status=400)
        self.repository.update_async_task(task_id=task_id, task_status="RUNNING", progress_percent=progress, status_message=status_message)
        self.repository.append_workflow_callback({"task_id":task_id,"callback_type":"PROGRESS","callback_status":"RUNNING","progress_percent":progress,"result":{"status_message":status_message},"message_id":message_id,"parent_message_id":parent_message_id,"trace_id":trace_id})
        return success(trace_id=trace_id, data={"task":self.repository.get_async_task(task_id),"callbacks":self.repository.get_workflow_callbacks(task_id)}, message="任务进度已登记")

    def complete(self, *, task_id, callback_status, result, trace_id, message_id=None, parent_message_id=None):
        task = self._require(task_id)
        self._validate_parent(task, parent_message_id)
        status = str(callback_status).upper()
        if status not in self.FINAL:
            raise BusinessError("INVALID_FINAL_STATUS", "最终状态只能是 SUCCESS、FAILED 或 CANCELLED", http_status=400)
        if task["task_status"] in self.FINAL:
            if task["final_result"] == result and task["task_status"] == status:
                return success(trace_id=trace_id, data={"task":task,"callbacks":self.repository.get_workflow_callbacks(task_id)}, message="最终回调幂等重放")
            raise BusinessError("TASK_FINAL_CONFLICT", "任务已经终态且最终结果不一致", http_status=409)
        self.repository.update_async_task(task_id=task_id, task_status=status, progress_percent=100, status_message="任务已完成" if status=="SUCCESS" else "任务办理失败", final_result=result)
        self.repository.append_workflow_callback({"task_id":task_id,"callback_type":"FINAL","callback_status":status,"progress_percent":100,"result":result,"message_id":message_id,"parent_message_id":parent_message_id,"trace_id":trace_id})
        return success(trace_id=trace_id, data={"task":self.repository.get_async_task(task_id),"callbacks":self.repository.get_workflow_callbacks(task_id)}, message="任务最终回调已登记")

    def query(self, *, task_id, trace_id):
        task = self._require(task_id)
        return success(trace_id=trace_id, data={"task":task,"callbacks":self.repository.get_workflow_callbacks(task_id)}, message="任务状态查询成功")

    def _require(self, task_id):
        task = self.repository.get_async_task(task_id)
        if task is None:
            raise BusinessError("TASK_NOT_FOUND", "异步任务不存在：" + str(task_id), http_status=404)
        return task

    @staticmethod
    def _validate_parent(task, parent_message_id):
        if task.get("source_message_id") and parent_message_id != task["source_message_id"]:
            raise BusinessError("CALLBACK_PARENT_MESSAGE_MISMATCH", "回调 parent_message_id 与原派发消息不匹配", http_status=409)
