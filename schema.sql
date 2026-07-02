-- Evidence Preservation System - PostgreSQL Schema
-- All passwords stored as SHA-256 hashes

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Users table (Admin, Officers, Supervisors)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'officer', 'supervisor')),
    password_hash VARCHAR(64) NOT NULL,  -- SHA-256 hex
    department VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(50)
);

-- Cases table
CREATE TABLE IF NOT EXISTS cases (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(30) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    police_station VARCHAR(150),
    status VARCHAR(20) DEFAULT 'Active' CHECK (status IN ('Active', 'Closed', 'Pending', 'Archived')),
    created_by VARCHAR(50) REFERENCES users(user_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Case Allocations table (which officer/supervisor handles which case)
CREATE TABLE IF NOT EXISTS case_allocations (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(30) REFERENCES cases(case_id) ON DELETE CASCADE,
    user_id VARCHAR(50) REFERENCES users(user_id),
    role VARCHAR(20) NOT NULL CHECK (role IN ('officer', 'supervisor')),
    allocated_by VARCHAR(50) REFERENCES users(user_id),
    allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, user_id)
);

-- Evidence table
CREATE TABLE IF NOT EXISTS evidence (
    id SERIAL PRIMARY KEY,
    evidence_id VARCHAR(30) UNIQUE NOT NULL,
    case_id VARCHAR(30) REFERENCES cases(case_id) ON DELETE CASCADE,
    -- File details
    file_name VARCHAR(255),
    file_path VARCHAR(500),
    file_format VARCHAR(50),
    nature VARCHAR(100),  -- CCTV, Email, WhatsApp Chat, Audio, Video, Hard Disk, etc.
    date_creation TIMESTAMP,
    date_extraction TIMESTAMP,
    -- Device details
    device_type VARCHAR(100),  -- Computer, DVR, Mobile, Server
    device_make VARCHAR(100),
    serial_number VARCHAR(100),
    storage_capacity VARCHAR(50),
    -- Technical info
    operating_system VARCHAR(100),
    software_used VARCHAR(200),
    hash_algorithm VARCHAR(20) DEFAULT 'SHA-256',
    hash_value VARCHAR(128),  -- File integrity hash
    -- Storage media
    storage_media VARCHAR(100),  -- CD/DVD/Pen Drive/External HDD
    storage_id_mark VARCHAR(100),
    -- Status and metadata
    status VARCHAR(30) DEFAULT 'Pending' CHECK (status IN ('Pending', 'Verified', 'Rejected', 'Under Review')),
    uploaded_by VARCHAR(50) REFERENCES users(user_id),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verified_by VARCHAR(50) REFERENCES users(user_id),
    verified_at TIMESTAMP,
    notes TEXT
);

-- Chain of Custody table
CREATE TABLE IF NOT EXISTS chain_of_custody (
    id SERIAL PRIMARY KEY,
    evidence_id VARCHAR(30) REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    case_id VARCHAR(30) REFERENCES cases(case_id),
    from_user VARCHAR(50),
    to_user VARCHAR(50),
    transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    purpose TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Section 63 certificates log
CREATE TABLE IF NOT EXISTS section63_certificates (
    id SERIAL PRIMARY KEY,
    cert_id VARCHAR(30) UNIQUE NOT NULL,
    case_id VARCHAR(30) REFERENCES cases(case_id),
    evidence_id VARCHAR(30) REFERENCES evidence(evidence_id),
    issued_by VARCHAR(50) REFERENCES users(user_id),
    certifier_name VARCHAR(100),
    certifier_designation VARCHAR(100),
    certifier_department VARCHAR(100),
    place VARCHAR(100),
    issue_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Salary Payments table (Razorpay)
CREATE TABLE IF NOT EXISTS salary_payments (
    id SERIAL PRIMARY KEY,
    officer_id VARCHAR(50) REFERENCES users(user_id),
    amount NUMERIC(10,2) NOT NULL,
    razorpay_order_id VARCHAR(100),
    razorpay_payment_id VARCHAR(100),
    razorpay_signature VARCHAR(200),
    status VARCHAR(20) DEFAULT 'created' CHECK (status IN ('created','paid','failed')),
    paid_by VARCHAR(50) REFERENCES users(user_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    paid_at TIMESTAMP
);

-- Default Admin user (password: Admin@123 -> SHA-256)
-- SHA-256 of "Admin@123" = e86f78a8a3caf0b60d8e74e5942aa6d86dc150cd3c03338aef25b7d2d7e3acc7
INSERT INTO users (user_id, name, role, password_hash, department)
VALUES (
    'ADMIN001',
    'System Administrator',
    'admin',
    'e86f78a8a3caf0b60d8e74e5942aa6d86dc150cd3c03338aef25b7d2d7e3acc7',
    'Administration'
) ON CONFLICT (user_id) DO NOTHING;
