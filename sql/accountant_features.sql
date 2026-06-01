-- InvoScan accountant features: in-app notifications
-- Run against diva_demo (port 3307)

CREATE TABLE IF NOT EXISTS accountant_notifications (
    IDNotification INT AUTO_INCREMENT PRIMARY KEY,
    Username VARCHAR(50) NOT NULL,
    type VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    invoice_ref VARCHAR(100),
    is_read TINYINT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_unread (Username, is_read, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
