from __future__ import annotations
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Optional
import psycopg2
from psycopg2.extras import Json

MILLIME = Decimal("0.001")

def _to_decimal_3(value: Any) -> Optional[Decimal]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        if isinstance(value, str):
            # Cleans Tunisian formatting: "102 515.849" -> "102515.849"
            value = value.replace("TND", "").replace("DT", "").replace(" ", "").replace(",", ".").strip()
        d = Decimal(str(value))
        return d.quantize(MILLIME, rounding=ROUND_HALF_UP)
    except Exception:
        return None

def _json_dumps_decimal_safe(obj: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, Decimal): return format(o, "f")
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")
    return json.dumps(obj, ensure_ascii=False, default=default)

# --- THE HELPER FUNCTION ---
def extract_value(ai_item: dict, possible_keys: list) -> any:
    """Helper to find keys ignoring UPPERCASE/lowercase and extra spaces."""
    if not isinstance(ai_item, dict): return None
    # Convert all AI keys to lowercase for safe searching
    item_lower = {str(k).lower().strip(): v for k, v in ai_item.items()}
    
    for key in possible_keys:
        safe_key = key.lower().strip()
        if safe_key in item_lower and item_lower[safe_key] not in (None, ""):
            return item_lower[safe_key]
    return None

@dataclass(frozen=True)
class DBConfig:
    host: str = "localhost"
    port: int = 5432
    dbname: str = "invoice_intelligence"
    user: str = "postgres"
    password: str = "diva"

class InvoiceDBHandler:
    def __init__(self, config: DBConfig | None = None):
        self._cfg = config or DBConfig()

    def _connect(self):
        return psycopg2.connect(
            host=self._cfg.host, port=self._cfg.port,
            dbname=self._cfg.dbname, user=self._cfg.user, password=self._cfg.password
        )

    def get_connection(self):
        return self._connect()

    def _pick_first(self, obj: Mapping[str, Any], *keys: str) -> Any:
        for k in keys:
            if k in obj and obj.get(k) not in (None, ""):
                return obj.get(k)
        return None

    def save_extraction(self, extraction_json: Mapping[str, Any]) -> Any:
        header = extraction_json.get("header") or {}
        totals = extraction_json.get("totals") or {}
        
        if not isinstance(header, Mapping) or not isinstance(totals, Mapping):
            raise TypeError("extraction_json must contain 'header' and 'totals' dicts")

        # --- Header mapping ---
        doc_num = self._pick_first(header, "doc_number", "invoice_number", "DOCUMENT N°", "Document N°", "N°")
        doc_date = self._pick_first(header, "doc_date", "invoice_date", "DATE", "Date")
        
        # --- Totals mapping ---
        total_ht = self._pick_first(totals, "total_ht", "TOTAL NET HT", "TOTAL HT")
        total_tva = self._pick_first(totals, "total_tva", "tva", "TVA", "TOTAL TVA")
        total_ttc = self._pick_first(totals, "total_ttc", "TOTAL TTC", "TTC")
        status = self._pick_first(extraction_json, "status") or "extracted"

        conn = self.get_connection()
        try:
            conn.autocommit = False
            with conn.cursor() as cur:
                # Teach Postgres how to read Tunisian / European day-first dates (e.g. DD/MM/YYYY).
                cur.execute("SET datestyle = 'ISO, DMY';")

                # 1. INSERT HEADER
                cur.execute(
                    """
                    INSERT INTO invoices (doc_number, doc_date, total_ht, total_tva, total_ttc, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING invoice_id
                    """,
                    (doc_num, doc_date, _to_decimal_3(total_ht), _to_decimal_3(total_tva), _to_decimal_3(total_ttc), status)
                )
                invoice_id = cur.fetchone()[0]

                # 2. INSERT LINE ITEMS (Using the robust translator!)
                line_items = extraction_json.get("line_items") or []
                for item in line_items:
                    if not isinstance(item, Mapping):
                        continue
                    
                    # Grab the Code
                    ai_code = extract_value(item, ["code", "article", "code pct", "reference", "code produit"])

                    # Grab the Designation / Name
                    ai_item_name = extract_value(item, ["designation", "libelle", "designation artile", "designation produit", "forme", "raw_label"])

                    # Grab the Quantity
                    ai_quantity = extract_value(item, ["quantité", "qté", "qte cmde", "stk", "proposé", "quantité a commander", "quantite en stock", "colis", "ucrt", "quantity"])

                    # Grab the Unit Price
                    ai_price = extract_value(item, ["prix unitaire", "p.u.ht", "premp", "unit_price", "unit_price_ht"])

                    # Grab the Line Total
                    ai_line_total = extract_value(item, ["total", "montant", "total ht", "line_total_ttc"])

                    # Put it in the strict SQL columns
                    cur.execute(
                        """
                        INSERT INTO invoice_lines (
                            invoice_id, raw_code, raw_label, quantity, unit_price_ht, line_total_ttc
                        ) 
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            invoice_id,           
                            ai_code,              
                            ai_item_name,         
                            _to_decimal_3(ai_quantity), 
                            _to_decimal_3(ai_price),
                            _to_decimal_3(ai_line_total)
                        )
                    )

                # 3. INSERT METADATA
                cur.execute(
                    "INSERT INTO extraction_metadata (invoice_id, raw_json) VALUES (%s, %s)",
                    (invoice_id, Json(extraction_json, dumps=_json_dumps_decimal_safe))
                )

            conn.commit()
            return invoice_id
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()