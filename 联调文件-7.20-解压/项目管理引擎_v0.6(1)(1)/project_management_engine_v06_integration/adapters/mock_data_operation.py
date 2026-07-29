class MockDataOperation:
    def persist_reference(self, *, project_id: str, data: dict) -> dict:
        return {
            "status": "success",
            "project_id": project_id,
            "data_ref": f"DATAREF_PROJECT_{project_id}",
            "mock": True,
        }
