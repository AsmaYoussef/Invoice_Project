-- Drop and recreate the column with a clean ASCII name
-- The original column was corrupted: 'Quantit??' instead of 'Quantité'
ALTER TABLE lignefac DROP COLUMN `Quantit??`;
ALTER TABLE lignefac ADD COLUMN Quantite DECIMAL(12,3) DEFAULT 0 AFTER LibProd;
