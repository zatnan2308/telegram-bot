# services/scheduler.py
from datetime import datetime, time, timedelta
from database.queries import (
    get_service_duration, 
    get_specialist_work_hours,
    get_bookings_for_specialist_on_date
)

def get_available_start_times(
    specialist_id: int,
    date_obj: datetime.date,
    service_id: int
) -> list[str]:
    """
    Возвращает список строк-времён (формат "HH:MM"),
    когда можно начать услугу service_id в день date_obj 
    у специалиста specialist_id.
    """
    duration = get_service_duration(service_id)  # int
    start_time, end_time = get_specialist_work_hours(specialist_id)  # time, time

    # Если что-то не задали
    if not start_time or not end_time or duration <= 0:
        return []

    # Получаем существующие бронирования
    bookings = get_bookings_for_specialist_on_date(specialist_id, date_obj)
    # bookings -> [{'start': datetime, 'duration': int}, ...]

    time_step = 30  # шаг в минутах
    available_slots = []

    # Собираем datetime для старта и конца
    workday_start = datetime.combine(date_obj, start_time)  # 2025-05-10 10:00
    workday_end   = datetime.combine(date_obj, end_time)    # 2025-05-10 20:00

    current = workday_start
    while True:
        potential_end = current + timedelta(minutes=duration)
        if potential_end > workday_end:
            break

        if not intersects_any_bookings(current, potential_end, bookings):
            slot_str = current.strftime("%H:%M")
            available_slots.append(slot_str)

        current += timedelta(minutes=time_step)
        if current >= workday_end:
            break
    
    return available_slots


def intersects_any_bookings(
    start_dt: datetime, 
    end_dt: datetime, 
    bookings: list
) -> bool:
    """
    Проверяет, пересекается ли интервал [start_dt, end_dt)
    с любым бронированием. Возвращает True, если пересечения есть.
    """
    for b in bookings:
        b_start = b['start']
        b_end = b_start + timedelta(minutes=b['duration'])

        # Интервалы [start_dt, end_dt) и [b_start, b_end)
        if not (end_dt <= b_start or start_dt >= b_end):
            return True  # пересекается

    return False
