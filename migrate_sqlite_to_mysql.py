import sqlite3

import pymysql


SQLITE_PATH = "hospital_chatbot.db"
MYSQL_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "hospital_chatbot",
    "port": 3306,
    "autocommit": False,
}


def fetch_rows(sqlite_conn: sqlite3.Connection, table: str):
    sqlite_conn.row_factory = sqlite3.Row
    cur = sqlite_conn.cursor()
    cur.execute(f"SELECT * FROM {table}")
    return [dict(row) for row in cur.fetchall()]


def sync_doctors(mysql_conn, doctors):
    with mysql_conn.cursor() as cur:
        for doctor in doctors:
            cur.execute(
                """
                INSERT INTO doctors (id, name, department)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    department = VALUES(department)
                """,
                (doctor["id"], doctor["name"], doctor["department"]),
            )


def sync_patients(mysql_conn, patients):
    with mysql_conn.cursor() as cur:
        for patient in patients:
            cur.execute(
                """
                INSERT INTO patients (id, name, contact)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    contact = VALUES(contact)
                """,
                (patient["id"], patient["name"], patient["contact"]),
            )


def sync_appointments(mysql_conn, appointments):
    with mysql_conn.cursor() as cur:
        for appointment in appointments:
            cur.execute(
                """
                INSERT INTO appointments
                    (id, patient_id, doctor_id, appointment_date, time_slot, symptoms, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    patient_id = VALUES(patient_id),
                    doctor_id = VALUES(doctor_id),
                    appointment_date = VALUES(appointment_date),
                    time_slot = VALUES(time_slot),
                    symptoms = VALUES(symptoms),
                    status = VALUES(status)
                """,
                (
                    appointment["id"],
                    appointment["patient_id"],
                    appointment["doctor_id"],
                    appointment["appointment_date"],
                    appointment["time_slot"],
                    appointment["symptoms"],
                    appointment["status"],
                ),
            )


def bump_auto_increment(mysql_conn, table: str) -> None:
    with mysql_conn.cursor() as cur:
        cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}")
        next_id = cur.fetchone()[0]
        cur.execute(f"ALTER TABLE {table} AUTO_INCREMENT = %s", (next_id,))


def main():
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    mysql_conn = pymysql.connect(**MYSQL_CONFIG)

    try:
        doctors = fetch_rows(sqlite_conn, "doctors")
        patients = fetch_rows(sqlite_conn, "patients")
        appointments = fetch_rows(sqlite_conn, "appointments")

        sync_doctors(mysql_conn, doctors)
        sync_patients(mysql_conn, patients)
        sync_appointments(mysql_conn, appointments)

        for table in ("doctors", "patients", "appointments"):
            bump_auto_increment(mysql_conn, table)

        mysql_conn.commit()
        print(
            f"Migrated {len(doctors)} doctors, {len(patients)} patients, "
            f"and {len(appointments)} appointments."
        )
    except Exception:
        mysql_conn.rollback()
        raise
    finally:
        sqlite_conn.close()
        mysql_conn.close()


if __name__ == "__main__":
    main()
