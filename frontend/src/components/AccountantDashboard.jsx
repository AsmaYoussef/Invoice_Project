import React, { useMemo, useState } from "react";
import axios from "axios";
import {
  Activity,
  Bot,
  CheckCircle2,
  Database,
  Eye,
  FileText,
  Loader2,
  Settings2,
  Upload,
  AlertCircle,
} from "lucide-react";

const API_BASE_URL = "http://127.0.0.1:8000";

// --- UI COMPONENTS ---

const TabButton = ({ active, icon: Icon, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition ${
      active
        ? "bg-slate-900 text-white shadow"
        : "bg-white text-slate-600 hover:bg-slate-100 border border-slate-200"
    }`}
  >
    <Icon size={16} />
    {label}
  </button>
);

const InfoField = ({ label, value }) => (
  <div className="space-y-1">
    <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
    <p className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 min-h-9">
      {String(value ?? "") || "—"}
    </p>
  </div>
);

const ValidationBadge = ({ status }) => {
  switch (status) {
    case "MATCH":
      return <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">✅ MATCH</span>;
    case "MISMATCH":
      return <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">❌ MISMATCH</span>;
    case "NOT_IN_ERP":
      return <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">⚠️ NEW ITEM</span>;
    default:
      return <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">UNCHECKED</span>;
  }
};

// --- MAIN DASHBOARD ---

const AccountantDashboard = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncSuccess, setSyncSuccess] = useState(false);
  const [apiError, setApiError] = useState("");

  const [settings, setSettings] = useState({
    use_nlp: true,
    dpi_choice: 200,
    use_fix_rotation: true,
    use_erase_color: true,
    use_remove_lines: true,
    use_keep_mask: true,
  });

  // Data Selectors
  const generalInfo = result?.dashboard?.general_info || {};
  const financialTotals = result?.dashboard?.financial_totals || {};
  const productLines = result?.dashboard?.product_lines || [];
  const pages = result?.visualizer?.pages || [];
  const technical = result?.technical || {};
  const trace = result?.system_trace || [];

  // Confidence Calculation
  const topConfidence = useMemo(() => {
    const scores = technical.field_confidence_scores || {};
    const values = Object.values(scores).filter((v) => typeof v === "number");
    if (!values.length) return "0%";
    const avg = (values.reduce((acc, v) => acc + v, 0) / values.length) * 100;
    return `${avg.toFixed(0)}%`;
  }, [technical.field_confidence_scores]);

  const handleUpload = async () => {
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
      setResult(response.data);
    } catch (error) {
      setApiError(error?.response?.data?.detail || "Connection failed. Is the API running?");
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    if (!result) return;
    setSyncLoading(true);
    try {
      // Send the entire dashboard payload to be saved in MySQL
      await axios.post(`${API_BASE_URL}/save-invoice`, result.dashboard);
      setSyncSuccess(true);
    } catch (error) {
      setApiError("Database Sync failed. Check if MySQL container is active.");
    } finally {
      setSyncLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100 text-slate-800 font-sans">
      <div className="grid min-h-screen grid-cols-12">
        {/* SIDEBAR */}
        <aside className="col-span-12 border-r border-slate-200 bg-white p-5 lg:col-span-3">
          <div className="mb-8 flex items-center gap-3">
            <div className="rounded-lg bg-indigo-600 p-2 text-white">
              <Bot size={20} />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight">Diva Software</h1>
              <p className="text-xs text-slate-500 font-medium">Smart OCR Engine v2.0</p>
            </div>
          </div>

          <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-600">
              <Settings2 size={14} /> Pipeline Config
            </p>
            {Object.keys(settings).map((key) => (
              <label key={key} className="flex items-center justify-between text-sm cursor-pointer capitalize">
                {key.replace(/_/g, " ")}
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  checked={settings[key]}
                  onChange={(e) => setSettings({ ...settings, [key]: e.target.checked })}
                />
              </label>
            ))}
          </div>

          <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-600">
              <Activity size={14} /> Extraction Logs
            </p>
            <div className="max-h-64 space-y-2 overflow-auto pr-1">
              {trace.map((step, i) => (
                <div key={i} className="rounded-md border border-slate-200 bg-white p-2 text-[11px]">
                  <p className="font-bold text-slate-700">{step.step}</p>
                  <p className="text-slate-500 truncate">{step.detail}</p>
                </div>
              ))}
              {!trace.length && <p className="text-xs text-slate-400 italic">No activity yet...</p>}
            </div>
          </div>
        </aside>

        {/* MAIN CONTENT */}
        <main className="col-span-12 p-8 lg:col-span-9">
          <header className="mb-8 flex flex-col gap-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-2xl font-extrabold tracking-tight text-slate-900">Invoice Reconciliation</h2>
              <p className="text-slate-500">Extract, validate against ERP, and sync to database.</p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold transition hover:bg-slate-50">
                <Upload size={16} />
                <span>{selectedFile?.name || "Select Document"}</span>
                <input type="file" className="hidden" onChange={(e) => setSelectedFile(e.target.files?.[0] || null)} />
              </label>

              <button
                onClick={handleUpload}
                disabled={!selectedFile || loading}
                className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-bold text-white shadow-lg transition hover:bg-indigo-700 disabled:opacity-50"
              >
                {loading ? <Loader2 size={18} className="animate-spin" /> : <FileText size={18} />}
                {loading ? "Analyzing..." : "Analyze"}
              </button>

              <button
                onClick={handleSync}
                disabled={!result || syncLoading}
                className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-2.5 text-sm font-bold text-white shadow-lg transition hover:bg-emerald-700 disabled:opacity-50"
              >
                {syncLoading ? <Loader2 size={18} className="animate-spin" /> : <Database size={18} />}
                {syncSuccess ? "Synced to DB ✓" : "Confirm & Sync"}
              </button>
            </div>
          </header>

          {apiError && (
            <div className="mb-6 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 shadow-sm">
              <AlertCircle size={18} />
              <p className="font-semibold">{apiError}</p>
            </div>
          )}

          <div className="mb-6 flex gap-2">
            <TabButton active={activeTab === "dashboard"} icon={CheckCircle2} label={`Review (${topConfidence})`} onClick={() => setActiveTab("dashboard")} />
            <TabButton active={activeTab === "visualizer"} icon={Eye} label="PDF Visualizer" onClick={() => setActiveTab("visualizer")} />
            <TabButton active={activeTab === "technical"} icon={Activity} label="Raw Data" onClick={() => setActiveTab("technical")} />
          </div>

          {!result && !loading && (
            <div className="flex min-h-[400px] flex-col items-center justify-center rounded-3xl border-2 border-dashed border-slate-300 bg-white p-12 text-center shadow-inner">
              <div className="mb-4 rounded-full bg-slate-100 p-4 text-slate-400">
                <Upload size={48} />
              </div>
              <h3 className="text-lg font-bold text-slate-800">Ready to start</h3>
              <p className="max-w-xs text-slate-500">Upload a supplier invoice to see the AI and ERP reconciliation in action.</p>
            </div>
          )}

          {/* DASHBOARD TAB */}
          {result && activeTab === "dashboard" && (
            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 space-y-6">
              <div className="grid grid-cols-12 gap-6">
                <section className="col-span-12 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm xl:col-span-8">
                  <h3 className="mb-6 text-sm font-bold uppercase tracking-widest text-slate-400">Header Information</h3>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <InfoField label="Invoice #" value={generalInfo.invoice_number} />
                    <InfoField label="Date" value={generalInfo.invoice_date} />
                    <InfoField label="Supplier Name" value={generalInfo.supplier_name} />
                    <InfoField label="Supplier MF" value={generalInfo.supplier_mf} />
                    <div className="md:col-span-2">
                      <InfoField label="Physical Address" value={generalInfo.address} />
                    </div>
                  </div>
                </section>

                <section className="col-span-12 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm xl:col-span-4">
                  <h3 className="mb-6 text-sm font-bold uppercase tracking-widest text-slate-400">Financial Summary</h3>
                  <div className="space-y-4">
                    <div className="flex justify-between border-b border-slate-100 pb-2">
                      <span className="text-sm text-slate-500">Total HT</span>
                      <span className="font-bold text-slate-900">{financialTotals.total_ht} TND</span>
                    </div>
                    <div className="flex justify-between border-b border-slate-100 pb-2">
                      <span className="text-sm text-slate-500">TVA Amount</span>
                      <span className="font-bold text-slate-900">{financialTotals.tva} TND</span>
                    </div>
                    <div className="flex justify-between pt-2">
                      <span className="text-base font-bold text-slate-900">Total TTC</span>
                      <span className="text-xl font-black text-indigo-600">{financialTotals.total_ttc} TND</span>
                    </div>
                  </div>
                </section>
              </div>

              <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h3 className="mb-6 text-sm font-bold uppercase tracking-widest text-slate-400">Line Item Validation</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b-2 border-slate-100 text-left text-xs font-black uppercase tracking-widest text-slate-400">
                        <th className="pb-4">Status</th>
                        <th className="pb-4">Product Code</th>
                        <th className="pb-4">Designation</th>
                        <th className="pb-4">Qty</th>
                        <th className="pb-4">OCR Price</th>
                        <th className="pb-4">ERP Truth</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {productLines.map((line, idx) => (
                        <tr key={idx} className="group hover:bg-slate-50">
                          <td className="py-4"><ValidationBadge status={line.validation_status} /></td>
                          <td className="py-4 font-mono font-bold text-slate-900">{line.code || "—"}</td>
                          <td className="py-4 font-medium text-slate-700">{line.designation || line.erp_name || "—"}</td>
                          <td className="py-4 text-slate-500">{line.quantite || "0"}</td>
                          <td className="py-4 font-bold text-slate-900">{line.price_unit || "0.00"}</td>
                          <td className="py-4 font-black text-indigo-600">{line.erp_price ? `${line.erp_price}` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          )}

          {/* VISUALIZER TAB */}
          {result && activeTab === "visualizer" && (
            <div className="space-y-6">
              {pages.map((page, idx) => (
                <div key={idx} className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                  <div className="rounded-2xl border border-slate-200 bg-white p-4">
                    <p className="mb-4 text-xs font-black uppercase tracking-widest text-slate-400">Original Scan</p>
                    <img src={page.original_image_b64} alt="Original" className="w-full rounded-xl shadow-md" />
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white p-4">
                    <p className="mb-4 text-xs font-black uppercase tracking-widest text-slate-400">Computer Vision (Cleaned)</p>
                    {page.cleaned_image_b64 ? (
                      <img src={page.cleaned_image_b64} alt="Cleaned" className="w-full rounded-xl shadow-md border-2 border-indigo-100" />
                    ) : (
                      <div className="flex h-64 items-center justify-center rounded-xl bg-slate-50 text-slate-400 italic">Preprocessing skipped for this page.</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* TECHNICAL TAB */}
          {result && activeTab === "technical" && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
              <div className="lg:col-span-8 rounded-2xl border border-slate-200 bg-slate-900 p-6 shadow-2xl">
                <h3 className="mb-4 text-xs font-black uppercase tracking-widest text-slate-500">Raw OCR Output</h3>
                <pre className="max-h-[600px] overflow-auto text-xs text-indigo-300 leading-relaxed whitespace-pre-wrap font-mono">
                  {technical.raw_ocr_text || "No raw text extracted."}
                </pre>
              </div>
              <div className="lg:col-span-4 space-y-6">
                <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                  <h3 className="mb-4 text-xs font-black uppercase tracking-widest text-slate-400">AI Confidence Scores</h3>
                  <div className="space-y-3">
                    {Object.entries(technical.field_confidence_scores || {}).map(([key, val]) => (
                      <div key={key}>
                        <div className="flex justify-between text-xs font-bold text-slate-600 mb-1 capitalize">
                          <span>{key}</span>
                          <span>{(val * 100).toFixed(1)}%</span>
                        </div>
                        <div className="h-1.5 w-full rounded-full bg-slate-100">
                          <div className="h-full rounded-full bg-indigo-500 transition-all duration-1000" style={{ width: `${val * 100}%` }}></div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default AccountantDashboard;