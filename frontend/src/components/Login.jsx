import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Eye, EyeOff, Lock, LogIn, User } from "lucide-react";

const API_BASE = "http://127.0.0.1:8000";

const Login = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (!username.trim() || !password.trim()) {
      setError("Please enter both username and password.");
      return;
    }

    setLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/api/auth/login`, {
        username: username.trim(),
        password,
      });

      const { access_token, role, username: uname } = res.data;
      localStorage.setItem("access_token", access_token);
      localStorage.setItem("role", role);
      localStorage.setItem("username", uname);

      if (role === "ADMINISTRATOR") {
        navigate("/admin", { replace: true });
      } else {
        navigate("/accountant", { replace: true });
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (typeof detail === "string") {
        setError(detail);
      } else {
        setError("Login failed. Please check your credentials.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-indigo-950 to-slate-900 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-600 shadow-lg shadow-indigo-500/30">
            <Lock className="text-white" size={28} />
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white">
            Diva Software
          </h1>
          <p className="mt-1 text-sm text-indigo-300">
            Secure OCR Platform Access
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl"
        >
          <h2 className="mb-6 text-center text-lg font-bold text-white">
            Sign in to your account
          </h2>

          {error && (
            <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm font-medium text-red-300">
              {error}
            </div>
          )}

          <div className="mb-4">
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-indigo-300">
              Username
            </label>
            <div className="relative">
              <User
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter username"
                autoComplete="username"
                className={`w-full rounded-xl border bg-white/5 py-3 pl-10 pr-4 text-sm text-white placeholder-slate-500 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 ${
                  error ? "border-red-500/50" : "border-white/10"
                }`}
              />
            </div>
          </div>

          <div className="mb-6">
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-indigo-300">
              Password
            </label>
            <div className="relative">
              <Lock
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                autoComplete="current-password"
                className={`w-full rounded-xl border bg-white/5 py-3 pl-10 pr-11 text-sm text-white placeholder-slate-500 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 ${
                  error ? "border-red-500/50" : "border-white/10"
                }`}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white transition"
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-3 text-sm font-bold text-white shadow-lg shadow-indigo-500/25 transition hover:bg-indigo-500 active:scale-[0.98] disabled:opacity-60"
          >
            {loading ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            ) : (
              <LogIn size={16} />
            )}
            {loading ? "Authenticating..." : "Sign In"}
          </button>

          <p className="mt-6 text-center text-xs text-slate-500">
            Protected by JWT token authentication
          </p>
        </form>
      </div>
    </div>
  );
};

export default Login;
