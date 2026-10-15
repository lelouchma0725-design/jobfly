import Header from "../components/Header";

export default function Dashboard() {
  return (
    <div className="page">
      <Header />
      <main>
        <div className="card">
          <h2>歡迎使用求職投遞助手</h2>
          <p className="muted">
            當前進度：P1 用戶模塊已就緒（文件上傳、平台帳號加密存儲、投遞設置、關注公司）。
            崗位採集、AI 畫像、自動投遞將在後續階段逐步開放。
          </p>
        </div>
      </main>
    </div>
  );
}
