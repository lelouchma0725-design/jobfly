import { Session } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { supabase } from "./lib/supabase";
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
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (loading) return <div className="center">載入中…</div>;
  if (!session) return <Login />;

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
