class L1ModelClient:
    """Placeholder for calls to L1 model scheduling."""

    async def call_model(self, prompt: str, model_tier: str) -> str:
        raise NotImplementedError("L1 model scheduling integration is not implemented yet.")

    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError("Embedding gateway integration is not implemented yet.")
