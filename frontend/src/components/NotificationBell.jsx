import React, { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { Bell, Check, Loader2 } from "lucide-react";

const API_BASE_URL = "http://127.0.0.1:8000";
const POLL_MS = 30_000;

function formatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef(null);

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE_URL}/api/accountant/notifications`, {
        params: { limit: 30 },
      });
      setNotifications(res.data.notifications || []);
      setUnreadCount(res.data.unread_count ?? 0);
    } catch {
      /* silent when offline or unauthorized */
    }
  }, []);

  useEffect(() => {
    fetchNotifications();
    const id = setInterval(fetchNotifications, POLL_MS);
    return () => clearInterval(id);
  }, [fetchNotifications]);

  useEffect(() => {
    const onDocClick = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const markRead = async (id) => {
    try {
      await axios.post(`${API_BASE_URL}/api/accountant/notifications/${id}/read`);
      await fetchNotifications();
    } catch {
      /* ignore */
    }
  };

  const markAllRead = async () => {
    setLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/api/accountant/notifications/read-all`);
      await fetchNotifications();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          if (!open) fetchNotifications();
        }}
        className="relative inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white p-2.5 text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        aria-label="Notifications"
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-[min(100vw-2rem,380px)] rounded-2xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
            <h4 className="text-sm font-bold text-slate-800 dark:text-slate-100">Notifications</h4>
            <button
              type="button"
              onClick={markAllRead}
              disabled={loading || unreadCount === 0}
              className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-500 disabled:opacity-40 dark:text-indigo-400"
            >
              {loading ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Mark all read
            </button>
          </div>
          <ul className="max-h-80 overflow-y-auto">
            {notifications.length === 0 ? (
              <li className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
                No notifications yet
              </li>
            ) : (
              notifications.map((n) => (
                <li
                  key={n.id}
                  className={`border-b border-slate-100 px-4 py-3 last:border-0 dark:border-slate-800 ${
                    !n.is_read ? "bg-indigo-50/50 dark:bg-indigo-950/30" : ""
                  }`}
                >
                  <button
                    type="button"
                    className="w-full text-left"
                    onClick={() => !n.is_read && markRead(n.id)}
                  >
                    <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                      {n.title}
                    </p>
                    {n.message && (
                      <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">{n.message}</p>
                    )}
                    <p className="mt-1 text-[10px] text-slate-400 dark:text-slate-500">
                      {formatTime(n.created_at)}
                      {n.invoice_ref ? ` · ${n.invoice_ref}` : ""}
                    </p>
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
