from db import get_conn


def trace_records(trace_id: str):
    conn = get_conn()
    cur = conn.cursor()

    result = {}

    tables = [
        "monitor_item",
        "reminder_record",
        "delivery_record",
        "confirm_record",
        "escalation_record",
        "recovery_record"
    ]

    for table in tables:
        cur.execute(f"SELECT * FROM {table} WHERE trace_id = ?", (trace_id,))
        result[table] = cur.fetchall()

    conn.close()
    return result