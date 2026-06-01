import React, { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  FileText,
  Loader2,
  LogOut,
  Plus,
  RefreshCw,
  ScrollText,
  Settings,
  Trash2,
  Users,
  X,
} from "lucide-react";
import InvoScanLogo from "./InvoScanLogo";
import ThemeToggle from "./ThemeToggle";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const API_BASE = "http://127.0.0.1:8000/api/admin";

const NAV_ITEMS = [
  { id: "users", label: "User Management", icon: Users },
  { id: "performance", label: "Performance", icon: BarChart3 },
  { id: "logs", label: "System Logs", icon: ScrollText },
  { id: "config", label: "Configuration", icon: Settings },
];

const PIE_COLORS = {
  VALID: "#10b981",
  LOW_CONFIDENCE: "#f59e0b",
  PRICE_MISMATCH: "#ef4444",
  UNKNOWN_PRODUCT: "#94a3b8",
};

function formatApiError(error, fallback) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return error?.message || fallback;
}

function logLevelClass(level) {
  const lv = String(level || "INFO").toUpperCase();
  if (lv === "ERROR") return "text-red-400 font-bold animate-pulse";
  if (lv === "WARN") return "text-amber-400";
  return "text-emerald-400";
}

const StatusBadge = ({ status }) => {
  const active = status === "ACTIVE";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${
        active ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"
      }`}
    >
      {active ? "Active" : "Suspended"}
    </span>
  );
};

const Modal = ({ open, title, onClose, children }) => {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-bold text-slate-900">{title}</h3>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
};

const UserManagementTab = ({ apiError, setApiError }) => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [deleteUser, setDeleteUser] = useState(null);
  const [form, setForm] = useState({ username: "", email: "", password: "", role: "ACCOUNTANT" });
  const [editForm, setEditForm] = useState({ email: "", role: "ACCOUNTANT", status: "ACTIVE", password: "" });
  const [saving, setSaving] = useState(false);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setApiError("");
    try {
      const res = await axios.get(`${API_BASE}/users`);
      setUsers(res.data.users || []);
    } catch (err) {
      setApiError(formatApiError(err, "Failed to load users."));
    } finally {
      setLoading(false);
    }
  }, [setApiError]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const handleAdd = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await axios.post(`${API_BASE}/users`, form);
      setAddOpen(false);
      setForm({ username: "", email: "", password: "", role: "ACCOUNTANT" });
      await loadUsers();
    } catch (err) {
      setApiError(formatApiError(err, "Failed to create user."));
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async (e) => {
    e.preventDefault();
    if (!editUser) return;
    setSaving(true);
    try {
      const payload = {
        email: editForm.email,
        role: editForm.role,
        status: editForm.status,
      };
      if (editForm.password) payload.password = editForm.password;
      await axios.put(`${API_BASE}/users/${editUser.id}`, payload);
      setEditUser(null);
      await loadUsers();
    } catch (err) {
      setApiError(formatApiError(err, "Failed to update user."));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (hard = false) => {
    if (!deleteUser) return;
    setSaving(true);
    try {
      await axios.delete(`${API_BASE}/users/${deleteUser.id}`, { params: { hard } });
      setDeleteUser(null);
      await loadUsers();
    } catch (err) {
      setApiError(formatApiError(err, "Failed to deactivate user."));
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (user) => {
    setEditUser(user);
    setEditForm({
      email: user.email,
      role: user.role,
      status: user.status,
      password: "",
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-extrabold text-slate-900">User Management</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={loadUsers}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-slate-50"
          >
            <RefreshCw size={16} /> Refresh
          </button>
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-700"
          >
            <Plus size={16} /> Add User
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex items-center justify-center p-12 text-slate-500">
            <Loader2 className="animate-spin" size={24} />
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs font-black uppercase tracking-widest text-slate-400">
                <th className="p-4">ID</th>
                <th className="p-4">Username</th>
                <th className="p-4">Email</th>
                <th className="p-4">Role</th>
                <th className="p-4">Status</th>
                <th className="p-4">Created</th>
                <th className="p-4">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-slate-50">
                  <td className="p-4 font-mono text-slate-600">{user.id}</td>
                  <td className="p-4 font-semibold">{user.username}</td>
                  <td className="p-4">{user.email}</td>
                  <td className="p-4">
                    <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-700">
                      {user.role}
                    </span>
                  </td>
                  <td className="p-4">
                    <StatusBadge status={user.status} />
                  </td>
                  <td className="p-4 text-slate-500">{user.created_at?.slice(0, 10) || "—"}</td>
                  <td className="p-4">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => openEdit(user)}
                        className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-semibold hover:bg-slate-100"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteUser(user)}
                        className="rounded-lg border border-red-200 px-3 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
                      >
                        Deactivate
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!users.length && (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-slate-500">
                    No users found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      <Modal open={addOpen} title="Add User" onClose={() => setAddOpen(false)}>
        <form onSubmit={handleAdd} className="space-y-3">
          <input
            required
            placeholder="Username"
            value={form.username}
            onChange={(e) => setForm((p) => ({ ...p, username: e.target.value }))}
            className="w-full rounded-xl border border-slate-300 px-3 py-2"
          />
          <input
            required
            type="email"
            placeholder="Email"
            value={form.email}
            onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
            className="w-full rounded-xl border border-slate-300 px-3 py-2"
          />
          <input
            required
            type="password"
            placeholder="Password (min 6 chars)"
            value={form.password}
            onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))}
            className="w-full rounded-xl border border-slate-300 px-3 py-2"
          />
          <select
            value={form.role}
            onChange={(e) => setForm((p) => ({ ...p, role: e.target.value }))}
            className="w-full rounded-xl border border-slate-300 px-3 py-2"
          >
            <option value="ACCOUNTANT">Accountant</option>
            <option value="ADMINISTRATOR">Administrator</option>
          </select>
          <button
            type="submit"
            disabled={saving}
            className="w-full rounded-xl bg-indigo-600 py-2.5 font-bold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "Creating..." : "Create User"}
          </button>
        </form>
      </Modal>

      <Modal open={!!editUser} title={`Edit User — ${editUser?.username || ""}`} onClose={() => setEditUser(null)}>
        <form onSubmit={handleEdit} className="space-y-3">
          <input
            required
            type="email"
            value={editForm.email}
            onChange={(e) => setEditForm((p) => ({ ...p, email: e.target.value }))}
            className="w-full rounded-xl border border-slate-300 px-3 py-2"
          />
          <select
            value={editForm.role}
            onChange={(e) => setEditForm((p) => ({ ...p, role: e.target.value }))}
            className="w-full rounded-xl border border-slate-300 px-3 py-2"
          >
            <option value="ACCOUNTANT">Accountant</option>
            <option value="ADMINISTRATOR">Administrator</option>
          </select>
          <select
            value={editForm.status}
            onChange={(e) => setEditForm((p) => ({ ...p, status: e.target.value }))}
            className="w-full rounded-xl border border-slate-300 px-3 py-2"
          >
            <option value="ACTIVE">Active</option>
            <option value="SUSPENDED">Suspended</option>
          </select>
          <input
            type="password"
            placeholder="New password (optional)"
            value={editForm.password}
            onChange={(e) => setEditForm((p) => ({ ...p, password: e.target.value }))}
            className="w-full rounded-xl border border-slate-300 px-3 py-2"
          />
          <button
            type="submit"
            disabled={saving}
            className="w-full rounded-xl bg-indigo-600 py-2.5 font-bold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </form>
      </Modal>

      <Modal open={!!deleteUser} title="Confirm Deactivation" onClose={() => setDeleteUser(null)}>
        <p className="mb-4 text-sm text-slate-600">
          Suspend <strong>{deleteUser?.username}</strong> or permanently delete this account?
        </p>
        <div className="flex flex-col gap-2">
          <button
            type="button"
            disabled={saving}
            onClick={() => handleDelete(false)}
            className="rounded-xl bg-amber-500 py-2.5 font-bold text-white hover:bg-amber-600 disabled:opacity-50"
          >
            Suspend Account
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => handleDelete(true)}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-red-300 py-2.5 font-bold text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            <Trash2 size={16} /> Permanently Delete
          </button>
        </div>
      </Modal>
    </div>
  );
};

const PerformanceTab = ({ setApiError }) => {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadMetrics = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/metrics`);
      setMetrics(res.data);
      setApiError("");
    } catch (err) {
      setApiError(formatApiError(err, "Failed to load metrics."));
    } finally {
      setLoading(false);
    }
  }, [setApiError]);

  useEffect(() => {
    loadMetrics();
    const id = setInterval(loadMetrics, 30000);
    return () => clearInterval(id);
  }, [loadMetrics]);

  const pieData = useMemo(() => {
    const bd = metrics?.validation_breakdown || {};
    return Object.entries(bd)
      .filter(([, v]) => v > 0)
      .map(([name, value]) => ({ name, value }));
  }, [metrics]);

  if (loading && !metrics) {
    return (
      <div className="flex items-center justify-center p-20 text-slate-500">
        <Loader2 className="animate-spin" size={28} />
      </div>
    );
  }

  const kpis = [
    { label: "Total Invoice Volume", value: metrics?.total_invoices ?? 0, suffix: " docs" },
    {
      label: "Mean Processing Speed",
      value: metrics?.avg_seconds_per_page ?? 0,
      suffix: "s / Page",
    },
    { label: "ERP Match Rate", value: metrics?.valid_rate_pct ?? 0, suffix: "%" },
    { label: "Active Anomaly Alerts", value: metrics?.unresolved_alerts ?? 0, suffix: "" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-extrabold text-slate-900">Performance Monitoring</h2>
        <button
          type="button"
          onClick={loadMetrics}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-slate-50"
        >
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {kpis.map((kpi) => (
          <div key={kpi.label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-wider text-slate-400">{kpi.label}</p>
            <p className="mt-2 text-3xl font-black text-indigo-600">
              {kpi.value}
              <span className="text-base font-semibold text-slate-500">{kpi.suffix}</span>
            </p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-4 text-sm font-bold uppercase tracking-widest text-slate-400">
            Volume Velocity (daily)
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={metrics?.volume_by_day || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Area type="monotone" dataKey="count" stroke="#4f46e5" fill="#818cf8" fillOpacity={0.35} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-4 text-sm font-bold uppercase tracking-widest text-slate-400">
            Validation Breakdown
          </h3>
          {pieData.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label>
                  {pieData.map((entry) => (
                    <Cell key={entry.name} fill={PIE_COLORS[entry.name] || "#64748b"} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-16 text-center text-sm text-slate-500">No validation data yet. Run OCR uploads first.</p>
          )}
        </div>
      </div>
    </div>
  );
};

const LogAuditorTab = ({ setApiError }) => {
  const [logs, setLogs] = useState([]);
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("all");
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/logs`, {
        params: { search, severity, limit: 300 },
      });
      setLogs(res.data.logs || []);
      setApiError("");
    } catch (err) {
      setApiError(formatApiError(err, "Failed to load logs."));
    } finally {
      setLoading(false);
    }
  }, [search, severity, setApiError]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-extrabold text-slate-900">System Log Auditor</h2>
        <button
          type="button"
          onClick={loadLogs}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-slate-50"
        >
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl">
        <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-900/95 p-4">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search logs..."
            className="min-w-[200px] flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500"
          />
          <div className="flex gap-1">
            {["all", "error", "warn"].map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSeverity(s)}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold uppercase ${
                  severity === s
                    ? "bg-indigo-600 text-white"
                    : "border border-slate-700 text-slate-400 hover:bg-slate-800"
                }`}
              >
                {s === "all" ? "All" : s === "error" ? "Only Errors" : "Only Warnings"}
              </button>
            ))}
          </div>
        </div>

        <div className="max-h-[65vh] overflow-auto p-4 font-mono text-xs">
          {loading ? (
            <div className="flex justify-center py-12 text-slate-500">
              <Loader2 className="animate-spin" size={22} />
            </div>
          ) : logs.length ? (
            logs.map((entry, idx) => (
              <button
                key={`${entry.timestamp}-${idx}`}
                type="button"
                onClick={() => setSelected(entry)}
                className="mb-1 block w-full rounded px-2 py-1 text-left hover:bg-slate-900"
              >
                <span className="text-slate-500">[{entry.timestamp?.slice(11, 19) || "??:??:??"}]</span>{" "}
                <span className={logLevelClass(entry.level)}>[{entry.level}]</span>{" "}
                <span className="text-slate-300">{entry.message}</span>
              </button>
            ))
          ) : (
            <p className="py-12 text-center text-slate-500">No log entries match your filters.</p>
          )}
        </div>
      </div>

      {selected && (
        <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md border-l border-slate-200 bg-white p-6 shadow-2xl">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-bold text-slate-900">Log Details</h3>
            <button type="button" onClick={() => setSelected(null)} className="rounded-lg p-1 hover:bg-slate-100">
              <X size={18} />
            </button>
          </div>
          <div className="space-y-3 text-sm">
            <p>
              <span className="font-semibold text-slate-500">Level:</span>{" "}
              <span className={logLevelClass(selected.level)}>{selected.level}</span>
            </p>
            <p>
              <span className="font-semibold text-slate-500">Time:</span> {selected.timestamp}
            </p>
            <p>
              <span className="font-semibold text-slate-500">Message:</span> {selected.message}
            </p>
            {selected.context?.stack_trace && (
              <div>
                <p className="mb-1 font-semibold text-slate-500">Stack Trace</p>
                <pre className="max-h-40 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-red-300">
                  {selected.context.stack_trace}
                </pre>
              </div>
            )}
            <div>
              <p className="mb-1 font-semibold text-slate-500">Context / Raw JSON</p>
              <pre className="max-h-80 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-emerald-300">
                {JSON.stringify(selected.context || {}, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const ConfigTab = ({ setApiError }) => {
  const [config, setConfig] = useState(null);
  const [saving, setSaving] = useState(false);
  const [emailsText, setEmailsText] = useState("");
  const [webhooksText, setWebhooksText] = useState("");

  const loadConfig = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/config`);
      setConfig(res.data);
      setEmailsText((res.data.notifications?.emails || []).join(", "));
      setWebhooksText((res.data.notifications?.webhooks || []).join("\n"));
      setApiError("");
    } catch (err) {
      setApiError(formatApiError(err, "Failed to load config."));
    }
  }, [setApiError]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSave = async (e) => {
    e.preventDefault();
    if (!config) return;
    setSaving(true);
    try {
      const payload = {
        ...config,
        notifications: {
          emails: emailsText
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          webhooks: webhooksText
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean),
        },
      };
      const res = await axios.post(`${API_BASE}/config`, payload);
      setConfig(res.data);
      setApiError("");
    } catch (err) {
      setApiError(formatApiError(err, "Failed to save config."));
    } finally {
      setSaving(false);
    }
  };

  if (!config) {
    return (
      <div className="flex items-center justify-center p-20 text-slate-500">
        <Loader2 className="animate-spin" size={28} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-extrabold text-slate-900">System Configuration & Alerts</h2>
      <form onSubmit={handleSave} className="space-y-6">
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold uppercase tracking-widest text-slate-400">Reconciliation</h3>
          <label className="block text-sm font-semibold text-slate-700">
            Fuzzy Match Threshold: {(config.confidence_threshold * 100).toFixed(0)}%
          </label>
          <input
            type="range"
            min="0.5"
            max="0.99"
            step="0.01"
            value={config.confidence_threshold}
            onChange={(e) =>
              setConfig((p) => ({ ...p, confidence_threshold: parseFloat(e.target.value) }))
            }
            className="mt-2 w-full accent-indigo-600"
          />
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold uppercase tracking-widest text-slate-400">OCR Defaults</h3>
          <label className="mb-1 block text-sm font-semibold text-slate-700">Default Processing DPI</label>
          <select
            value={config.default_dpi}
            onChange={(e) => setConfig((p) => ({ ...p, default_dpi: Number(e.target.value) }))}
            className="w-full max-w-xs rounded-xl border border-slate-300 px-3 py-2"
          >
            {[150, 200, 300].map((dpi) => (
              <option key={dpi} value={dpi}>
                {dpi} DPI
              </option>
            ))}
          </select>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold uppercase tracking-widest text-slate-400">Alert Rules</h3>
          <label className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <input
              type="checkbox"
              checked={config.alert_rules?.enabled ?? true}
              onChange={(e) =>
                setConfig((p) => ({
                  ...p,
                  alert_rules: { ...p.alert_rules, enabled: e.target.checked },
                }))
              }
              className="h-4 w-4 rounded accent-indigo-600"
            />
            Enable price mismatch alerts
          </label>
          <label className="mt-3 block text-sm text-slate-600">
            Trigger alert when mismatch exceeds (% of total HT)
          </label>
          <input
            type="number"
            min="1"
            max="100"
            value={config.alert_rules?.price_mismatch_pct_threshold ?? 15}
            onChange={(e) =>
              setConfig((p) => ({
                ...p,
                alert_rules: {
                  ...p.alert_rules,
                  price_mismatch_pct_threshold: Number(e.target.value),
                },
              }))
            }
            className="mt-1 w-full max-w-xs rounded-xl border border-slate-300 px-3 py-2"
          />
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold uppercase tracking-widest text-slate-400">
            Notification Routing
          </h3>
          <label className="block text-sm font-semibold text-slate-700">Alert Emails (comma-separated)</label>
          <input
            value={emailsText}
            onChange={(e) => setEmailsText(e.target.value)}
            placeholder="ops@diva.local, finance@motion.div"
            className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2"
          />
          <label className="mt-4 block text-sm font-semibold text-slate-700">Webhook URLs (one per line)</label>
          <textarea
            value={webhooksText}
            onChange={(e) => setWebhooksText(e.target.value)}
            rows={3}
            placeholder="https://hooks.example.com/alert"
            className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 font-mono text-sm"
          />
        </section>

        <button
          type="submit"
          disabled={saving}
          className="rounded-xl bg-emerald-600 px-8 py-3 font-bold text-white shadow-lg hover:bg-emerald-700 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Configuration"}
        </button>
      </form>
    </div>
  );
};

const AdminDashboard = () => {
  const [activeTab, setActiveTab] = useState("users");
  const [apiError, setApiError] = useState("");

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-800 dark:bg-slate-950 dark:text-slate-100">
      <div className="grid min-h-screen grid-cols-12">
        <aside className="col-span-12 border-r border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900 lg:col-span-3 lg:min-h-screen">
          <div className="mb-8 flex items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-indigo-600 p-2 text-white">
              <InvoScanLogo size={20} />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight">InvoScan Admin</h1>
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">System Supervision v1.0</p>
            </div>
          </div>
          <ThemeToggle />
          </div>

          <nav className="space-y-1">
            {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setActiveTab(id)}
                className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-semibold transition active:scale-[0.98] ${
                  activeTab === id
                    ? "bg-indigo-600 text-white shadow-md"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon size={18} />
                {label}
              </button>
            ))}
          </nav>

          <div className="mt-8 space-y-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-500">
              <p className="font-medium text-slate-600">
                Signed in as <span className="font-bold text-indigo-600">{localStorage.getItem("username") || "admin"}</span>
              </p>
            </div>
            <button
              type="button"
              onClick={() => { localStorage.clear(); window.location.href = "/login"; }}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-semibold text-red-600 transition hover:bg-red-100 active:scale-[0.98]"
            >
              <LogOut size={16} />
              Sign Out
            </button>
          </div>
        </aside>

        <main className="col-span-12 p-6 lg:col-span-9 lg:p-8">
          {apiError && (
            <div className="mb-6 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <AlertTriangle size={18} />
              <p className="font-semibold">{apiError}</p>
            </div>
          )}

          {activeTab === "users" && <UserManagementTab apiError={apiError} setApiError={setApiError} />}
          {activeTab === "performance" && <PerformanceTab setApiError={setApiError} />}
          {activeTab === "logs" && <LogAuditorTab setApiError={setApiError} />}
          {activeTab === "config" && <ConfigTab setApiError={setApiError} />}
        </main>
      </div>
    </div>
  );
};

export default AdminDashboard;
