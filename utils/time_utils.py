from typing import Optional, List
import datetime

def parse_time_input(user_text: str, available_times: List[str]) -> Optional[str]:
    if not available_times:
        return None

    unique_dates = list({t.split()[0] for t in available_times})
    cleaned = user_text.strip().lower()

    if cleaned.isdigit():
        try:
            hour = int(cleaned)
            if 0 <= hour <= 23:
                time_part = f"{hour:02d}:00"
                if len(unique_dates) == 1:
                    candidate = f"{unique_dates[0]} {time_part}"
                    if candidate in available_times:
                        return candidate
        except ValueError:
            pass

    if user_text.count(":") == 1 and user_text.count("-") == 0:
        if len(unique_dates) == 1:
            candidate = f"{unique_dates[0]} {user_text}"
            if candidate in available_times:
                return candidate
        return None

    if user_text in available_times:
        return user_text

    return None
