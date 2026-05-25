-- Admin dashboard tables for diva_demo
-- Run once in DBeaver or: mysql -h 127.0.0.1 -P 3307 -u root -p diva_demo < sql/admin_schema.sql

CREATE TABLE IF NOT EXISTS system_users (
    IDUser INT AUTO_INCREMENT PRIMARY KEY,
    Username VARCHAR(50) NOT NULL UNIQUE,
    Email VARCHAR(150) NOT NULL UNIQUE,
    PasswordHash VARCHAR(255) NOT NULL,
    Role ENUM('ACCOUNTANT', 'ADMINISTRATOR') NOT NULL DEFAULT 'ACCOUNTANT',
    Status ENUM('ACTIVE', 'SUSPENDED') NOT NULL DEFAULT 'ACTIVE',
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    IDRun INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255),
    page_count INT DEFAULT 0,
    duration_ms INT DEFAULT 0,
    invoice_number VARCHAR(100),
    line_count INT DEFAULT 0,
    valid_count INT DEFAULT 0,
    low_conf_count INT DEFAULT 0,
    price_mismatch_count INT DEFAULT 0,
    unknown_count INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'SUCCESS',
    run_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Default admin (password: admin123) — bcrypt hash generated via scripts/seed_admin_user.py
-- INSERT IGNORE INTO system_users (Username, Email, PasswordHash, Role, Status)
-- VALUES ('admin', 'admin@motion.div', '<bcrypt_hash>', 'ADMINISTRATOR', 'ACTIVE');
