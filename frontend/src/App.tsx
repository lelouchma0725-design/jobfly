import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { getSession, signOut } from "./lib/auth";
import type { AuthSession } from "./lib/auth";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import Accounts from "./pages/Accounts";
import Companies from "./pages/Companies";
import Profile from "./pages/Profile";
import Jobs from "./pages/Jobs";
import Matches from "./pages/Matches";
import Applications from "./pages/Applications";
import Tasks from "./pages/Tasks";
import Admin from "./pages/Admin";

export default function App() {
  const [session, setSession] = useState<AuthSession | null>(() => getSession());

  useEffect(() => {
    // 頁面刷新時若有會話則維持；失效由 api() 的 401 刷新機制處理
    setSession(getSession());
  }, []);

  if (!session) return <Login onLogin={setSession} />;

  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="/jobs" element={<Jobs />} />
      <Route path="/matches" element={<Matches />} />
      <Route path="/applications" element={<Applications />} />
      <Route path="/tasks" element={<Tasks />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="/documents" element={<Documents />} />
      <Route path="/profile" element={<Profile />} />
      <Route path="/accounts" element={<Accounts />} />
      <Route path="/companies" element={<Companies />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export { signOut };
