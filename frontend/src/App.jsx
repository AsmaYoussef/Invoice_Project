import { BrowserRouter as Router, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { useEffect, useCallback } from "react";
import axios from "axios";
import "./App.css";
import AccountantDashboard from "./components/AccountantDashboard";
import AdminDashboard from "./components/AdminDashboard";
import Login from "./components/Login";

// ---------------------------------------------------------------------------
// Global Axios interceptor -- attaches JWT token to every outgoing request
// and handles 401/403 responses by clearing auth state and redirecting.
// ---------------------------------------------------------------------------
axios.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let authErrorRedirectScheduled = false;

axios.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    if ((status === 401 || status === 403) && !authErrorRedirectScheduled) {
      const isLoginRequest = error?.config?.url?.includes("/api/auth/login");
      if (!isLoginRequest) {
        authErrorRedirectScheduled = true;
        localStorage.clear();
        window.location.href = "/login?expired=1";
      }
    }
    return Promise.reject(error);
  }
);

// ---------------------------------------------------------------------------
// Route guard components
// ---------------------------------------------------------------------------

function ProtectedRoute({ children, allowedRole }) {
  const token = localStorage.getItem("access_token");
  const role = localStorage.getItem("role");

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRole && role !== allowedRole) {
    return <AccessDenied userRole={role} />;
  }

  return children;
}

function AccessDenied({ userRole }) {
  const navigate = useNavigate();
  const homePath = userRole === "ADMINISTRATOR" ? "/admin" : "/accountant";

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-md rounded-2xl border border-red-200 bg-white p-10 text-center shadow-lg">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-100 text-red-600">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
          </svg>
        </div>
        <h2 className="mb-2 text-xl font-extrabold text-slate-900">Access Denied</h2>
        <p className="mb-6 text-sm text-slate-500">
          You do not have permission to access this area.
        </p>
        <button
          onClick={() => navigate(homePath, { replace: true })}
          className="rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-bold text-white shadow transition hover:bg-indigo-500 active:scale-[0.98]"
        >
          Go to My Dashboard
        </button>
      </div>
    </div>
  );
}

function LoginRedirect() {
  const token = localStorage.getItem("access_token");
  const role = localStorage.getItem("role");

  if (token && role) {
    return <Navigate to={role === "ADMINISTRATOR" ? "/admin" : "/accountant"} replace />;
  }

  return <Login />;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

function App() {
  useEffect(() => {
    authErrorRedirectScheduled = false;
  }, []);

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<LoginRedirect />} />
        <Route
          path="/accountant"
          element={
            <ProtectedRoute allowedRole="ACCOUNTANT">
              <AccountantDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute allowedRole="ADMINISTRATOR">
              <AdminDashboard />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
