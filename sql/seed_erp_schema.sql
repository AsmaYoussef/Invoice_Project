-- Core ERP schema for diva_demo
-- Recreates all tables required by the OCR reconciliation pipeline

CREATE TABLE IF NOT EXISTS fournisseur (
    IDFournisseur INT AUTO_INCREMENT PRIMARY KEY,
    Code VARCHAR(50),
    Nom VARCHAR(255),
    MF VARCHAR(50),
    Adresse VARCHAR(255),
    Tel VARCHAR(30),
    Fax VARCHAR(30)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS article (
    IDArticle INT AUTO_INCREMENT PRIMARY KEY,
    Code VARCHAR(50) NOT NULL,
    LibProd VARCHAR(255),
    PrixAchat DECIMAL(12,3) DEFAULT 0,
    PrixVente DECIMAL(12,3) DEFAULT 0,
    TauxTVA DECIMAL(5,2) DEFAULT 19.00,
    IDFournisseur INT DEFAULT NULL,
    INDEX idx_code (Code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS facture (
    IDFacture INT AUTO_INCREMENT PRIMARY KEY,
    LibFacture VARCHAR(100) UNIQUE,
    DateFacture DATE,
    Client VARCHAR(150),
    TotalHT DECIMAL(12,3) DEFAULT 0,
    TotalTTC DECIMAL(12,3) DEFAULT 0,
    TotalTVA DECIMAL(12,3) DEFAULT 0,
    MF VARCHAR(20),
    Adresse VARCHAR(150),
    SaisiPar VARCHAR(50),
    SaisiLe DATE,
    Observations TEXT,
    CoordonneesBancaires VARCHAR(255) DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS lignefac (
    IDLigneFac INT AUTO_INCREMENT PRIMARY KEY,
    IDFacture INT NOT NULL,
    IDArticle INT DEFAULT 0,
    Code VARCHAR(50),
    LibProd VARCHAR(255),
    Quantite DECIMAL(12,3) DEFAULT 0,
    PrixVente DECIMAL(12,3) DEFAULT 0,
    prixMP DECIMAL(12,3) DEFAULT 0,
    TauxTVA DECIMAL(5,2) DEFAULT 19.00,
    Ordre INT DEFAULT 0,
    INDEX idx_facture (IDFacture)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS reconciliation_alerts (
    IDAlert INT AUTO_INCREMENT PRIMARY KEY,
    IDFacture INT NOT NULL,
    type VARCHAR(50),
    description TEXT,
    is_resolved TINYINT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_facture (IDFacture)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS extraction_metadata (
    IDMeta INT AUTO_INCREMENT PRIMARY KEY,
    IDFacture INT NOT NULL,
    raw_json LONGTEXT,
    avg_confidence DECIMAL(5,3) DEFAULT 0,
    model_version VARCHAR(30),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_facture (IDFacture)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Admin tables
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

-- Seed sample supplier and articles for Avenir MEDIS demo
INSERT IGNORE INTO fournisseur (Code, Nom, MF, Adresse)
VALUES ('AVENIR', 'AVENIR MEDIS', '1234567/A', 'Sfax, Tunisie');

SET @frs_id = LAST_INSERT_ID();

INSERT IGNORE INTO article (Code, LibProd, PrixAchat, IDFournisseur) VALUES
('MP680046', 'DOLIPRANE 1000MG BT/8',           2.450, @frs_id),
('MP680047', 'DOLIPRANE 500MG BT/16',           1.850, @frs_id),
('MP601413', 'AMOXICILLINE 1G BT/12',           4.200, @frs_id),
('MP601414', 'AMOXICILLINE 500MG BT/12',        3.100, @frs_id),
('MP680300', 'IBUPROFEN 400MG BT/30',           3.750, @frs_id),
('MP680301', 'PARACETAMOL 500MG BT/16',         1.650, @frs_id),
('MP600100', 'CLAMOXYL 500MG BT/12',            5.950, @frs_id),
('MP600101', 'AUGMENTIN 1G BT/12',              8.200, @frs_id),
('MP600200', 'ASPIRIN 100MG BT/30',             2.100, @frs_id),
('MP600201', 'VOLTARENE 50MG BT/30',            4.500, @frs_id);
