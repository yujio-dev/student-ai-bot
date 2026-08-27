import unittest
from types import SimpleNamespace

from app.ai_service import AIService


class FakeResponses:
    def __init__(self) -> None:
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            output_text="Готово",
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        )


class AIServiceImageTest(unittest.TestCase):
    def test_answer_image_sends_base64_image_and_caption(self) -> None:
        service = AIService.__new__(AIService)
        responses = FakeResponses()
        service.client = SimpleNamespace(responses=responses)
        service.model = "test-model"
        service.max_output_tokens = 500
        service.input_rate = 1.0
        service.output_rate = 2.0

        answer = service.answer_image(b"image", "Реши второй пункт")

        content = responses.request["input"][0]["content"]
        self.assertIn("Реши второй пункт", content[0]["text"])
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["detail"], "high")
        self.assertEqual(content[1]["image_url"], "data:image/jpeg;base64,aW1hZ2U=")
        self.assertEqual((answer.text, answer.input_tokens, answer.output_tokens), ("Готово", 10, 20))


if __name__ == "__main__":
    unittest.main()
