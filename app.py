import datetime as dt
import json
import os
import re
import uuid
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import pymysql
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from sqlalchemy import create_engine, select
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from werkzeug.exceptions import HTTPException

from models import (
    ensure_schema,
    half_hour_slots,
    available_slot,
    available_slots,
    create_appointment,
    cancel_appointment,
    get_booked_appointments_for_contact,
    Doctor,
)

load_dotenv()

PRIMARY_DB_URL = os.getenv(
    "DB_URL", "mysql+pymysql://root:@127.0.0.1:3306/hospital_chatbot"
)

def ensure_mysql_database(db_url: str) -> None:
    url = make_url(db_url)
    if not url.drivername.startswith("mysql"):
        return

    database_name = url.database
    if not database_name:
        return

    conn = pymysql.connect(
        host=url.host or "127.0.0.1",
        user=url.username or "root",
        password=url.password or "",
        port=url.port or 3306,
        charset="utf8mb4",
        connect_timeout=3,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database_name}`")
        conn.commit()
    finally:
        conn.close()


def build_engine():
    ensure_mysql_database(PRIMARY_DB_URL)
    mysql_engine = create_engine(PRIMARY_DB_URL, echo=False, future=True)
    with mysql_engine.connect() as conn:
        conn.execute(select(1))
    return mysql_engine


engine = build_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
ensure_schema(engine)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

app = Flask(__name__)
CORS(app, origins="*")


ALLOWED_SLOTS = half_hour_slots()

# Map user-friendly specialty keywords to canonical department names
SPECIALTY_KEYWORDS = {
    "general": "General Medicine",
    "medicine": "General Medicine",
    "physician": "General Medicine",
    "general medicine": "General Medicine",
    "cardio": "Cardiology",
    "heart": "Cardiology",
    "cardiology": "Cardiology",
    "orthopedic": "Orthopedics",
    "ortho": "Orthopedics",
    "bone": "Orthopedics",
    "orthopedics": "Orthopedics",
    "derma": "Dermatology",
    "skin": "Dermatology",
    "dermatology": "Dermatology",
    "neuro": "Neurology",
    "brain": "Neurology",
    "nerve": "Neurology",
    "neurology": "Neurology",
    "child": "Pediatrics",
    "children": "Pediatrics",
    "kid": "Pediatrics",
    "pediatric": "Pediatrics",
    "pediatrics": "Pediatrics",
    "gyno": "Gynecology",
    "gyne": "Gynecology",
    "pregnancy": "Gynecology",
    "women": "Gynecology",
    "gynecology": "Gynecology",
}

SYMPTOM_DEPARTMENT_RULES = {
    "General Medicine": [
        "cold",
        "cough",
        "fever",
        "sore throat",
        "flu",
        "viral",
        "body ache",
        "body pain",
        "weakness",
        "tiredness",
        "fatigue",
        "vomiting",
        "nausea",
        "stomach pain",
        "stomach ache",
        "loose motion",
        "diarrhea",
        "infection",
    ],
    "Orthopedics": [
        "leg pain",
        "knee pain",
        "ankle pain",
        "foot pain",
        "heel pain",
        "hip pain",
        "shoulder pain",
        "back pain",
        "neck pain",
        "joint pain",
        "bone pain",
        "fracture",
        "sprain",
        "swelling in leg",
        "muscle pain",
        "arthritis",
    ],
    "Cardiology": [
        "chest pain",
        "heart pain",
        "palpitation",
        "palpitations",
        "high bp",
        "high blood pressure",
        "low bp",
        "shortness of breath",
    ],
    "Dermatology": [
        "rash",
        "skin rash",
        "itching",
        "acne",
        "eczema",
        "psoriasis",
        "skin allergy",
        "pigmentation",
    ],
    "Neurology": [
        "headache",
        "migraine",
        "dizziness",
        "vertigo",
        "seizure",
        "numbness",
        "tingling",
        "memory loss",
        "nerve pain",
    ],
    "Pediatrics": [
        "child fever",
        "baby fever",
        "kid fever",
        "infant",
        "newborn",
        "child cough",
        "baby cough",
    ],
    "Gynecology": [
        "period pain",
        "pelvic pain",
        "pregnancy",
        "missed period",
        "irregular periods",
        "vaginal bleeding",
        "pcos",
    ],
}

COMMON_NON_NAME_REPLIES = {
    "hi",
    "hello",
    "hey",
    "book",
    "appointment",
    "cancel",
    "help",
    "yes",
    "no",
    "ok",
    "okay",
    "book another",
    "book another appointment",
    "book appointment",
    "ask a question",
    "ask another question",
    "talk to human",
    "cancel this appointment",
    "cancel booking",
}

BOOKING_KEYWORDS = {
    "book",
    "appointment",
    "doctor",
    "specialist",
    "schedule",
    "reschedule",
    "cancel",
    "date",
    "time",
    "symptom",
    "pain",
    "fever",
    "rash",
    "headache",
    "cough",
    "hospital",
    "clinic",
}

QUESTION_STARTERS = {
    "what",
    "why",
    "how",
    "when",
    "where",
    "which",
    "can",
    "could",
    "should",
    "is",
    "are",
    "do",
    "does",
    "tell",
    "explain",
}


@dataclass
class PendingBooking:
    symptoms: Optional[str] = None
    department: Optional[str] = None
    doctor_id: Optional[int] = None
    date: Optional[dt.date] = None
    time_slot: Optional[str] = None
    patient_name: Optional[str] = None
    contact: Optional[str] = None


@dataclass
class SessionState:
    stage: str = "need_name"
    pending: PendingBooking = field(default_factory=PendingBooking)
    verified_contact: Optional[str] = None
    cancellable_ids: list[int] = field(default_factory=list)


SESSIONS: Dict[str, SessionState] = {}


def get_session(session_id: Optional[str]) -> Tuple[str, SessionState]:
    if not session_id or session_id not in SESSIONS:
        session_id = str(uuid.uuid4())
        SESSIONS[session_id] = SessionState()
    return session_id, SESSIONS[session_id]


def reset_session(state: SessionState) -> None:
    state.stage = "need_name"
    state.pending = PendingBooking()
    state.cancellable_ids = []


def call_gemini(prompt: str, system_instruction: str, *, temperature: float = 0.3) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY")

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={urlparse.quote(GEMINI_API_KEY)}"
    )
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_instruction}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 250,
        },
    }
    req = urlrequest.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini API error: {detail or exc.reason}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Gemini API unreachable: {exc.reason}") from exc

    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini API returned no candidates")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise RuntimeError("Gemini API returned an empty response")
    return text


def ai_fallback(message: str) -> str:
    """
    Generic Q&A fallback using Gemini.
    """
    if not GEMINI_API_KEY:
        return (
            "I'm here to help with appointments. For general questions, please add "
            "your Gemini API key as GEMINI_API_KEY in the .env file."
        )

    return call_gemini(
        message,
        (
            "You are a helpful hospital assistant. Answer briefly and safely. "
            "Do not diagnose with certainty. Recommend urgent medical care for "
            "serious symptoms like chest pain, severe breathing trouble, stroke signs, "
            "heavy bleeding, or loss of consciousness."
        ),
        temperature=0.3,
    )


def ai_infer_department(symptoms: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None

    content = call_gemini(
        symptoms,
        (
            "You route patient symptoms to one hospital department only. "
            "Choose from General Medicine, Cardiology, Orthopedics, Dermatology, "
            "Neurology, Pediatrics, Gynecology, or Unknown. "
            "Return strict JSON only, for example {\"department\":\"Orthopedics\"}."
        ),
        temperature=0,
    )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None

    department = parsed.get("department")
    if department in {"General Medicine", "Cardiology", "Orthopedics", "Dermatology", "Neurology", "Pediatrics", "Gynecology"}:
        return department
    return None


def parse_date(text: str) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def is_past_date(value: dt.date) -> bool:
    return value < dt.date.today()


def parse_time(text: str) -> Optional[str]:
    cleaned = " ".join(text.strip().upper().split())
    if not cleaned:
        return None

    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([AP]M)\b", cleaned)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or "00")
    period = match.group(3)

    if hour < 1 or hour > 12 or minute not in {0, 30}:
        return None

    if period == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12

    return f"{hour:02d}:{minute:02d}"


def format_time_slot(slot: str) -> str:
    return dt.datetime.strptime(slot, "%H:%M").strftime("%I:%M %p").lstrip("0")


def format_date(value: dt.date) -> str:
    return value.strftime("%Y-%m-%d")


def nearest_time_options(desired_time: str, slots: list[str], limit: int = 4) -> list[str]:
    desired_minutes = int(desired_time[:2]) * 60 + int(desired_time[3:])

    def slot_distance(slot: str) -> tuple[int, int]:
        slot_minutes = int(slot[:2]) * 60 + int(slot[3:])
        return (abs(slot_minutes - desired_minutes), slot_minutes)

    return sorted(slots, key=slot_distance)[:limit]


def parse_department(text: str) -> Optional[str]:
    lower = text.lower()
    for kw, dept in SPECIALTY_KEYWORDS.items():
        if kw in lower:
            return dept
    return None


def infer_department_from_symptoms(symptoms: str) -> Optional[str]:
    normalized = normalize_text(symptoms)
    if not normalized:
        return None

    for department, phrases in SYMPTOM_DEPARTMENT_RULES.items():
        for phrase in phrases:
            if normalize_text(phrase) in normalized:
                return department

    tokens = set(normalized.split())
    token_rules = {
        "General Medicine": {"cold", "cough", "fever", "flu", "viral", "weakness", "fatigue", "vomiting", "nausea", "stomach", "diarrhea"},
        "Orthopedics": {"leg", "knee", "ankle", "foot", "heel", "hip", "shoulder", "back", "neck", "joint", "bone", "fracture", "sprain"},
        "Cardiology": {"heart", "chest", "palpitation", "palpitations", "bp", "breathless"},
        "Dermatology": {"skin", "rash", "itching", "acne", "eczema", "psoriasis"},
        "Neurology": {"headache", "migraine", "dizziness", "vertigo", "seizure", "numbness", "tingling"},
        "Pediatrics": {"child", "children", "kid", "kids", "baby", "infant", "newborn"},
        "Gynecology": {"period", "pelvic", "pregnancy", "pregnant", "pcos", "women", "woman"},
    }
    for department, keywords in token_rules.items():
        if tokens & keywords:
            return department

    try:
        return ai_infer_department(symptoms)
    except Exception:
        return None


def build_doctor_suggestions(doctors: list[Doctor]) -> list[str]:
    return [f"{doc.id}. {doc.name} ({doc.department})" for doc in doctors]


def extract_name(text: str) -> Optional[str]:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return None

    lower = cleaned.lower()
    if "name is" in lower:
        idx = lower.index("name is") + len("name is")
        after = cleaned[idx:].strip()
        return " ".join(after.split()[:3]).strip(",.") or None
    if "i am" in lower:
        idx = lower.index("i am") + len("i am")
        after = cleaned[idx:].strip()
        return " ".join(after.split()[:3]).strip(",.") or None

    # While explicitly asking for a name, accept a short plain-text reply like "Payal".
    words = cleaned.strip(",.").split()
    if (
        1 <= len(words) <= 3
        and lower not in COMMON_NON_NAME_REPLIES
        and all(any(ch.isalpha() for ch in word) for word in words)
    ):
        return " ".join(words).strip(",.")

    return None


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def is_general_question(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False

    words = normalized.split()
    first_word = words[0]
    has_question_form = "?" in text or first_word in QUESTION_STARTERS
    if not has_question_form:
        return False

    return not any(keyword in normalized for keyword in BOOKING_KEYWORDS)


def is_restart_booking_request(text: str) -> bool:
    normalized = normalize_text(text)
    return normalized in {"book another", "book another appointment", "book appointment"}


def is_general_question_request(text: str) -> bool:
    normalized = normalize_text(text)
    return normalized in {"ask a question", "ask another question"}


def extract_contact(text: str) -> Optional[str]:
    cleaned = text.strip()
    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned)
    if email_match:
        return email_match.group(0).lower()

    digits = re.sub(r"\D", "", cleaned)
    if len(digits) >= 10:
        return digits[-10:]
    return None


def extract_appointment_id(text: str) -> Optional[int]:
    match = re.search(r"(?:appointment\s*#?\s*|#)(\d+)|\b(\d+)\b", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def summarize_appointment(appt) -> str:
    return (
        f"{appt.id}. {appt.doctor.name} on {format_date(appt.appointment_date)} "
        f"at {format_time_slot(appt.time_slot)}"
    )


def cancel_option_label(appt) -> str:
    return (
        f"Cancel appointment #{appt.id} with {appt.doctor.name} on "
        f"{format_date(appt.appointment_date)} at {format_time_slot(appt.time_slot)}"
    )


def serialize_doctor(doc: Doctor) -> Dict:
    return {"id": doc.id, "name": doc.name, "department": doc.department}


def first_doctor_with_open_slot(db: Session, department: str, appt_date: dt.date) -> Optional[Doctor]:
    for doc in db.scalars(select(Doctor).where(Doctor.department == department)):
        if available_slots(db, doc.id, appt_date, ALLOWED_SLOTS):
            return doc
    return None


def next_steps(state: SessionState) -> str:
    p = state.pending
    missing = []
    if not p.symptoms:
        missing.append("your symptoms")
    if not p.department and not p.doctor_id:
        missing.append("preferred department or doctor")
    if not p.date:
        missing.append("date (YYYY-MM-DD)")
    if not p.time_slot:
        missing.append("time slot (e.g. 10:00 AM)")
    if not p.patient_name:
        missing.append("your name")
    if not p.contact:
        missing.append("a phone or email")

    if missing:
        return "I still need " + ", ".join(missing) + "."
    return "Ready to confirm your appointment."


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug/db")
def debug_db():
    return {
        "backend": "mysql",
        "driver": engine.url.drivername,
        "database_url": engine.url.render_as_string(hide_password=True),
    }


@app.get("/")
def root():
    return send_from_directory("static", "index.html")


@app.get("/demo")
def demo():
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hospital Chatbot</title>
  <style>
    :root { --bg:#0b1623; --card:#101d2c; --muted:#8ea0b5; --accent:#4be1c3; --text:#e8f1fb; --radius:16px; --shadow:0 20px 60px rgba(0,0,0,0.35);}
    *{box-sizing:border-box;}
    body{margin:0;min-height:100vh;font-family:"Inter",system-ui,-apple-system,sans-serif;background:radial-gradient(120% 120% at 10% 20%,rgba(75,225,195,0.15),transparent),radial-gradient(90% 90% at 80% 0%,rgba(114,184,255,0.18),transparent),var(--bg);color:var(--text);padding:32px;}
    .layout{max-width:1100px;margin:0 auto;display:grid;grid-template-columns:2fr 1fr;gap:18px;}
    header{grid-column:span 2;display:flex;align-items:center;justify-content:space-between;}
    .eyebrow{letter-spacing:0.1em;text-transform:uppercase;color:var(--muted);font-size:12px;margin:0 0 8px;}
    h1{margin:0 0 6px;} .lede{margin:0;color:var(--muted);max-width:600px;}
    .tag{background:rgba(75,225,195,0.12);color:var(--accent);border:1px solid rgba(75,225,195,0.3);padding:8px 14px;border-radius:999px;font-weight:600;}
    .card{background:var(--card);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius);padding:18px;box-shadow:var(--shadow);}
    .chat{height:520px;overflow-y:auto;display:flex;flex-direction:column;gap:12px;padding:8px;}
    .bubble{padding:12px 14px;border-radius:14px;max-width:80%;line-height:1.4;box-shadow:0 10px 30px rgba(0,0,0,0.2);}
    .user{align-self:flex-end;background:#20334a;} .bot{align-self:flex-start;background:rgba(75,225,195,0.12);border:1px solid rgba(75,225,195,0.25);}
    form{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:10px;}
    input{padding:12px 14px;border-radius:12px;border:1px solid rgba(255,255,255,0.08);background:#0f2033;color:var(--text);}
    button{background:linear-gradient(135deg,#4be1c3,#52a8ff);border:none;color:#04101d;padding:12px 18px;border-radius:12px;font-weight:700;cursor:pointer;}
    .tips ul{padding-left:18px;margin:8px 0;color:var(--muted);} .tips li{margin-bottom:6px;}
    @media (max-width:900px){.layout{grid-template-columns:1fr;}header{flex-direction:column;align-items:flex-start;gap:8px;}}
  </style>
</head>
<body>
  <div class="layout">
    <header>
      <div>
        <p class="eyebrow">Reyna Hospitals</p>
        <h1>Smart Appointment Assistant</h1>
        <p class="lede">Book, reschedule, or ask quick questions. The bot checks live availability before confirming.</p>
      </div>
      <div class="tag">Beta</div>
    </header>

    <main class="card">
      <section class="chat" id="chat"></section>
      <form id="chat-form">
        <input id="input" type="text" placeholder="Describe symptoms or ask a question…" autocomplete="off" required />
        <button type="submit">Send</button>
      </form>
    </main>

    <aside class="card tips">
      <h3>Try saying</h3>
      <ul>
        <li>"Book me with a cardiologist on 2026-03-20 at 10:00"</li>
        <li>"Cancel appointment 12"</li>
        <li>"I have skin rash, any precautions?"</li>
      </ul>
    </aside>
  </div>

  <script>
    const chatEl = document.getElementById('chat');
    const form = document.getElementById('chat-form');
    const input = document.getElementById('input');
    let sessionId = localStorage.getItem('session_id') || '';

    const addBubble = (text, role='bot') => {
      const div = document.createElement('div');
      div.className = `bubble ${role}`;
      div.textContent = text;
      chatEl.appendChild(div);
      chatEl.scrollTop = chatEl.scrollHeight;
    };

    async function sendMessage(message){
      addBubble(message, 'user');
      input.value = '';
      const res = await fetch('/api/chat', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({message, session_id: sessionId})
      });
      const data = await res.json();
      sessionId = data.session_id;
      localStorage.setItem('session_id', sessionId);
      addBubble(data.reply, 'bot');
      if(data.suggestions){
        const s = document.createElement('div');
        s.className = 'bubble bot';
        s.innerHTML = '<strong>Suggestions:</strong> ' + data.suggestions.join(' · ');
        chatEl.appendChild(s);
        chatEl.scrollTop = chatEl.scrollHeight;
      }
    }

    form.addEventListener('submit', (e)=>{
      e.preventDefault();
      const msg = input.value.trim();
      if(msg) sendMessage(msg);
    });

    addBubble('Hi! I can book or cancel appointments. Tell me your symptoms and preferred date/time.');
  </script>
</body>
</html>
    """


@app.get("/api/doctors")
def list_doctors():
    with SessionLocal() as db:
        doctors = db.scalars(select(Doctor)).all()
    return jsonify([serialize_doctor(d) for d in doctors])


@app.get("/api/availability")
def availability():
    doctor_id = request.args.get("doctor_id", type=int)
    dept = request.args.get("department", type=str)
    appt_date_raw = request.args.get("date")
    appt_date = parse_date(appt_date_raw) if appt_date_raw else dt.date.today()

    if not doctor_id and not dept:
        return jsonify({"error": "doctor_id or department is required"}), 400

    if appt_date and is_past_date(appt_date):
        return jsonify({"error": "Past dates are not allowed"}), 400

    with SessionLocal() as db:
        if not doctor_id and dept:
            doc = first_doctor_with_open_slot(db, dept, appt_date)
            if not doc:
                return jsonify({"slots": [], "doctor": None, "department": dept})
            doctor_id = doc.id

        slots = available_slots(db, doctor_id, appt_date, ALLOWED_SLOTS)
        doc = db.get(Doctor, doctor_id)

    return jsonify(
        {
            "date": appt_date.isoformat(),
            "doctor": serialize_doctor(doc) if doc else None,
            "slots": slots,
            "department": doc.department if doc else dept,
        }
    )


@app.post("/api/chat")
def chat():
    try:
        data = request.get_json(force=True)
        user_msg = data.get("message", "").strip()
    except Exception as exc:  # bad payloads
        return (
            jsonify(
                {
                    "session_id": "",
                    "reply": "I couldn't read that message. Please try again.",
                    "suggestions": ["Hi, I want to book", "My name is ..."],
                    "error": str(exc),
                }
            ),
            400,
        )

    session_id, state = get_session(data.get("session_id"))

    if is_restart_booking_request(user_msg):
        reset_session(state)
        return jsonify(
            {
                "session_id": session_id,
                "reply": "Sure, let's book another appointment. What's your name?",
                "suggestions": ["My name is ..."],
                "state": "booking",
            }
        )

    if is_general_question_request(user_msg):
        reset_session(state)
        state.stage = "idle"
        return jsonify(
            {
                "session_id": session_id,
                "reply": "Sure, ask me any question.",
                "suggestions": ["Book appointment", "Cancel booking"],
                "state": "idle",
            }
        )

    if is_general_question(user_msg) and state.stage in {"need_name", "need_symptoms"}:
        try:
            fallback = ai_fallback(user_msg)
        except Exception as exc:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "I'm having trouble reaching Gemini right now. You can still book an appointment.",
                    "suggestions": ["Book appointment", "Cancel booking"],
                    "state": "idle",
                    "error": str(exc),
                }
            )
        return jsonify(
            {
                "session_id": session_id,
                "reply": fallback,
                "suggestions": ["Book appointment", "Ask another question"],
                "state": "idle",
            }
        )

    if state.stage == "cancel_verify_contact":
        contact = extract_contact(user_msg) or state.verified_contact
        if not contact:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Please share the same phone number or email you used while booking.",
                    "state": "cancellation",
                }
            )

        with SessionLocal() as db:
            appointments = get_booked_appointments_for_contact(db, contact)

        if not appointments:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": (
                        "I couldn't find any active appointments with that contact. "
                        "Please try the same phone number or email used during booking."
                    ),
                    "state": "cancellation",
                }
            )

        state.verified_contact = contact
        state.cancellable_ids = [appt.id for appt in appointments]
        state.stage = "cancel_select"
        appointment_lines = "\n".join(summarize_appointment(appt) for appt in appointments)
        return jsonify(
            {
                "session_id": session_id,
                "reply": (
                    "I found these active appointments under your contact. "
                    f"Which one would you like to cancel?\n{appointment_lines}"
                ),
                "suggestions": [cancel_option_label(appt) for appt in appointments],
                "state": "cancellation",
            }
        )

    if state.stage == "cancel_select":
        appt_id = extract_appointment_id(user_msg)
        if not appt_id or appt_id not in state.cancellable_ids:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Please choose one of your listed appointment IDs to cancel.",
                    "suggestions": [f"Cancel appointment #{appt_id}" for appt_id in state.cancellable_ids],
                    "state": "cancellation",
                }
            )

        with SessionLocal() as db:
            success = cancel_appointment(db, appt_id)
        contact = state.verified_contact
        reset_session(state)
        state.verified_contact = contact
        if success:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": f"Appointment #{appt_id} has been cancelled. Anything else I can help with?",
                    "suggestions": ["Book another appointment", "Ask a question"],
                    "state": "idle",
                }
            )
        return jsonify(
            {
                "session_id": session_id,
                "reply": "I couldn't cancel that appointment. It may already be cancelled.",
                "state": "cancellation",
            }
        )

    # Allow cancellations anytime
    if "cancel" in user_msg.lower():
        state.stage = "cancel_verify_contact"
        state.cancellable_ids = []
        return jsonify(
            {
                "session_id": session_id,
                "reply": (
                    "Sure. To protect your appointments, please share the same "
                    "phone number or email you used while booking."
                ),
                "state": "cancellation",
            }
        )

    p = state.pending

    # Stage: ask for name
    if state.stage == "need_name":
        found_name = extract_name(user_msg)
        if found_name:
            p.patient_name = found_name
            state.stage = "need_symptoms"
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": f"Hi {p.patient_name}! What symptoms are you experiencing?",
                    "state": "booking",
                }
            )
        return jsonify(
            {
                "session_id": session_id,
                "reply": "Hi! I can book an appointment. First, what's your name?",
                "state": "booking",
            }
        )

    # Stage: capture symptoms and suggest doctors
    if state.stage == "need_symptoms":
        if not p.symptoms:
            p.symptoms = user_msg
        else:
            p.symptoms = f"{p.symptoms} {user_msg}".strip()

        dept = (
            parse_department(user_msg)
            or parse_department(p.symptoms or "")
            or infer_department_from_symptoms(p.symptoms or "")
        )
        if dept:
            p.department = dept
        if not p.department:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": (
                        "I want to match you with the right specialist. "
                        "Which department would you prefer? General Medicine, Cardiology, "
                        "Orthopedics, Dermatology, Neurology, Pediatrics, or Gynecology?"
                    ),
                    "suggestions": [
                        "General Medicine",
                        "Cardiology",
                        "Orthopedics",
                        "Dermatology",
                        "Neurology",
                        "Pediatrics",
                        "Gynecology",
                    ],
                    "state": "need_symptoms",
                }
            )
        with SessionLocal() as db:
            doctors = db.scalars(
                select(Doctor).where(Doctor.department == p.department)
            ).all()
            if not doctors:
                return jsonify(
                    {
                        "session_id": session_id,
                        "reply": (
                            f"I couldn't find available doctors in {p.department}. "
                            "Please choose another department."
                        ),
                        "suggestions": [
                            "General Medicine",
                            "Cardiology",
                            "Orthopedics",
                            "Dermatology",
                            "Neurology",
                            "Pediatrics",
                            "Gynecology",
                        ],
                        "state": "need_symptoms",
                    }
                )
            options = build_doctor_suggestions(doctors)
        state.stage = "select_doctor"
        options_text = "\n".join(options)
        return jsonify(
            {
                "session_id": session_id,
                "reply": (
                    f"Based on your symptoms, the best match looks like {p.department}. "
                    f"Tap a doctor below or type the doctor name/number:\n{options_text}"
                ),
                "suggestions": options,
                "state": "booking",
            }
        )

    # Stage: select doctor
    if state.stage == "select_doctor":
        chosen_id = None
        normalized_msg = normalize_text(user_msg)
        with SessionLocal() as db:
            doctor_query = select(Doctor)
            if p.department:
                doctor_query = doctor_query.where(Doctor.department == p.department)
            for doc in db.scalars(doctor_query):
                normalized_name = normalize_text(doc.name)
                if str(doc.id) in user_msg or normalized_name in normalized_msg:
                    chosen_id = doc.id
                    p.department = doc.department
                    break
        if not chosen_id:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Please pick a doctor by typing their number or name.",
                    "state": "booking",
                }
            )
        p.doctor_id = chosen_id
        state.stage = "need_date"
        return jsonify(
            {
                "session_id": session_id,
                "reply": "Great. What date would you like? Please use YYYY-MM-DD format.",
                "state": "booking",
            }
        )

    if state.stage == "need_date":
        parsed = parse_date(user_msg)
        if not parsed:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Please provide the date in YYYY-MM-DD format.",
                    "state": "booking",
                }
            )
        if is_past_date(parsed):
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Please choose today or a future date. Past dates are not allowed.",
                    "state": "booking",
                }
            )
        p.date = parsed
        state.stage = "need_time"
        return jsonify(
            {
                "session_id": session_id,
                "reply": (
                    f"Thanks. What time would you like on {format_date(p.date)}? "
                    "Please use 12-hour format like 10:00 AM."
                ),
                "state": "booking",
            }
        )

    # Stage: collect time and book
    if state.stage == "need_time":
        parsed_t = parse_time(user_msg)
        if not parsed_t:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Please provide the time in 12-hour format, for example 10:00 AM or 10:30 AM.",
                    "state": "booking",
                }
            )

        p.time_slot = parsed_t

        with SessionLocal() as db:
            slot = available_slot(db, p.doctor_id, p.date, p.time_slot, ALLOWED_SLOTS)
            if slot is None:
                alts = available_slots(db, p.doctor_id, p.date, ALLOWED_SLOTS)
                if not alts:
                    return jsonify(
                        {
                            "session_id": session_id,
                            "reply": f"Doctor is fully booked on {format_date(p.date)}. Please choose another date.",
                            "state": "need_date",
                        }
                    )
                nearest_alts = nearest_time_options(p.time_slot, alts)
                alt_labels = [format_time_slot(alt) for alt in nearest_alts]
                return jsonify(
                    {
                        "session_id": session_id,
                        "reply": (
                            f"{format_time_slot(p.time_slot)} is not available. Nearby open times are: "
                            f"{', '.join(alt_labels)}. Please choose one."
                        ),
                        "suggestions": alt_labels,
                        "state": "need_time",
                    }
                )
            if slot != p.time_slot:
                p.time_slot = slot
            doctor_name = db.get(Doctor, p.doctor_id).name if p.doctor_id else "doctor"
        state.stage = "need_contact"
        return jsonify(
            {
                "session_id": session_id,
                "reply": (
                    f"{doctor_name} is available on {format_date(p.date)} at "
                    f"{format_time_slot(p.time_slot)}. Please share your phone number "
                    "or email to confirm the booking."
                ),
                "state": "booking",
            }
        )

    if state.stage == "need_contact":
        contact = extract_contact(user_msg)
        if not contact:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Please share a valid phone number or email so I can confirm and later verify your appointment.",
                    "state": "booking",
                }
            )

        p.contact = contact

        with SessionLocal() as db:
            appt = create_appointment(
                db,
                doctor_id=p.doctor_id,
                patient_name=p.patient_name or "Patient",
                patient_contact=p.contact,
                appt_date=p.date,
                time_slot=p.time_slot,
                symptoms=p.symptoms or "",
            )
            doctor_name = db.get(Doctor, p.doctor_id).name if p.doctor_id else "doctor"
            appointment_id = appt.id
            appointment_date = appt.appointment_date
            appointment_time = appt.time_slot
        state.verified_contact = p.contact
        reset_session(state)
        state.verified_contact = contact
        return jsonify(
            {
                "session_id": session_id,
                "reply": (
                    f"Booked! Appointment #{appointment_id} with doctor "
                    f"{doctor_name} on {format_date(appointment_date)} at "
                    f"{format_time_slot(appointment_time)}. You can later cancel it "
                    "by returning with the same phone number or email. Need anything else?"
                ),
                "suggestions": ["Cancel this appointment", "Book another"],
                "appointment_id": appointment_id,
            }
        )

    # Generic Q&A fallback
    try:
        fallback = ai_fallback(user_msg)
    except Exception as exc:
        return jsonify(
            {
                "session_id": session_id,
                "reply": "I'm having trouble reaching the AI service right now. You can still book an appointment.",
                "suggestions": ["Book appointment", "Cancel booking"],
                "state": "idle",
                "error": str(exc),
            }
        )
    return jsonify(
        {
            "session_id": session_id,
            "reply": fallback,
            "suggestions": ["Book appointment", "Talk to human"],
            "state": "idle",
        }
    )


@app.errorhandler(Exception)
def handle_error(err):
    if isinstance(err, HTTPException):
        return jsonify({"error": err.description, "message": err.name}), err.code

    # Ensure frontend never sees HTML error pages
    return (
        jsonify({"error": str(err), "message": "Internal error. Please try again."}),
        500,
    )


if __name__ == "__main__":
    # Run without the Flask reloader to avoid double-starts and port conflicts.
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
