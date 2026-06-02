import React, { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { History, Loader2, RefreshCw } from "lucide-react";

const API_BASE_URL = "http://127.0.0.1:8000";

const FILTERS = [
  { id: "ALL", label: "All" },
  { id: "PENDING_ADMIN", label: "Pending Admin" },
  { id: "ON_HOLD", label: "On Hold" },
  { id: "POSTED_TO_ERP", label: "Posted to ERP" },
  { id: "VALIDATED", label: "Validated" },
  { id: "NEEDS_REVIEW", label: "Needs Review" },
  { id: "DISCREPANCY", label: "Discrepancies" },
];

function StatusBadge({ status }) {
  const map = {
    VALIDATED: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    NEEDS_REVIEW: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-300",
    DISCREPANCY: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
    PENDING_ADMIN: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300",
    ON_HOLD: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-200",
    POSTED_TO_ERP: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  };
  const label = status?.replace(/_/g, " ") || "Unknown";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        map[status] || "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
      }`}
    >
      {label}
    </span>
  );
}

function ScoreBar({ pct }) {
  const value = Math.min(100, Math.max(0, Number(pct) || 0));
  const color =
    value >= 85 ? "bg-emerald-500" : value >= 70 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div className={`h-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs font-bold text-slate-700 dark:text-slate-200">{value}%</span>
    </div>
  );
}

function mapSubmission(row) {
  return {
    id: row.id,
    lib_facture: row.lib_facture,
    invoice_number: row.invoice_number || row.lib_facture,
    supplier: row.supplier_name || "—",
    saved_at: row.submitted_at,
    validation_status: row.validation_status,
    workflow_status: row.workflow_status,
    review_score_pct: row.review_score_pct,
    line_count: row.line_count,
    valid_count: row.valid_count,
    total_ht: row.total_ht,
  };
}

export default function InvoiceHistoryPanel({ refreshKey = 0 }) {
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("ALL");

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await axios.get(`${API_BASE_URL}/api/accountant/submissions`, {
        params: { limit: 100, offset: 0 },
      });
      setInvoices((res.data.submissions || []).map(mapSubmission));
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to load submission history.");
      setInvoices([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory, refreshKey]);

  const filtered = useMemo(() => {
    if (filter === "ALL") return invoices;
    if (["PENDING_ADMIN", "ON_HOLD", "POSTED_TO_ERP"].includes(filter)) {
      return invoices.filter((inv) => inv.workflow_status === filter);
    }
    return invoices.filter((inv) => inv.validation_status === filter);
  }, [invoices, filter]);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-indigo-100 p-2 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300">
            <History size={20} />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100">Submission History</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Invoices you submitted for administrative ERP approval
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={loadHistory}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          Refresh
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFilter(f.id)}
            className={`rounded-full px-4 py-1.5 text-xs font-bold transition ${
              filter === f.id
                ? "bg-indigo-600 text-white shadow"
                : "border border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex min-h-[200px] items-center justify-center text-slate-500 dark:text-slate-400">
          <Loader2 size={32} className="animate-spin text-indigo-600" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 py-16 text-center dark:border-slate-700">
          <p className="font-semibold text-slate-700 dark:text-slate-200">No submissions yet</p>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Submit an invoice for administrative approval to see it here.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[800px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs font-bold uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
              <tr>
                <th className="px-4 py-3">Invoice #</th>
                <th className="px-4 py-3">Supplier</th>
                <th className="px-4 py-3">Submitted</th>
                <th className="px-4 py-3">Workflow</th>
                <th className="px-4 py-3">Validation</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Total HT</th>
                <th className="px-4 py-3">Lines</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {filtered.map((inv) => (
                <tr
                  key={inv.id}
                  className="bg-white transition hover:bg-slate-50 dark:bg-slate-900 dark:hover:bg-slate-800/80"
                >
                  <td className="px-4 py-3 font-mono font-semibold text-slate-800 dark:text-slate-100">
                    {inv.invoice_number || inv.lib_facture}
                  </td>
                  <td className="max-w-[200px] truncate px-4 py-3 text-slate-700 dark:text-slate-300">
                    {inv.supplier || "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {inv.saved_at ? String(inv.saved_at).slice(0, 10) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={inv.workflow_status} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={inv.validation_status} />
                  </td>
                  <td className="px-4 py-3">
                    <ScoreBar pct={inv.review_score_pct} />
                  </td>
                  <td className="px-4 py-3 font-mono text-slate-700 dark:text-slate-300">
                    {Number(inv.total_ht || 0).toFixed(3)}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {inv.valid_count}/{inv.line_count} valid
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
