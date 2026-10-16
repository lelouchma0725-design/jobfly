import { useEffect, useState } from "react";
import { api } from "../lib/api";

type Settings = {
  ai_optimize_resume: boolean;
  ai_optimize_cover_letter: boolean;
  match_threshold: number;
  auto_apply_mode: "off" | "threshold" | "all";
  apply_rate_limit_min: number;
  push_time_local: string;
  timezone: string;
  daily_digest_enabled: boolean;
  login_expiry_notify: boolean;
  preferred_locations: string[] | null;
  location_weight: number;
};

const DEFAULTS: Settings = {
  ai_optimize_resume: false,
  ai_optimize_cover_letter: false,
  match_threshold: 70,
  auto_apply_mode: "threshold",
  apply_rate_limit_min: 5,
  push_time_local: "08:00",
  timezone: "Asia/Shanghai",
  daily_digest_enabled: true,
  login_expiry_notify: true,
  preferred_locations: [],
  location_weight: 10,
};

type PushChannels = Record<string, string>;

export default function Settings() {
  const [s, setS] = useState<Settings>(DEFAULTS);
  const [channels, setChannels] = useState<PushChannels>({});
  const [chForm, setChForm] = useState({ channel: "pushplus", value: "" });
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api<Settings>("/api/me/settings")
      .then(setS)
      .catch(() => setMsg("讀取設置失敗"));
    api<PushChannels>("/api/me/push-channels").then(setChannels).catch(() => {});
  }, []);

  async function saveChannel() {
    setMsg("");
    try {
      await api(`/api/me/push-channels?channel=${chForm.channel}`, {
        method: "PATCH",
        body: JSON.stringify({ value: chForm.value || null }),
      });
      setChForm({ ...chForm, value: "" });
      setChannels(await api<PushChannels>("/api/me/push-channels"));
      setMsg("推送渠道已更新");
    } catch (e) {
      setMsg(`保存失敗: ${(e as Error).message}`);
    }
  }

  async function save(patch: Partial<Settings>) {
    const next = { ...s, ...patch };
    setS(next);
    try {
      await api("/api/me/settings", { method: "PATCH", body: JSON.stringify(patch) });
      setMsg("已保存");
    } catch {
      setMsg("保存失敗");
    }
  }

  return (
    <div className="page">      <main className="narrow">
        <div className="card">
          <h2>投遞與推送設置</h2>

          <h3>AI 內容微調</h3>
          <label className="row">
            <input
              type="checkbox"
              checked={s.ai_optimize_resume}
              onChange={(e) => save({ ai_optimize_resume: e.target.checked })}
            />
            投遞時允許按崗位要求微調簡歷
          </label>
          <label className="row">
            <input
              type="checkbox"
              checked={s.ai_optimize_cover_letter}
              onChange={(e) => save({ ai_optimize_cover_letter: e.target.checked })}
            />
            投遞時允許按崗位要求生成/微調 Cover Letter
          </label>

          <h3>貼合度閾值</h3>
          <label className="row">
            <input
              type="range"
              min={50}
              max={100}
              step={5}
              value={s.match_threshold}
              onChange={(e) => save({ match_threshold: Number(e.target.value) })}
            />
            <b>{s.match_threshold}%</b> — 貼合度高於此值才推送/投遞
          </label>

          <h3>期望地區加權</h3>
          <p className="muted">命中期望城市的崗位加分，其他地區適度降分（影響貼合度排序與投遞）。</p>
          <label className="row">
            <input
              placeholder="期望城市，逗號分隔（如：上海,香港）"
              defaultValue={(s.preferred_locations ?? []).join(",")}
              onBlur={(e) =>
                save({
                  preferred_locations: e.target.value
                    .split(/[,，]/)
                    .map((x) => x.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <label className="row">
            <input
              type="range"
              min={0}
              max={25}
              step={5}
              value={s.location_weight}
              onChange={(e) => save({ location_weight: Number(e.target.value) })}
            />
            <b>+{s.location_weight}</b> 分 — 地區權重（非期望城市 -{Math.min(s.location_weight, 10)} 分）
          </label>

          <h3>自動投遞模式</h3>
          {(
            [
              ["off", "關閉自動投遞：僅按閾值推送崗位"],
              ["threshold", "達標自動投遞：貼合度達標的崗位自動投遞"],
              ["all", "全自動投遞：所有崗位都投，無法完成的推送人工處理"],
            ] as const
          ).map(([value, desc]) => (
            <label className="row" key={value}>
              <input
                type="radio"
                name="mode"
                checked={s.auto_apply_mode === value}
                onChange={() => save({ auto_apply_mode: value })}
              />
              {desc}
            </label>
          ))}

          <h3>每日推送</h3>
          <label className="row">
            推送時間
            <input
              type="time"
              value={s.push_time_local}
              onChange={(e) => save({ push_time_local: e.target.value })}
            />
          </label>
          <label className="row">
            時區
            <select value={s.timezone} onChange={(e) => save({ timezone: e.target.value })}>
              <option value="Asia/Shanghai">北京時間 (UTC+8)</option>
              <option value="Asia/Hong_Kong">香港時間 (UTC+8)</option>
              <option value="Asia/Taipei">台北時間 (UTC+8)</option>
              <option value="Asia/Singapore">新加坡時間 (UTC+8)</option>
              <option value="America/Los_Angeles">美西 (UTC-8)</option>
              <option value="America/New_York">美東 (UTC-5)</option>
              <option value="Europe/London">倫敦 (UTC+0)</option>
            </select>
          </label>
          <label className="row">
            <input
              type="checkbox"
              checked={s.daily_digest_enabled}
              onChange={(e) => save({ daily_digest_enabled: e.target.checked })}
            />
            啟用每日摘要推送
          </label>
          <label className="row">
            <input
              type="checkbox"
              checked={s.login_expiry_notify}
              onChange={(e) => save({ login_expiry_notify: e.target.checked })}
            />
            平台登錄態失效時提醒我
          </label>

          <h3>推送渠道（FR-1h，token 加密存儲）</h3>
          <p className="muted">
            已配置：{Object.entries(channels).length ? Object.entries(channels).map(([k, v]) => `${k}(${v})`).join("、") : "無"}
          </p>
          <div className="row wrap">
            <select
              value={chForm.channel}
              onChange={(e) => setChForm({ ...chForm, channel: e.target.value })}
            >
              <option value="pushplus">PushPlus（微信，需實名，每日200條免費）</option>
              <option value="wecom">企業微信群機器人 webhook</option>
              <option value="email">郵箱地址</option>
            </select>
            <input
              placeholder={
                chForm.channel === "email" ? "你的郵箱" : chForm.channel === "wecom"
                  ? "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…" : "PushPlus token"
              }
              value={chForm.value}
              onChange={(e) => setChForm({ ...chForm, value: e.target.value })}
            />
            <button onClick={() => void saveChannel()}>保存渠道</button>
          </div>

          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
