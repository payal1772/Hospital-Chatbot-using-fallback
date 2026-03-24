CREATE DATABASE IF NOT EXISTS hospital_chatbot;
USE hospital_chatbot;

CREATE TABLE IF NOT EXISTS doctors (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  department VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  contact VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  patient_id INT NOT NULL,
  doctor_id INT NOT NULL,
  appointment_date DATE NOT NULL,
  time_slot VARCHAR(20) NOT NULL,
  symptoms TEXT,
  status VARCHAR(20) DEFAULT 'booked',
  CONSTRAINT fk_patient FOREIGN KEY (patient_id) REFERENCES patients(id),
  CONSTRAINT fk_doctor FOREIGN KEY (doctor_id) REFERENCES doctors(id)
);

INSERT INTO doctors (name, department) VALUES
('Dr. Meera Thomas','General Medicine'),
('Dr. Ravi Kumar','General Medicine'),
('Dr. Rajesh Kumar','Pediatrics'),
('Dr. Sunita Patel','Neurology'),
('Dr. Anil Sharma','Cardiology'),
('Dr. Asha Nair','Cardiology'),
('Dr. Vivek Rao','Orthopedics'),
('Dr. Arjun Singh','Orthopedics'),
('Dr. Priya Desai','Dermatology'),
('Dr. Suresh Menon','Dermatology'),
('Dr. Kavita Joshi','Gynecology'),
('Dr. Ramesh Gupta','Gynecology'),
('Dr. Anjali Verma','Psychiatry'),
('Dr. Sanjay Mehta','Psychiatry');
