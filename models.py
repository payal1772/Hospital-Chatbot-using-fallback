import datetime as dt
from typing import Optional, List

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    Text,
    ForeignKey,
    create_engine,
    select,
    inspect,
)
from sqlalchemy.orm import declarative_base, relationship, Session, joinedload

Base = declarative_base()


SEED_DOCTORS = [
    ("Dr. Meera Thomas", "General Medicine"),
    ("Dr. Asha Nair", "Cardiology"),
    ("Dr. Rohan Mehta", "Cardiology"),
    ("Dr. Sneha Kapoor", "Cardiology"),
    ("Dr. Vivek Rao", "Orthopedics"),
    ("Dr. Karan Malhotra", "Orthopedics"),
    ("Dr. Neha Verma", "Orthopedics"),
    ("Dr. Priya Desai", "Dermatology"),
    ("Dr. Ananya Sen", "Dermatology"),
    ("Dr. Mehul Shah", "Dermatology"),
    ("Dr. Arjun Iyer", "Neurology"),
    ("Dr. Nisha Menon", "Neurology"),
    ("Dr. Rahul Bedi", "Neurology"),
    ("Dr. Kavita Joshi", "Pediatrics"),
    ("Dr. Sameer Kulkarni", "Pediatrics"),
    ("Dr. Ritu Agarwal", "Pediatrics"),
    ("Dr. Pooja Arora", "Gynecology"),
    ("Dr. Shalini Gupta", "Gynecology"),
    ("Dr. Devika Nambiar", "Gynecology"),
]


def half_hour_slots() -> List[str]:
    return [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)]


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    department = Column(String(100), nullable=False)

    appointments = relationship("Appointment", back_populates="doctor")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    contact = Column(String(100), nullable=False)

    appointments = relationship("Appointment", back_populates="patient")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_date = Column(Date, nullable=False)
    time_slot = Column(String(20), nullable=False)  # e.g. "10:00", "14:30"
    symptoms = Column(Text, nullable=True)
    status = Column(String(20), default="booked")  # booked | cancelled

    patient = relationship("Patient", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")


def ensure_schema(engine) -> None:
    inspector = inspect(engine)
    existing = inspector.get_table_names()
    if not {"doctors", "patients", "appointments"}.issubset(existing):
        Base.metadata.create_all(engine)

    with Session(engine) as session:
        existing_doctors = {
            (doctor.name, doctor.department)
            for doctor in session.scalars(select(Doctor))
        }
        missing_doctors = [
            Doctor(name=name, department=department)
            for name, department in SEED_DOCTORS
            if (name, department) not in existing_doctors
        ]
        if missing_doctors:
            session.add_all(missing_doctors)
            session.commit()


def available_slot(
    session: Session,
    doctor_id: int,
    appt_date: dt.date,
    desired_time: str,
    allowed_slots: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Returns the requested time slot if it is free for the given date.
    """
    if allowed_slots is None:
        allowed_slots = half_hour_slots()

    taken = {
        row.time_slot
        for row in session.scalars(
            select(Appointment).where(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date == appt_date,
                Appointment.status == "booked",
            )
        )
    }

    if desired_time not in allowed_slots or desired_time in taken:
        return None
    return desired_time


def available_slots(
    session: Session,
    doctor_id: int,
    appt_date: dt.date,
    allowed_slots: Optional[List[str]] = None,
) -> List[str]:
    """
    Returns all free time slots for a doctor on a given date.
    """
    if allowed_slots is None:
        allowed_slots = half_hour_slots()

    taken = {
        row.time_slot
        for row in session.scalars(
            select(Appointment).where(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date == appt_date,
                Appointment.status == "booked",
            )
        )
    }
    return [slot for slot in sorted(allowed_slots) if slot not in taken]


def create_appointment(
    session: Session,
    *,
    doctor_id: int,
    patient_name: str,
    patient_contact: str,
    appt_date: dt.date,
    time_slot: str,
    symptoms: str,
) -> Appointment:
    patient = session.scalar(
        select(Patient).where(Patient.contact == patient_contact)
    )
    if not patient:
        patient = Patient(name=patient_name, contact=patient_contact)
        session.add(patient)
        session.flush()

    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doctor_id,
        appointment_date=appt_date,
        time_slot=time_slot,
        symptoms=symptoms,
        status="booked",
    )
    session.add(appt)
    session.commit()
    session.refresh(appt)
    return appt


def get_booked_appointments_for_contact(session: Session, contact: str) -> List[Appointment]:
    return list(
        session.scalars(
            select(Appointment)
            .options(joinedload(Appointment.doctor), joinedload(Appointment.patient))
            .join(Patient)
            .where(
                Patient.contact == contact,
                Appointment.status == "booked",
            )
            .order_by(Appointment.appointment_date, Appointment.time_slot)
        )
    )


def cancel_appointment(session: Session, appt_id: int) -> bool:
    appt = session.get(Appointment, appt_id)
    if not appt or appt.status == "cancelled":
        return False
    appt.status = "cancelled"
    session.commit()
    return True
