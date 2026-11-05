import { useT } from "../lib/i18n";

export default function Pager({
  total,
  limit,
  offset,
  onPage,
  onLimit,
}: {
  total: number;
  limit: number;
  offset: number;
  onPage: (offset: number) => void;
  onLimit: (limit: number) => void;
}) {
  const { t } = useT();
  const pages = Math.max(1, Math.ceil(total / limit));
  const cur = Math.floor(offset / limit) + 1;
  return (
    <div className="pager">
      <span className="muted">{t("total").replace("{n}", String(total))}</span>
      <select value={limit} onChange={(e) => onLimit(Number(e.target.value))}>
        {[10, 20, 50, 100].map((n) => (
          <option key={n} value={n}>
            {t("pageSize")} {n}
          </option>
        ))}
      </select>
      <button className="ghost small" disabled={cur <= 1} onClick={() => onPage((cur - 2) * limit)}>
        {t("prev")}
      </button>
      <span>
        {cur} / {pages}
      </span>
      <button
        className="ghost small"
        disabled={cur >= pages}
        onClick={() => onPage(cur * limit)}
      >
        {t("next")}
      </button>
    </div>
  );
}
