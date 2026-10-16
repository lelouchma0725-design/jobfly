import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { getSession } from "./lib/auth";
import type { AuthSession } from "./lib/auth";
import { LangProvider } from "./lib/i18n";
import { onLoadingChange } from "./lib/loading";
import Header from "./components/Header";
import Login from "./pages/Login";
import Home from "./pages/Home";
import Me from "./pages/Me";
import Admin from "./pages/Admin";

export default function App() {
  const [session, setSession] = useState<AuthSession | null>(() => getSession());
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setSession(getSession());
    return onLoadingChange(setLoading);
  }, []);

  return (
    <LangProvider>
      {!session ? (
        <Login onLogin={setSession} />
      ) : (
        <div className="page">
          <Header />
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/me" element={<Me />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          {loading && (
            <div className="loading-mask">
              <div className="loading-spinner" />
              <div className="loading-text">Loading…</div>
            </div>
          )}
        </div>
      )}
    </LangProvider>
  );
}
