"""脱敏服务 —— 简化版，直接接受文本而非 Payload 对象。"""
from app.engines.masking.masking_engine import ProductizedMaskingEngine, ProductizedMaskingResult
from app.repositories.json_store import JsonStore

MaskingResult = ProductizedMaskingResult


class DataMaskingEngine:
    def __init__(self, store: JsonStore) -> None:
        self.engine = ProductizedMaskingEngine(store)

    def mask(self, input_text: str = "", output_text: str = "") -> ProductizedMaskingResult:
        return self.engine.mask(input_text=input_text, output_text=output_text)
