
# Hospital Chatbot

Hospital Chatbot is a Flask-based patient support and appointment booking system. It combines a conversational interface with doctor availability, appointment management, symptom-to-department routing, and an AI fallback for general questions.

## Features

- Book hospital appointments through chat
- Cancel existing appointments using the same contact details used at booking time
- Route patient symptoms to the most relevant department
- Suggest doctors by department
- Check live doctor availability by date
- Support general health-related questions through Gemini
- Serve a simple browser-based chat UI

## Tech Stack

- Python
- Flask
- SQLAlchemy
- MySQL
- PyMySQL
- HTML, CSS, JavaScript
- Gemini API for general Q&A and symptom routing fallback

## Project Structure

```text
Hospital_chatbot/
|-- app.py
|-- models.py
|-- schema.sql
|-- requirements.txt
|-- migrate_sqlite_to_mysql.py
|-- static/
|   `-- index.html
`-- README.md
```

## How It Works

The chatbot manages a session-based conversation flow for:

- booking appointments
- cancelling appointments
- answering generic questions

During booking, it collects the patient's name, symptoms, preferred department or doctor, appointment date, time slot, and contact details. It stores appointments in the database and checks slot availability before confirming the booking.

For open-ended questions, the app uses Gemini as a fallback assistant. If the question is not part of the booking flow, the chatbot can answer generally instead of forcing the patient back into appointment booking.

## Database

The application is designed to run with MySQL and automatically ensures the required schema exists at startup.

Tables used:

- `doctors`
- `patients`
- `appointments`

The app also seeds a default doctor list if the table is empty or missing some expected doctors.

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd Hospital_chatbot
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
DB_URL=mysql+pymysql://root:<your-password>@127.0.0.1:3306/hospital_chatbot
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
```

Notes:

- `GEMINI_API_KEY` is optional if you only want appointment booking and cancellation.
- If Gemini is not configured, general AI answers will be limited.

### 5. Create the database

Make sure MySQL is running, then create the database:

```sql
CREATE DATABASE hospital_chatbot;
```

You can also use the provided [schema.sql](/abs/path/c:/Reyna%20Solutions/Hospital_chatbot/schema.sql) if you want to initialize the schema manually.

### 6. Run the app

```bash
python app.py
```

Then open:

```text
http://127.0.0.1:5000/
```

## API Endpoints

### `GET /`

Serves the main chat UI.

### `GET /demo`

Serves a lightweight demo chat page.

### `GET /api/health`

Returns a simple health response.

Example response:

```json
{
  "status": "ok"
}
```

### `GET /api/debug/db`

Returns database backend and driver details for debugging.

### `GET /api/doctors`

Returns the list of doctors.

### `GET /api/availability`

Checks doctor availability by `doctor_id` or `department` and date.

Example:

```text
/api/availability?department=Cardiology&date=2026-03-30
```

### `POST /api/chat`

Main chatbot endpoint.

Example request:

```json
{
  "message": "I want to book an appointment for fever tomorrow",
  "session_id": ""
}
```

## Example Prompts

- `Book me with a cardiologist on 2026-03-30 at 10:00 AM`
- `I have a skin rash and itching`
- `Cancel my appointment`
- `What are the symptoms of dehydration?`

## Notes

- Appointment time slots are handled in 30-minute intervals.
- Cancellation requires the same phone number or email used while booking.
- General health answers are informational and should not replace professional medical advice.

## Future Improvements

- Add authentication for patients and staff
- Add rescheduling support
- Add admin dashboard for doctor and appointment management
- Improve natural language understanding for appointment requests
- Add email or SMS confirmations

## License

Add your preferred license here.
=======
# Hospital-Chatbot-using-fallback
Hospital Chatbot is an AI-powered appointment booking and patient support system built with Flask, SQLAlchemy, and MySQL/SQLite. It helps patients book or cancel doctor appointments, check doctor availability, route symptoms to the right department, and ask general health-related questions through a simple chat interface

