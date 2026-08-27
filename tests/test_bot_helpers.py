import unittest

from app.bot import GITHUB_URL, format_about_message, markdown_to_telegram_html, split_message


class SplitMessageTest(unittest.TestCase):
    def test_chunks_fit_telegram_limit(self) -> None:
        chunks = split_message(("строка\n" * 1200).strip(), limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))

    def test_model_markdown_becomes_telegram_html(self) -> None:
        source = "**Исправленный код**\n```python\nx = 0  # исправлено\n```\n- `x` начинается с нуля"
        rendered = markdown_to_telegram_html(source)
        self.assertIn("<b>Исправленный код</b>", rendered)
        self.assertIn('<pre><code class="language-python">', rendered)
        self.assertIn("x = 0  # исправлено", rendered)
        self.assertIn("• <code>x</code>", rendered)
        self.assertNotIn("```", rendered)

    def test_about_message_contains_public_project_details(self) -> None:
        rendered = format_about_message(42)
        self.assertIn("Версия:", rendered)
        self.assertIn("Yujio", rendered)
        self.assertIn("Решено задач:</b> 42", rendered)
        self.assertIn(GITHUB_URL, rendered)


if __name__ == "__main__":
    unittest.main()
