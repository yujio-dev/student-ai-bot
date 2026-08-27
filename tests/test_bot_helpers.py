import unittest

from app.ai_service import INSTRUCTIONS, PRODUCT_CAPABILITIES
from app.bot import (
    GITHUB_URL,
    format_about_message,
    format_start_message,
    is_photo_followup,
    markdown_to_telegram_html,
    split_message,
)


class SplitMessageTest(unittest.TestCase):
    def test_chunks_fit_telegram_limit(self) -> None:
        chunks = split_message(("строка\n" * 1200).strip(), limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))

    def test_model_markdown_becomes_telegram_html(self) -> None:
        source = (
            "**Исправленный код** — готово\n```python\nx = 0  # исправлено\n```\n"
            "- `x` начинается с нуля"
        )
        rendered = markdown_to_telegram_html(source)
        self.assertIn("<b>Исправленный код</b>", rendered)
        self.assertIn('<pre><code class="language-python">', rendered)
        self.assertIn("x = 0  # исправлено", rendered)
        self.assertIn("• <code>x</code>", rendered)
        self.assertNotIn("```", rendered)
        self.assertNotIn("—", rendered)
        self.assertNotIn("–", rendered)

    def test_start_message_explains_text_and_photo_tasks(self) -> None:
        rendered = format_start_message()
        self.assertIn("Текстом - первый распознанный разбор бесплатный", rendered)
        self.assertIn("Одной фотографией - 100 Stars или 5", rendered)
        self.assertIn("/buy", rendered)
        self.assertIn("/newtask", rendered)
        self.assertNotIn("—", rendered)
        self.assertNotIn("–", rendered)

    def test_about_message_contains_public_project_details(self) -> None:
        rendered = format_about_message(42)
        self.assertIn("Версия:", rendered)
        self.assertIn("Yujio", rendered)
        self.assertIn("Решено задач:</b> 42", rendered)
        self.assertIn(GITHUB_URL, rendered)

    def test_product_prompt_does_not_promise_unavailable_features(self) -> None:
        self.assertIn("не создаёт изображения, DOCX, PPTX или PDF", PRODUCT_CAPABILITIES)
        self.assertIn("Никогда не придумывай", PRODUCT_CAPABILITIES)

    def test_ai_prompts_forbid_long_dashes(self) -> None:
        prompts = INSTRUCTIONS + PRODUCT_CAPABILITIES
        self.assertIn("U+2014", prompts)
        self.assertIn("U+2013", prompts)
        self.assertNotIn("—", prompts)
        self.assertNotIn("–", prompts)

    def test_answer_format_starts_with_structured_given_data(self) -> None:
        self.assertIn("1. **Дано**", INSTRUCTIONS)
        self.assertIn("исходные значения, условия, ограничения", INSTRUCTIONS)
        self.assertNotIn("Что пошло не так", INSTRUCTIONS)

    def test_clear_photo_followups_are_detected(self) -> None:
        self.assertTrue(is_photo_followup("Теперь реши задачу 2 и задачу 3"))
        self.assertTrue(is_photo_followup("Разбери 2 и 3 задачи"))
        self.assertTrue(is_photo_followup("Объясни вторую подробнее"))
        self.assertTrue(is_photo_followup("Продолжи разбор"))
        self.assertFalse(is_photo_followup("Привет, сколько стоит бот?"))


if __name__ == "__main__":
    unittest.main()
