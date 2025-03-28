from datetime import datetime, timedelta
from database.queries import get_service_duration, get_specialist_work_hours, get_bookings_for_specialist_on_date

def get_available_start_times(specialist_id: int, date_obj: datetime.date, service_id: int) -> list[str]:
    duration = get_service_duration(service_id)
    start_time, end_time = get_specialist_work_hours(specialist_id)
    if not start_time or not end_time or duration <= 0:
        return []
    bookings = get_bookings_for_specialist_on_date(specialist_id, date_obj)
    time_step = 30
    available_slots = []
    workday_start = datetime.combine(date_obj, start_time)
    workday_end   = datetime.combine(date_obj, end_time)
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

def intersects_any_bookings(start_dt: datetime, end_dt: datetime, bookings: list) -> bool:
    for b in bookings:
        b_start = b['start']
        b_end = b_start + timedelta(minutes=b['duration'])
        if not (end_dt <= b_start or start_dt >= b_end):
            return True
    return False
