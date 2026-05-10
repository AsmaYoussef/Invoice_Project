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
} from "lucide-react";

const API_BASE_URL = "http://127.0.0.1:8000";

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

const AccountantDashboard = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
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

  const generalInfo = result?.dashboard?.general_info || {};
  const financialTotals = result?.dashboard?.financial_totals || {};
  const productLines = result?.dashboard?.product_lines || [];
  const pages = result?.visualizer?.pages || [];
  const technical = result?.technical || {};
  const trace = result?.system_trace || [];

  const topConfidence = useMemo(() => {
    const values = Object.values(technical.field_confidence_scores || {}).filter(
      (v) => typeof v === "number"
    );
    if (!values.length) return "N/A";
    const avg = (values.reduce((acc, value) => acc + value, 0) / values.length) * 100;
    return `${avg.toFixed(1)}%`;
  }, [technical.field_confidence_scores]);

  const handleUpload = async () => {
    if (!selectedFile) return;
    setLoading(true);
    setApiError("");

    const formData = new FormData();
    formData.append("file", selectedFile);
    Object.entries(settings).forEach(([key, value]) => {
      formData.append(key, String(value));
    });

    try {
      const response = await axios.post(`${API_BASE_URL}/upload-invoice`, formData);
      setResult(response.data);
      setSyncSuccess(false);
    } catch (error) {
      setApiError(error?.response?.data?.detail || "Upload failed. Check backend logs.");
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    if (!result?.raw_pipeline) return;
    try {
      await axios.post(`${API_BASE_URL}/save-invoice`, result.raw_pipeline);
      setSyncSuccess(true);
    } catch (_error) {
      setApiError("Sync failed while saving to database.");
    }
  };

  const updateSetting = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="min-h-screen bg-slate-100 text-slate-800">
      <div className="grid min-h-screen grid-cols-12">
        <aside className="col-span-12 border-r border-slate-200 bg-white p-5 lg:col-span-3">
          <div className="mb-5 flex items-center gap-3">
            <div className="rounded-lg bg-slate-900 p-2 text-white">
              <Bot size={16} />
            </div>
            <div>
              <h1 className="font-bold">Accountant Console</h1>
              <p className="text-xs text-slate-500">OCR + NLP invoice extraction</p>
            </div>
          </div>

          <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
              <Settings2 size={14} /> Pipeline Settings
            </p>

            <label className="flex items-center justify-between text-sm">
              NLP Enrichment
              <input
                type="checkbox"
                checked={settings.use_nlp}
                onChange={(e) => updateSetting("use_nlp", e.target.checked)}
              />
            </label>
            <label className="flex items-center justify-between text-sm">
              DPI Scaling
              <select
                value={settings.dpi_choice}
                onChange={(e) => updateSetting("dpi_choice", Number(e.target.value))}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
              >
                <option value={150}>150</option>
                <option value={200}>200</option>
                <option value={300}>300</option>
              </select>
            </label>
            <label className="flex items-center justify-between text-sm">
              Fix Rotation
              <input
                type="checkbox"
                checked={settings.use_fix_rotation}
                onChange={(e) => updateSetting("use_fix_rotation", e.target.checked)}
              />
            </label>
            <label className="flex items-center justify-between text-sm">
              Remove Borders
              <input
                type="checkbox"
                checked={settings.use_remove_lines}
                onChange={(e) => updateSetting("use_remove_lines", e.target.checked)}
              />
            </label>
          </div>

          <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
              <Activity size={14} /> System Trace
            </p>
            <div className="max-h-64 space-y-2 overflow-auto pr-1 text-xs">
              {trace.length === 0 && <p className="text-slate-500">No trace yet.</p>}
              {trace.map((step) => (
                <div key={step.step} className="rounded-md border border-slate-200 bg-white p-2">
                  <p className="font-semibold text-slate-700">{step.step}</p>
                  <p className="text-slate-500">{step.detail}</p>
                </div>
              ))}
            </div>
          </div>
        </aside>

        <main className="col-span-12 p-6 lg:col-span-9">
          <div className="mb-6 flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-xl font-bold">Invoice Processing Workspace</h2>
              <p className="text-sm text-slate-500">Split-view validation for accounting operations.</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
                <Upload size={14} />
                <span>{selectedFile?.name || "Choose invoice PDF/image"}</span>
                <input
                  type="file"
                  className="hidden"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                />
              </label>
              <button
                type="button"
                onClick={handleUpload}
                disabled={!selectedFile || loading}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
                {loading ? "Processing..." : "Run Extraction"}
              </button>
              <button
                type="button"
                onClick={handleSync}
                disabled={!result}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                <Database size={14} />
                {syncSuccess ? "Saved ✓" : "Confirm & Sync"}
              </button>
            </div>
          </div>

          {apiError && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{apiError}</div>
          )}

          <div className="mb-5 flex flex-wrap gap-2">
            <TabButton
              active={activeTab === "dashboard"}
              icon={CheckCircle2}
              label={`Dashboard (${topConfidence})`}
              onClick={() => setActiveTab("dashboard")}
            />
            <TabButton
              active={activeTab === "visualizer"}
              icon={Eye}
              label="Visualizer"
              onClick={() => setActiveTab("visualizer")}
            />
            <TabButton
              active={activeTab === "technical"}
              icon={Activity}
              label="Technical"
              onClick={() => setActiveTab("technical")}
            />
          </div>

          {!result ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
              Upload a file and run extraction to populate the dashboard.
            </div>
          ) : null}

          {result && activeTab === "dashboard" && (
            <div className="space-y-5">
              <div className="grid grid-cols-12 gap-4">
                <section className="col-span-12 rounded-xl border border-slate-200 bg-white p-4 xl:col-span-7">
                  <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">General Info</h3>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <InfoField label="Type" value={generalInfo.type} />
                    <InfoField label="Invoice Number" value={generalInfo.invoice_number} />
                    <InfoField label="Invoice Date" value={generalInfo.invoice_date} />
                    <InfoField label="Supplier" value={generalInfo.supplier_name} />
                    <InfoField label="Supplier MF" value={generalInfo.supplier_mf} />
                    <InfoField label="Client MF" value={generalInfo.client_mf} />
                    <InfoField label="Phone" value={generalInfo.telephone} />
                    <InfoField label="Fax" value={generalInfo.fax} />
                    <InfoField label="Email" value={generalInfo.email} />
                    <InfoField label="RC" value={generalInfo.rc} />
                    <div className="md:col-span-2">
                      <InfoField label="Address" value={generalInfo.address} />
                    </div>
                  </div>
                </section>

                <section className="col-span-12 rounded-xl border border-slate-200 bg-white p-4 xl:col-span-5">
                  <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Money Section</h3>
                  <div className="space-y-3">
                    <InfoField label="Total Brut HT" value={financialTotals.total_brut_ht} />
                    <InfoField label="Remise (%)" value={financialTotals.remise_pct} />
                    <InfoField label="Total HT" value={financialTotals.total_ht} />
                    <InfoField label="TVA" value={financialTotals.tva} />
                    <InfoField label="Transport" value={financialTotals.transport} />
                    <InfoField label="Timbre Fiscal" value={financialTotals.timbre_fiscal} />
                    <InfoField label="Total TTC" value={financialTotals.total_ttc} />
                  </div>
                </section>
              </div>

              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
                  Product Lines ({productLines.length})
                </h3>
                <div className="overflow-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                        {["Code", "Designation", "Quantite", "Prix Unitaire", "Montant", "Date Peremption"].map((header) => (
                          <th key={header} className="px-3 py-2">{header}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {productLines.map((line, idx) => (
                        <tr key={`${line.code || "code"}-${idx}`} className="border-b border-slate-100">
                          <td className="px-3 py-2">{line.code || line.code_pct || line.code_article || "—"}</td>
                          <td className="px-3 py-2">{line.designation || "—"}</td>
                          <td className="px-3 py-2">{line.quantite ?? "—"}</td>
                          <td className="px-3 py-2">{line.prix_unitaire ?? "—"}</td>
                          <td className="px-3 py-2">{line.montant ?? "—"}</td>
                          <td className="px-3 py-2">{line.date_peremption || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          )}

          {result && activeTab === "visualizer" && (
            <section className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Original PDF vs Cleaned OCR Page
              </h3>
              <div className="space-y-5">
                {pages.map((page) => (
                  <div key={page.page_number} className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Original - Page {page.page_number}
                      </p>
                      {page.original_image_b64 ? (
                        <img src={page.original_image_b64} alt={`Original page ${page.page_number}`} className="w-full rounded border border-slate-200" />
                      ) : (
                        <p className="text-sm text-slate-500">No image available.</p>
                      )}
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Cleaned - Page {page.page_number}
                      </p>
                      {page.cleaned_image_b64 ? (
                        <img src={page.cleaned_image_b64} alt={`Cleaned page ${page.page_number}`} className="w-full rounded border border-slate-200" />
                      ) : (
                        <p className="text-sm text-slate-500">No cleaned image available.</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {result && activeTab === "technical" && (
            <div className="grid grid-cols-12 gap-4">
              <section className="col-span-12 rounded-xl border border-slate-200 bg-white p-4 xl:col-span-7">
                <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Raw OCR String</h3>
                <pre className="max-h-[500px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-100 whitespace-pre-wrap">
                  {technical.raw_ocr_text || "No OCR text."}
                </pre>
              </section>

              <section className="col-span-12 space-y-4 xl:col-span-5">
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                    Confidence Scores
                  </h3>
                  <div className="max-h-64 space-y-2 overflow-auto text-sm">
                    {Object.entries(technical.field_confidence_scores || {}).map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2">
                        <span className="text-slate-600">{key}</span>
                        <span className="font-semibold text-slate-800">{(value * 100).toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">NLP Trace Console</h3>
                  <div className="max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-xs text-emerald-300">
                    {trace.map((step, idx) => (
                      <p key={`${step.step}-${idx}`}>
                        [{String(idx + 1).padStart(2, "0")}] {step.step} :: {step.detail}
                      </p>
                    ))}
                    {trace.length === 0 && <p>[00] Waiting for extraction trace...</p>}
                  </div>
                </div>
              </section>
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default AccountantDashboard;