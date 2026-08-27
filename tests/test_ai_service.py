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


class ContinuingResponses:
    def __init__(self) -> None:
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            return SimpleNamespace(
                output_text="Первая часть ",
                usage=SimpleNamespace(input_tokens=10, output_tokens=20),
                status="incomplete",
                incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                output=[{
                    "type": "message",
                    "role": "assistant",
                    "status": "incomplete",
                    "content": [{"type": "output_text", "text": "Первая часть "}],
                }],
            )
        return SimpleNamespace(
            output_text="и окончание",
            usage=SimpleNamespace(input_tokens=30, output_tokens=40),
            status="completed",
            incomplete_details=None,
            output=[],
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

    def test_incomplete_answer_is_continued_automatically(self) -> None:
        service = AIService.__new__(AIService)
        responses = ContinuingResponses()
        service.client = SimpleNamespace(responses=responses)
        service.model = "test-model"
        service.max_output_tokens = 500
        service.input_rate = 1.0
        service.output_rate = 2.0

        answer = service.answer("Реши все задачи")

        self.assertEqual(answer.text, "Первая часть и окончание")
        self.assertEqual((answer.input_tokens, answer.output_tokens), (40, 60))
        self.assertEqual(len(responses.requests), 2)
        continuation = responses.requests[1]["input"][-1]["content"][0]["text"]
        self.assertIn("Продолжи ровно с места остановки", continuation)

    def test_extract_image_tasks_uses_extraction_prompt(self) -> None:
        service = AIService.__new__(AIService)
        responses = FakeResponses()
        service.client = SimpleNamespace(responses=responses)
        service.model = "test-model"
        service.max_output_tokens = 500
        service.input_rate = 1.0
        service.output_rate = 2.0

        service.extract_image_tasks(b"photo")

        self.assertIn("Не решай задачи", responses.request["instructions"])
        content = responses.request["input"][0]["content"]
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["detail"], "high")

    def test_photo_session_answer_contains_recognized_tasks_and_request(self) -> None:
        service = AIService.__new__(AIService)
        responses = FakeResponses()
        service.client = SimpleNamespace(responses=responses)
        service.model = "test-model"
        service.max_output_tokens = 500
        service.input_rate = 1.0
        service.output_rate = 2.0

        service.answer_photo_session(
            "Задача 1: 2 + 2", "Объясни подробнее", "Реши задачу 1"
        )

        prompt = responses.request["input"][0]["content"][0]["text"]
        self.assertIn("Задача 1: 2 + 2", prompt)
        self.assertIn("Объясни подробнее", prompt)
        self.assertIn("Предыдущий запрос в этой фото-сессии:\nРеши задачу 1", prompt)
        self.assertIn("Не решай остальные номера", prompt)


if __name__ == "__main__":
    unittest.main()
