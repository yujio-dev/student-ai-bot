from __future__ import annotations

import base64
from dataclasses import dataclass

from openai import OpenAI


INSTRUCTIONS = """
Ты - доброжелательный учебный наставник. Помогай студентам разбирать задачи по разным
предметам: математике, физике, химии, программированию, языкам и другим дисциплинам.
Сам определи предмет и подходящий формат решения. Отвечай по-русски, если пользователь
явно не выбрал другой язык. Пиши живо и поддерживающе: не просто выдавай результат,
а помогай студенту понять ход решения и уверенно объяснить его преподавателю.

Формат ответа:
1. **Дано** - структурированно перечисли всю информацию, которую передал пользователь
   и которая пригодится в решении: исходные значения, условия, ограничения, обозначения
   и то, что требуется найти или сделать. Для фотографии сначала аккуратно распознай
   условие. Не добавляй фактов, которых нет у пользователя. Если задач несколько,
   раздели данные по номерам задач.
2. **Решение** - вычисления, рассуждение, исправленный текст или полный рабочий код,
   в зависимости от предмета. Если исправляешь код, помести его в Markdown-блок и в
   конце каждой реально исправленной строки добавь короткий комментарий на языке
   программы, например `# исправлено: начинаем с нуля`. Не комментируй неизменённые
   очевидные строки.
3. **Разбираем по шагам** - объясни каждое важное действие, формулу или исправление:
   что мы делаем, почему и как это ведёт к ответу. Не пропускай промежуточную логику.
   Обычно нужно 4-8 содержательных абзацев, но не раздувай элементарный ответ.
4. **Как проверить** - 2-4 конкретных теста, включая обычный и граничный случай,
   с ожидаемым результатом.
5. **Что сказать на защите** - 2-4 предложения, которыми студент сможет своими
   словами объяснить основную идею решения.

Не выдумывай результат запуска кода. Если данных не хватает, назови одно точное
уточнение. Не выполняй контрольную или экзамен за пользователя скрытно: помоги
понять и самостоятельно защитить решение.
Никогда не используй символы Unicode U+2014 и U+2013. Во всех предложениях ставь
только обычный дефис `-`, даже если по правилам типографики требуется тире.
Используй только простой Markdown: `**жирный текст**`, одиночные обратные кавычки для
короткого кода и тройные обратные кавычки для блоков кода. Не используй таблицы.
""".strip()


PRODUCT_CAPABILITIES = """
Фактические функции бота:
- бот решает учебные задачи, отправленные текстом;
- бот отдельно обрабатывает одну фотографию учебной задачи после подтверждения цены:
  100 Telegram Stars или 5 оплаченных разборов;
- бот пока не принимает PDF и другие файлы и не создаёт изображения, DOCX, PPTX или PDF;
- бесплатный первый текстовый разбор не оплачивает фоторазбор.
Никогда не придумывай и не обещай функции, которых нет в этом списке. Если пользователь
спрашивает о недоступной функции, честно скажи, что она пока не реализована, и направь
в /faq. Не утверждай, что бот уже умеет что-либо только потому, что это технически можно
добавить в будущем.
Никогда не используй символы Unicode U+2014 и U+2013. Используй только обычный `-`.
""".strip()


@dataclass(frozen=True)
class AIAnswer:
    text: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class RouteResult:
    is_task: bool
    reply: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class AIService:
    def __init__(self, api_key: str, model: str, max_output_tokens: int,
                 input_usd_per_million: float, output_usd_per_million: float) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.input_rate = input_usd_per_million
        self.output_rate = output_usd_per_million

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_rate + output_tokens * self.output_rate) / 1_000_000

    @staticmethod
    def _incomplete_reason(response) -> str | None:
        details = getattr(response, "incomplete_details", None)
        if isinstance(details, dict):
            return details.get("reason")
        return getattr(details, "reason", None)

    @staticmethod
    def _output_items(response) -> list:
        items = []
        for item in getattr(response, "output", []) or []:
            if hasattr(item, "model_dump"):
                items.append(item.model_dump(exclude_none=True))
            else:
                items.append(item)
        return items

    def _complete_answer(self, input_items: list, min_output_tokens: int = 0) -> AIAnswer:
        """Continue responses that stop only because they reached the output limit."""
        history = list(input_items)
        text_parts: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0
        max_tokens = max(self.max_output_tokens, min_output_tokens)

        for _ in range(4):
            response = self.client.responses.create(
                model=self.model,
                instructions=INSTRUCTIONS,
                input=history,
                max_output_tokens=max_tokens,
                reasoning={"effort": "low"},
                text={"verbosity": "high"},
                store=False,
            )
            text_parts.append(response.output_text)
            if response.usage:
                total_input_tokens += int(response.usage.input_tokens)
                total_output_tokens += int(response.usage.output_tokens)

            if not (
                getattr(response, "status", "completed") == "incomplete"
                and self._incomplete_reason(response) == "max_output_tokens"
            ):
                return AIAnswer(
                    "".join(text_parts),
                    total_input_tokens,
                    total_output_tokens,
                    self._cost(total_input_tokens, total_output_tokens),
                )

            history.extend(self._output_items(response))
            history.append({
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "Продолжи ровно с места остановки. Не повторяй уже написанное. "
                        "Обязательно доведи все задачи и все разделы ответа до конца."
                    ),
                }],
            })

        raise RuntimeError("AI response remained incomplete after automatic continuations")

    def route(self, message: str) -> RouteResult:
        """Decide whether a message is a billable academic task before consuming credit."""
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                "Определи тип сообщения для учебного Telegram-бота. Первая строка должна "
                "быть ровно TASK, если пользователь просит решить, проверить, объяснить, "
                "перевести или разобрать конкретное учебное задание. Первая строка должна "
                "быть CHAT для приветствия, благодарности, разговора или вопроса о функциях, "
                "цене и правилах бота. Для TASK больше ничего не пиши. Для CHAT после первой "
                "строки ответь дружелюбно и по делу максимум тремя предложениями; по вопросам "
                "о продукте упомяни команду /faq. Не решай учебные задачи в режиме CHAT.\n\n"
                + PRODUCT_CAPABILITIES
            ),
            input=message,
            max_output_tokens=140,
            reasoning={"effort": "low"},
            text={"verbosity": "low"},
            store=False,
        )
        raw = response.output_text.strip()
        first, _, rest = raw.partition("\n")
        is_task = first.strip().upper() == "TASK"
        reply = rest.strip() if not is_task else ""
        if not is_task and not reply:
            reply = "Я готов помочь с учебной задачей. О возможностях и оплате рассказывает /faq."
        input_tokens = int(response.usage.input_tokens if response.usage else 0)
        output_tokens = int(response.usage.output_tokens if response.usage else 0)
        return RouteResult(
            is_task, reply, input_tokens, output_tokens, self._cost(input_tokens, output_tokens)
        )

    def answer(self, question: str) -> AIAnswer:
        return self._complete_answer([{
            "role": "user",
            "content": [{"type": "input_text", "text": question}],
        }])

    def answer_image(self, image_bytes: bytes, caption: str = "") -> AIAnswer:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        prompt = (
            "Распознай условие учебной задачи на фотографии и реши её по инструкциям. "
            "Если часть условия неразборчива или обрезана, не додумывай её: точно укажи, "
            "какую часть нужно переснять."
        )
        if caption.strip():
            prompt += f"\nКомментарий пользователя: {caption.strip()}"
        return self._complete_answer([{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{encoded}",
                    "detail": "high",
                },
            ],
        }], min_output_tokens=4000)
