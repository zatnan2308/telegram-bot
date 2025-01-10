from typing import Optional, List
import datetime

def parse_time_input(user_text: str, available_times: List[str]) -> Optional[str]:
    """
    Пытается распознать время из user_text и вернуть точный слот из available_times
    """
    if not available_times:
        return None

    # Уникальные даты из available_times
    unique_dates = list({t.split()[0] for t in available_times})

    # Очищаем ввод пользователя
    cleaned = user_text.strip().lower()

    # Случай 1: Пользователь ввел только час (например "12")
    if cleaned.isdigit():
        try:
            hour = int(cleaned)
            if 0 <= hour <= 23:
                time_part = f"{hour:02d}:00"
                # Если есть только одна уникальная дата
                if len(unique_dates) == 1:
                    candidate = f"{unique_dates[0]} {time_part}"
                    if candidate in available_times:
                        return candidate
        except ValueError:
            pass

    # Случай 2: Формат "ЧЧ:ММ"
    if user_text.count(":") == 1 and user_text.count("-") == 0:
        if len(unique_dates) == 1:
            candidate = f"{unique_dates[0]} {user_text}"
            if candidate in available_times:
                return candidate
        return None

    # Случай 3: Полный формат "YYYY-MM-DD HH:MM"
    if user_text in available_times:
        return user_text

    return None
