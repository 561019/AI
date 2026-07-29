class MockWorkflowCallback:
    def send_result(self, *, trace_id: str, task_id: str | None, result: dict) -> dict:
        return {
            "callback_status": "accepted",
            "trace_id": trace_id,
            "task_id": task_id,
            "result": result,
            "mock": True,
        }
