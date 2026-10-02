import re

# Ссылки: http(s), www, а также домены вида "site.ru"
URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|\S+\.(?:ru|com|net|org|io|me|tv|info|app|dev|co)\b)",
    re.IGNORECASE,
)

# Телефон: как минимум 10 символов с цифрами и разделителями
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s\-\(\)]{8,}\d)")

BAD_WORDS = [
    # Русский (корни — работает по подстроке, чтобы ловить формы)
    "бля", "хуй", "хуе", "хуё", "пизд", "ебан", "ебал", "ебат", "ёбан",
    "сука", "суки", "мразь", "гандон", "долбоеб", "долбоёб", "мудак",
    "мудил", "нахуй", "нахуя", "охуе", "ахуе", "залуп",
    # English
    "fuck", "shit", "bitch", "asshole", "bastard", "cunt", "dick", "pussy",
]

def check_message(text: str) -> str | None:
    """
    Возвращает причину отказа, если сообщение нарушает правила.
    Иначе — None.
    """
    if not text:
        return None

    if URL_PATTERN.search(text):
        return "🔗 Отправка ссылок запрещена."

    if PHONE_PATTERN.search(text):
        return "📱 Отправка номеров телефонов запрещена."

    lower = text.lower()
    for word in BAD_WORDS:
        if word in lower:
            return "🚫 Использование нецензурной лексики запрещено."

    return None