import React, { useMemo, useState } from "react";
import axios from "axios";
import {
  Activity,
  CheckCircle2,
  Database,
  Download,
  Eye,
  FileText,
  Loader2,
  LogOut,
  RefreshCw,
  Settings2,
  Upload,
  AlertCircle,
  History,
} from "lucide-react";

import InvoScanLogo from "./InvoScanLogo";
import InvoiceHistoryPanel from "./InvoiceHistoryPanel";
import NotificationBell from "./NotificationBell";
import ThemeToggle from "./ThemeToggle";

const API_BASE_URL = "http://127.0.0.1:8000";

const DEFAULT_PIPELINE_STATUS = {
  preprocessing: "Deskew & Thresholding Active",
  ocr_engine: "Tesseract OCR + Layout Recovery Active",
  nlp_layer: "Extract-Lock-Clean Architecture Active",
};

const DPI_OPTIONS = [150, 200, 300];

function formatApiError(error, fallback) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  }
  if (detail && typeof detail === "object") {
    return JSON.stringify(detail);
  }
  return error?.message || fallback;
}

function safeNum(raw) {
  if (raw === "" || raw == null) return null;
  const n = Number(String(raw).replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function formatTunisianPhone(raw) {
  const digits = String(raw ?? "").replace(/\D/g, "");
  if (!digits) return "";
  if (digits.length === 8) {
    return `${digits.slice(0, 2)} ${digits.slice(2, 5)} ${digits.slice(5)}`;
  }
  return digits;
}

function downloadBlob(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const TabButton = ({ active, icon: Icon, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition ${
      active
        ? "bg-slate-900 text-white shadow dark:bg-indigo-600"
        : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
    }`}
  >
    <Icon size={16} />
    {label}
  </button>
);

const InfoField = ({ label, value }) => (
  <div className="space-y-1">
    <p className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</p>
    <p className="min-h-9 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100">
      {String(value ?? "") || "—"}
    </p>
  </div>
);

const ValidationBadge = ({ status }) => {
  switch (status) {
    case "VALID":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
          Valid
        </span>
      );
    case "PRICE_MISMATCH":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
          Price mismatch
        </span>
      );
    case "LOW_CONFIDENCE":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
          Low confidence
        </span>
      );
    case "UNKNOWN_PRODUCT":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-900">
          Unknown product
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
          Unchecked
        </span>
      );
  }
};

const rowClassForStatus = (status) => {
  switch (status) {
    case "VALID":
      return "bg-emerald-50/60 hover:bg-emerald-50 dark:bg-emerald-950/40 dark:hover:bg-emerald-950/60";
    case "PRICE_MISMATCH":
    case "UNKNOWN_PRODUCT":
      return "bg-red-50/70 hover:bg-red-50 dark:bg-red-950/40 dark:hover:bg-red-950/60";
    case "LOW_CONFIDENCE":
      return "bg-amber-50/70 hover:bg-amber-50 dark:bg-amber-950/40 dark:hover:bg-amber-950/60";
    default:
      return "hover:bg-slate-50 dark:hover:bg-slate-800/80";
  }
};

const StatusLine = ({ label }) => (
  <div className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-300">
    <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" aria-hidden />
    <span>{label}</span>
  </div>
);

const PipelineStatusPanel = ({
  pipelineStatus,
  dpiChoice,
  onDpiChange,
  showCleanJson,
  onShowCleanJsonChange,
}) => {
  const status = { ...DEFAULT_PIPELINE_STATUS, ...(pipelineStatus || {}) };
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-950">
      <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
        <Settings2 size={14} /> Pipeline Status
      </p>
      <div className="space-y-2">
        <StatusLine label={`Preprocessing: ${status.preprocessing}`} />
        <StatusLine label={`OCR Engine: ${status.ocr_engine}`} />
        <StatusLine label={`NLP / Logic Layer: ${status.nlp_layer}`} />
      </div>
      <div className="border-t border-slate-200 pt-3 dark:border-slate-700">
        <label className="mb-1 block text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Processing DPI
        </label>
        <select
          value={dpiChoice}
          onChange={(ev) => onDpiChange(Number(ev.target.value))}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
        >
          {DPI_OPTIONS.map((dpi) => (
            <option key={dpi} value={dpi}>
              {dpi} DPI
            </option>
          ))}
        </select>
        <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">Applied on next Analyze / Re-Analyze</p>
      </div>
      <div className="border-t border-slate-200 pt-3 dark:border-slate-700">
        <label className="flex cursor-pointer items-start gap-2 text-sm text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-900"
            checked={showCleanJson}
            onChange={(ev) => onShowCleanJsonChange(ev.target.checked)}
          />
          <span>
            <span className="block text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Debug
            </span>
            Show Cleaned Pipeline JSON
          </span>
        </label>
      </div>
    </div>
  );
};

const PageCompareCard = ({ page, index }) => (
  <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
    <p className="mb-4 text-xs font-black uppercase tracking-widest text-slate-400">
      Page {page.page ?? index + 1}
    </p>
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase text-slate-500">Original Upload</p>
        <div className="max-h-[480px] overflow-auto rounded-xl border border-slate-100 bg-slate-50 p-2">
          {page.original_image_b64 ? (
            <img
              src={page.original_image_b64}
              alt={`Original page ${index + 1}`}
              className="mx-auto w-full object-contain"
            />
          ) : (
            <p className="p-4 text-sm text-slate-400">Original preview unavailable</p>
          )}
        </div>
      </div>
      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase text-slate-500">Cleaned Binary</p>
        <div className="max-h-[480px] overflow-auto rounded-xl border border-slate-100 bg-slate-50 p-2">
          {page.cleaned_image_b64 ? (
            <img
              src={page.cleaned_image_b64}
              alt={`Cleaned page ${index + 1}`}
              className="mx-auto w-full object-contain"
            />
          ) : (
            <p className="p-4 text-sm text-slate-400">Cleaned preview unavailable</p>
          )}
        </div>
      </div>
    </div>
  </div>
);

const SupplierBanner = ({ generalInfo }) => {
  const matched = generalInfo?.supplier_status === "SUPPLIER_MATCH";
  const tel = formatTunisianPhone(generalInfo?.tel);
  const fax = formatTunisianPhone(generalInfo?.fax);
  return (
    <div
      className={`rounded-xl border p-4 ${
        matched
          ? "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/50"
          : "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/50"
      }`}
    >
      <p className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        Supplier reconciliation
      </p>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <div>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">OCR extracted</p>
          <p className="font-semibold text-slate-900 dark:text-slate-100">{generalInfo?.supplier_name || "—"}</p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">ERP reference</p>
          <p className="font-semibold text-indigo-700 dark:text-indigo-400">
            {generalInfo?.erp_supplier_name || "No match in fournisseur"}
          </p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">Telephone</p>
          <p className="font-mono font-semibold text-slate-800 dark:text-slate-200">{tel || "—"}</p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">Fax</p>
          <p className="font-mono font-semibold text-slate-800 dark:text-slate-200">{fax || "—"}</p>
        </div>
      </div>
    </div>
  );
};

const AccountantDashboard = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [dashboard, setDashboard] = useState(null);
  const [visualizer, setVisualizer] = useState(null);
  const [technical, setTechnical] = useState(null);
  const [loading, setLoading] = useState(false);
  const [revalidateLoading, setRevalidateLoading] = useState(false);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncSuccess, setSyncSuccess] = useState(false);
  const [apiError, setApiError] = useState("");
  const [showCleanJson, setShowCleanJson] = useState(false);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  const [settings, setSettings] = useState({
    use_nlp: true,
    dpi_choice: 200,
    use_fix_rotation: true,
    use_erase_color: true,
    use_remove_lines: true,
    use_keep_mask: true,
  });

  const generalInfo = dashboard?.general_info || {};
  const financialTotals = dashboard?.financial_totals || {};
  const productLines = dashboard?.product_lines || [];
  const pages = visualizer?.pages || [];

  const statusCounts = useMemo(() => {
    const c = { VALID: 0, PRICE_MISMATCH: 0, LOW_CONFIDENCE: 0, UNKNOWN_PRODUCT: 0 };
    productLines.forEach((l) => {
      if (c[l.validation_status] !== undefined) c[l.validation_status] += 1;
    });
    return c;
  }, [productLines]);

  const topConfidence = useMemo(() => {
    const scores = productLines.map((l) => l.confidence).filter((v) => typeof v === "number");
    if (!scores.length) return "—";
    const avg = (scores.reduce((a, v) => a + v, 0) / scores.length) * 100;
    return `${avg.toFixed(0)}%`;
  }, [productLines]);

  const updateLine = (index, field, value) => {
    setDashboard((prev) => {
      if (!prev) return prev;
      const lines = [...prev.product_lines];
      const next = { ...lines[index], [field]: value };
      if (field === "price_unit") {
        next.ocr_price = value;
        next.price_from_db = false;
      }
      lines[index] = next;
      return { ...prev, product_lines: lines };
    });
  };

  const updateLineCodes = (index, value) => {
    setDashboard((prev) => {
      if (!prev) return prev;
      const lines = [...prev.product_lines];
      lines[index] = {
        ...lines[index],
        code_pct: value,
        code: value,
      };
      return { ...prev, product_lines: lines };
    });
  };

  const buildApiPayload = (payload) => ({
    general_info: payload.general_info || {},
    financial_totals: payload.financial_totals || {
      total_ht: 0,
      total_ttc: 0,
      tva: 0,
    },
    product_lines: (payload.product_lines || []).map((line) => ({
      code: String(line.code || ""),
      code_pct: String(line.code_pct || line.code || ""),
      code_article: String(line.code_article || ""),
      designation: String(line.designation || line.erp_name || ""),
      quantite: String(line.quantite ?? ""),
      ocr_price: safeNum(line.ocr_price ?? line.price_unit),
      price_unit: safeNum(line.price_unit),
      erp_price: line.erp_price != null ? Number(line.erp_price) : null,
      erp_name: line.erp_name || null,
      validation_status: line.validation_status || "UNCHECKED",
      confidence: typeof line.confidence === "number" ? line.confidence : null,
      flags: Array.isArray(line.flags) ? line.flags : [],
      computed_montant: line.computed_montant ?? null,
      id_article: line.id_article ?? null,
      price_from_db: Boolean(line.price_from_db),
    })),
  });

  const runUpload = async () => {
    if (!selectedFile) return;
    setLoading(true);
    setApiError("");
    setSyncSuccess(false);

    const formData = new FormData();
    formData.append("file", selectedFile);
    Object.entries(settings).forEach(([key, value]) => {
      formData.append(key, String(value));
    });

    try {
      const response = await axios.post(`${API_BASE_URL}/upload-invoice`, formData);
      setDashboard(response.data.dashboard);
      setVisualizer(response.data.visualizer);
      setTechnical(response.data.technical || {});
      setActiveTab("dashboard");
    } catch (error) {
      setApiError(formatApiError(error, "Connection failed. Is the API running?"));
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (e) => {
    e?.preventDefault?.();
    await runUpload();
  };

  const handleRevalidate = async (e) => {
    e?.preventDefault?.();
    if (!dashboard) return;
    setRevalidateLoading(true);
    setApiError("");
    try {
      const response = await axios.post(
        `${API_BASE_URL}/revalidate`,
        buildApiPayload(dashboard)
      );
      setDashboard((prev) => ({
        ...prev,
        ...response.data.dashboard,
        financial_totals:
          response.data.dashboard?.financial_totals ?? prev?.financial_totals,
      }));
    } catch (error) {
      setApiError(formatApiError(error, "Re-validation failed."));
    } finally {
      setRevalidateLoading(false);
    }
  };

  const handleSave = async (e) => {
    e?.preventDefault?.();
    if (!dashboard) return;
    setSyncLoading(true);
    setApiError("");
    try {
      const response = await axios.post(
        `${API_BASE_URL}/save-invoice`,
        buildApiPayload(dashboard)
      );
      setSyncSuccess(true);
      setApiError("");
      setHistoryRefreshKey((k) => k + 1);
      console.log("Saved:", response.data);
    } catch (error) {
      setApiError(formatApiError(error, "Save to ERP failed. Check MySQL and seed data."));
    } finally {
      setSyncLoading(false);
    }
  };

  const handleDownloadCleanJson = (e) => {
    e.preventDefault();
    const payload = technical?.clean_json || dashboard || {};
    downloadBlob(JSON.stringify(payload, null, 2), "invoice-clean.json", "application/json");
  };

  const handleDownloadRawOcr = (e) => {
    e.preventDefault();
    downloadBlob(technical?.raw_ocr_text || "", "invoice-raw-ocr.txt", "text/plain;charset=utf-8");
  };

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-800 dark:bg-slate-950 dark:text-slate-100">
      <div className="grid min-h-screen grid-cols-12">
        <aside className="col-span-12 border-r border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900 lg:col-span-3">
          <div className="mb-6 flex items-center justify-between gap-2">
            <div className="flex items-center gap-3">
            <div className="rounded-lg bg-indigo-600 p-2 text-white">
              <InvoScanLogo size={20} />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight">InvoScan</h1>
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Invoice Extraction v2.0</p>
            </div>
            </div>
            <ThemeToggle />
          </div>

          <PipelineStatusPanel
            pipelineStatus={technical?.pipeline_status}
            dpiChoice={settings.dpi_choice}
            onDpiChange={(dpi) => setSettings((prev) => ({ ...prev, dpi_choice: dpi }))}
            showCleanJson={showCleanJson}
            onShowCleanJsonChange={setShowCleanJson}
          />

          <div className="mt-6 space-y-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">
              <p className="font-medium text-slate-600 dark:text-slate-300">
                Signed in as <span className="font-bold text-indigo-600">{localStorage.getItem("username") || "accountant"}</span>
              </p>
            </div>
            <button
              type="button"
              onClick={() => { localStorage.clear(); window.location.href = "/login"; }}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-semibold text-red-600 transition hover:bg-red-100 active:scale-[0.98] dark:border-red-900 dark:bg-red-950/40 dark:text-red-400 dark:hover:bg-red-950/60"
            >
              <LogOut size={16} />
              Sign Out
            </button>
          </div>
        </aside>

        <main className="col-span-12 p-8 lg:col-span-9">
          <header className="mb-8 flex flex-col gap-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-slate-100">
                Invoice Reconciliation
              </h2>
              <p className="text-slate-500 dark:text-slate-400">
                Extract, validate against ERP, and save to facture / lignefac.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <NotificationBell />
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 transition hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700">
                <Upload size={16} />
                <span>{selectedFile?.name || "Select Document"}</span>
                <input
                  type="file"
                  className="hidden"
                  onChange={(ev) => setSelectedFile(ev.target.files?.[0] || null)}
                />
              </label>

              <button
                type="button"
                onClick={handleUpload}
                disabled={!selectedFile || loading}
                className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-bold text-white shadow-lg transition hover:bg-indigo-700 disabled:opacity-50"
              >
                {loading ? <Loader2 size={18} className="animate-spin" /> : <FileText size={18} />}
                {loading ? "Analyzing..." : dashboard && selectedFile ? "Re-Analyze" : "Analyze"}
              </button>

              <button
                type="button"
                onClick={handleRevalidate}
                disabled={!dashboard || revalidateLoading}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 py-2.5 text-sm font-bold text-slate-800 shadow transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
              >
                {revalidateLoading ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
                Re-Validate
              </button>

              <button
                type="button"
                onClick={handleSave}
                disabled={!dashboard || syncLoading}
                className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-2.5 text-sm font-bold text-white shadow-lg transition hover:bg-emerald-700 disabled:opacity-50"
              >
                {syncLoading ? <Loader2 size={18} className="animate-spin" /> : <Database size={18} />}
                {syncSuccess ? "Saved to ERP" : "Save to ERP"}
              </button>
            </div>
          </header>

          {apiError && (
            <div className="mb-6 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 shadow-sm">
              <AlertCircle size={18} />
              <p className="font-semibold">{apiError}</p>
            </div>
          )}

          {syncSuccess && (
            <div className="mb-6 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-800">
              Document saved to ERP (facture + lignefac).
            </div>
          )}

          <div className="mb-6 flex gap-2">
            <TabButton
              active={activeTab === "dashboard"}
              icon={CheckCircle2}
              label={`Review (${topConfidence})`}
              onClick={() => setActiveTab("dashboard")}
            />
            <TabButton
              active={activeTab === "visualizer"}
              icon={Eye}
              label="PDF Visualizer"
              onClick={() => setActiveTab("visualizer")}
            />
            <TabButton
              active={activeTab === "technical"}
              icon={Activity}
              label="Raw Data"
              onClick={() => setActiveTab("technical")}
            />
            <TabButton
              active={activeTab === "history"}
              icon={History}
              label="History"
              onClick={() => setActiveTab("history")}
            />
          </div>

          {dashboard && activeTab === "dashboard" && (
            <div className="mb-4 flex flex-wrap gap-2 text-xs font-semibold">
              <span className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-800">
                Valid: {statusCounts.VALID}
              </span>
              <span className="rounded-full bg-red-100 px-3 py-1 text-red-800">
                Price mismatch: {statusCounts.PRICE_MISMATCH}
              </span>
              <span className="rounded-full bg-amber-100 px-3 py-1 text-amber-900">
                Low confidence (&lt;85%): {statusCounts.LOW_CONFIDENCE}
              </span>
              <span className="rounded-full bg-red-50 px-3 py-1 text-red-900">
                Unknown: {statusCounts.UNKNOWN_PRODUCT}
              </span>
            </div>
          )}

          {!dashboard && !loading && (
            <div className="flex min-h-[400px] flex-col items-center justify-center rounded-3xl border-2 border-dashed border-slate-300 bg-white p-12 text-center shadow-inner dark:border-slate-700 dark:bg-slate-900">
              <div className="mb-4 rounded-full bg-slate-100 p-4 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
                <Upload size={48} />
              </div>
              <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100">Ready to start</h3>
              <p className="max-w-xs text-slate-500 dark:text-slate-400">
                Upload a supplier invoice. Run seed SQL in DBeaver first if the demo DB is empty.
              </p>
            </div>
          )}

          {dashboard && activeTab === "dashboard" && (
            <div className="space-y-6">
              <SupplierBanner generalInfo={generalInfo} />

              <div className="grid grid-cols-12 gap-6">
                <section className="col-span-12 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900 xl:col-span-8">
                  <h3 className="mb-6 text-sm font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                    Header Information
                  </h3>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <InfoField label="Invoice #" value={generalInfo.invoice_number} />
                    <InfoField label="Date" value={generalInfo.invoice_date} />
                    <InfoField label="Supplier Name" value={generalInfo.supplier_name} />
                    <InfoField label="Supplier MF" value={generalInfo.supplier_mf} />
                    <InfoField label="Telephone" value={formatTunisianPhone(generalInfo.tel)} />
                    <InfoField label="Fax" value={formatTunisianPhone(generalInfo.fax)} />
                    <div className="md:col-span-2">
                      <InfoField label="Physical Address" value={generalInfo.address} />
                    </div>
                  </div>
                </section>

                <section className="col-span-12 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900 xl:col-span-4">
                  <h3 className="mb-6 text-sm font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                    Financial Summary
                  </h3>
                  <div className="space-y-4">
                    <div className="flex justify-between border-b border-slate-100 pb-2 dark:border-slate-800">
                      <span className="text-sm text-slate-500 dark:text-slate-400">Total HT</span>
                      <span className="font-bold text-slate-900 dark:text-slate-100">
                        {financialTotals.total_ht ?? "—"} TND
                      </span>
                    </div>
                    <div className="flex justify-between border-b border-slate-100 pb-2 dark:border-slate-800">
                      <span className="text-sm text-slate-500 dark:text-slate-400">TVA</span>
                      <span className="font-bold text-slate-900 dark:text-slate-100">
                        {financialTotals.tva ?? "—"} TND
                      </span>
                    </div>
                    <div className="flex justify-between pt-2">
                      <span className="text-base font-bold text-slate-900 dark:text-slate-100">Total TTC</span>
                      <span className="text-xl font-black text-indigo-600 dark:text-indigo-400">
                        {financialTotals.total_ttc ?? "—"} TND
                      </span>
                    </div>
                  </div>
                </section>
              </div>

              <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                <h3 className="mb-6 text-sm font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                  Line Item Validation
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b-2 border-slate-100 text-left text-xs font-black uppercase tracking-widest text-slate-400 dark:border-slate-800 dark:text-slate-500">
                        <th className="pb-4 pr-2">Status</th>
                        <th className="pb-4 pr-2">Code / MP</th>
                        <th className="pb-4 pr-2">Article PF</th>
                        <th className="pb-4 pr-2">Designation</th>
                        <th className="pb-4 pr-2">Qty</th>
                        <th className="pb-4 pr-2">OCR Price</th>
                        <th className="pb-4">ERP Price</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                      {productLines.map((line, idx) => (
                        <tr key={idx} className={rowClassForStatus(line.validation_status)}>
                          <td className="py-3 pr-2">
                            <ValidationBadge status={line.validation_status} />
                            {typeof line.confidence === "number" && (
                              <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">
                                {(line.confidence * 100).toFixed(0)}%
                              </p>
                            )}
                          </td>
                          <td className="py-3 pr-2">
                            <input
                              className="w-24 rounded border border-slate-200 bg-white px-2 py-1 font-mono text-xs dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                              value={line.code_pct || line.code || ""}
                              onChange={(ev) => updateLineCodes(idx, ev.target.value)}
                            />
                          </td>
                          <td className="py-3 pr-2">
                            <input
                              className="w-28 rounded border border-slate-200 bg-white px-2 py-1 font-mono text-xs dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                              value={line.code_article || ""}
                              onChange={(ev) => updateLine(idx, "code_article", ev.target.value)}
                            />
                          </td>
                          <td className="py-3 pr-2">
                            <input
                              className="min-w-[180px] rounded border border-slate-200 bg-white px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                              value={line.designation || line.erp_name || ""}
                              onChange={(ev) => updateLine(idx, "designation", ev.target.value)}
                            />
                          </td>
                          <td className="py-3 pr-2">
                            <input
                              className="w-16 rounded border border-slate-200 bg-white px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                              value={line.quantite ?? ""}
                              onChange={(ev) => updateLine(idx, "quantite", ev.target.value)}
                            />
                          </td>
                          <td className="py-3 pr-2">
                            <input
                              className="w-20 rounded border border-slate-200 bg-white px-2 py-1 text-xs font-bold dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                              value={line.ocr_price ?? line.price_unit ?? ""}
                              onChange={(ev) => updateLine(idx, "price_unit", ev.target.value)}
                            />
                          </td>
                          <td className="py-3 font-black text-indigo-600 dark:text-indigo-400">
                            {line.erp_price != null && Number.isFinite(Number(line.erp_price))
                              ? Number(line.erp_price).toFixed(3)
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          )}

          {dashboard && activeTab === "visualizer" && (
            <div className="space-y-6">
              {pages.length === 0 ? (
                <p className="text-slate-500">No preview images for this document.</p>
              ) : (
                pages.map((page, idx) => (
                  <PageCompareCard key={page.page ?? idx} page={page} index={idx} />
                ))
              )}
            </div>
          )}

          {activeTab === "history" && (
            <InvoiceHistoryPanel refreshKey={historyRefreshKey} />
          )}

          {dashboard && activeTab === "technical" && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={handleDownloadCleanJson}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 shadow-sm transition hover:bg-slate-50"
                >
                  <Download size={16} />
                  Download Cleaned JSON
                </button>
                <button
                  type="button"
                  onClick={handleDownloadRawOcr}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 shadow-sm transition hover:bg-slate-50"
                >
                  <Download size={16} />
                  Download Raw OCR Text
                </button>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-900 p-6 shadow-2xl">
                <h3 className="mb-4 text-xs font-black uppercase tracking-widest text-slate-500">Raw OCR Output</h3>
                <pre className="max-h-[600px] overflow-auto text-xs text-indigo-300 leading-relaxed whitespace-pre-wrap font-mono">
                  {technical?.raw_ocr_text || JSON.stringify(dashboard, null, 2)}
                </pre>
              </div>

              {showCleanJson && (
                <div className="rounded-2xl border border-slate-200 bg-slate-900 p-6 shadow-2xl">
                  <h3 className="mb-4 text-xs font-black uppercase tracking-widest text-slate-500">
                    Cleaned Pipeline JSON
                  </h3>
                  <pre className="max-h-[600px] overflow-auto text-xs text-emerald-300 leading-relaxed whitespace-pre-wrap font-mono">
                    {JSON.stringify(technical?.clean_json || {}, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default AccountantDashboard;
