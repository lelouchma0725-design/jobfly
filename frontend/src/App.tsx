import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { getSession } from "./lib/auth";
import type { AuthSession } from "./lib/auth";
import Header from "./components/Header";
import Login from "./pages/Login";
import Home from "./pages/Home";
import Me from "./pages/Me";
import Admin from "./pages/Admin";

export default function App() {
  const [session, setSession] = useState<AuthSession | null>(() => getSession());

  useEffect(() => {
    // 頁面刷新時若有會話則維持；失效由 api() 的 401 刷新機制處理
    setSession(getSession());
  }, []);

  if (!session) return <Login onLogin={setSession} />;

  return (
    <div className="page">
      <Header />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/me" element={<Me />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
