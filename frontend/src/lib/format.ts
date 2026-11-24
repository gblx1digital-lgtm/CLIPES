export function fmtDuration(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return "—";
  const total = Math.max(0, Math.round(s));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

/** Timecode preciso (mm:ss.d) para o editor. */
export function fmtTimecode(s: number): string {
  if (!isFinite(s)) return "0:00.0";
  const neg = s < 0;
  s = Math.abs(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const ss = sec.toFixed(1).padStart(4, "0");
  return `${neg ? "-" : ""}${h ? `${h}:${String(m).padStart(2, "0")}` : m}:${ss}`;
}

const rtf = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 45) return "agora";
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 7) return rtf.format(Math.round(diff / 86400), "day");
  return fmtDate(iso);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i ? 1 : 0)} ${u[i]}`;
}

export function fmtNumber(n: number): string {
  return n.toLocaleString("pt-BR");
}

export const JOB_LABELS: Record<string, string> = {
  monitor_creator: "Monitorar canal",
  ingest_media: "Preparar mídia",
  analyze_video: "Análise com IA",
  render_export: "Renderizar MP4",
};

export const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  twitch: "Twitch",
  upload: "Upload",
  url: "Link direto",
  drive: "Google Drive",
};

export const RIGHTS_LABELS: Record<string, string> = {
  own: "Conteúdo próprio",
  authorized: "Autorizado pelo criador",
  licensed: "Licenciado",
};
