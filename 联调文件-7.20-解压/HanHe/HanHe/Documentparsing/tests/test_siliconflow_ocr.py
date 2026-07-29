from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx
from PIL import Image

from doc_table_engine.siliconflow_ocr import SiliconFlowPaddleOCRProvider


class SiliconFlowOCRTests(unittest.TestCase):
    def test_image_request_and_markdown_table_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "invoice.png"
            Image.new("RGB", (40, 30), "white").save(image_path)
            requests: list[dict] = []

            def respond(request: httpx.Request) -> httpx.Response:
                payload = json.loads(request.content)
                requests.append(payload)
                return httpx.Response(200, json={"choices": [{"message": {"content": (
                    "发票正文\n\n| 项目 | 金额 |\n| --- | --- |\n| 住宿 | 100 |"
                )}}]})

            provider = self._provider(respond)
            try:
                result = provider.recognize(image_path, "f" * 64)
            finally:
                provider.close()

            self.assertEqual(requests[0]["model"], "PaddlePaddle/PaddleOCR-VL-1.5")
            image_url = requests[0]["messages"][0]["content"][0]["image_url"]["url"]
            self.assertTrue(image_url.startswith("data:image/png;base64,"))
            self.assertEqual(requests[0]["messages"][0]["content"][1]["text"], "OCR:")
            self.assertEqual(result.text_blocks[0].raw_value, "发票正文")
            self.assertEqual(result.text_blocks[0].source.page, 1)
            self.assertEqual(result.text_blocks[0].source.bbox, (0.0, 0.0, 1000.0, 1000.0))
            self.assertEqual(len(result.tables), 1)
            self.assertEqual(result.tables[0].values[-1].raw_value, "100")
            self.assertEqual(result.ai_structured["provider"], "SiliconFlow")

    def test_pdf_is_rendered_and_sent_one_page_per_request(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "two-pages.pdf"
            document = pymupdf.open()
            document.new_page().insert_text((72, 72), "page one")
            document.new_page().insert_text((72, 72), "page two")
            document.save(pdf_path)
            document.close()
            request_count = 0

            def respond(_: httpx.Request) -> httpx.Response:
                nonlocal request_count
                request_count += 1
                return httpx.Response(200, json={
                    "choices": [{"message": {"content": f"recognized page {request_count}"}}]
                })

            provider = self._provider(respond)
            try:
                result = provider.recognize(pdf_path, "a" * 64)
            finally:
                provider.close()

            self.assertEqual(request_count, 2)
            self.assertEqual([block.source.page for block in result.text_blocks], [1, 2])
            self.assertEqual(result.ai_structured["page_count"], 2)

    def test_api_key_is_required_only_when_ocr_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "scan.png"
            Image.new("RGB", (10, 10), "white").save(image_path)
            provider = SiliconFlowPaddleOCRProvider(None)
            try:
                with self.assertRaisesRegex(RuntimeError, "SILICONFLOW_API_KEY"):
                    provider.recognize(image_path, "b" * 64)
            finally:
                provider.close()

    @staticmethod
    def _provider(responder) -> SiliconFlowPaddleOCRProvider:
        provider = SiliconFlowPaddleOCRProvider("test-key", default_confidence=0.80)
        provider.client.close()
        provider.client = httpx.Client(
            transport=httpx.MockTransport(responder),
            headers={"Authorization": "Bearer test-key"},
        )
        return provider


if __name__ == "__main__":
    unittest.main()
