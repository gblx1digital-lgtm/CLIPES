export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError(0, "Não foi possível conectar à API. Verifique se o backend está rodando.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = `Erro ${res.status}`;
    if (data?.detail) {
      msg = Array.isArray(data.detail)
        ? data.detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, "")).join("; ")
        : String(data.detail);
    }
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  put: <T>(url: string, body: unknown) => request<T>("PUT", url, body),
  patch: <T>(url: string, body: unknown) => request<T>("PATCH", url, body),
  del: <T = void>(url: string) => request<T>("DELETE", url),
};

/** Upload com progresso (fetch não expõe progresso de envio). */
export function uploadWithProgress<T>(url: string, form: FormData, onProgress: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress((e.loaded / e.total) * 100);
    xhr.onload = () => {
      let data: any = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* resposta vazia */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(new ApiError(xhr.status, data?.detail ? String(data.detail) : `Erro ${xhr.status}`));
    };
    xhr.onerror = () => reject(new ApiError(0, "Falha de rede durante o envio."));
    xhr.send(form);
  });
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

// ------------------------------------------------------------------ tipos
export type CamRect = { x: number; y: number; w: number; h: number };
export type Layout = {
  mode: "split" | "full";
  cam: CamRect | null;
  cam_height: number;
  focus_x: number;
  focus_y: number;
  zoom: number;
  cam_source?: string | null;
};

export type Creator = {
  id: number;
  name: string;
  youtube_handle: string | null;
  youtube_channel_id: string | null;
  twitch_login: string | null;
  twitch_user_id: string | null;
  active: boolean;
  media_authorized: boolean;
  authorization_note: string | null;
  default_layout: Layout | null;
  notes: string | null;
  last_checked_at: string | null;
  last_check_error: string | null;
  created_at: string;
  drive_folder_id: string | null;
  drive_folder_url: string | null;
  live_now: boolean;
  live_title: string | null;
  live_url: string | null;
  live_since: string | null;
  stats: { videos?: number; clips?: number; approved?: number; avg_score?: number; best_score?: number | null };
};

export type Video = {
  id: number;
  creator_id: number;
  creator_name: string | null;
  platform: "youtube" | "twitch" | "upload" | "url" | "drive";
  external_id: string;
  title: string;
  url: string | null;
  thumbnail_url: string | null;
  published_at: string | null;
  discovered_at: string;
  is_live_vod: boolean;
  rights_basis: string | null;
  rights_note: string | null;
  media_status: "none" | "ingesting" | "ready" | "failed";
  media_error: string | null;
  has_media: boolean;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  has_audio: boolean | null;
  analysis_status: "not_started" | "queued" | "running" | "done" | "failed";
  analysis_error: string | null;
  analyzed_at: string | null;
  layout_hint: { cam: CamRect; stability: number } | null;
  analysis_meta: {
    candidates?: { start_s: number; end_s: number; peak_s: number; signal_score: number }[];
    ai_kept?: number;
    ai_evaluated?: number;
    transcript_segments?: number;
    scene_changes?: number;
  } | null;
  clip_count: number;
};

export type ClipStatus = "pending_review" | "approved" | "rejected";
export type Clip = {
  id: number;
  source_video_id: number;
  creator_id: number;
  creator_name: string | null;
  title: string;
  summary: string | null;
  hook: string | null;
  category: string;
  category_label: string;
  start_s: number;
  end_s: number;
  duration_s: number;
  viral_score: number;
  tier: "alto" | "medio" | "baixo";
  tier_label: string;
  status: ClipStatus;
  render_status: "none" | "queued" | "rendering" | "done" | "failed";
  auto_approved: boolean;
  discovered_at: string;
  reviewed_at: string | null;
  thumbnail_url: string | null;
  source_title: string | null;
  source_url: string | null;
  source_platform: string | null;
  layout: Layout;
};

export type ClipDetail = Clip & {
  score_breakdown: {
    criteria: Record<string, { label: string; weight: number; value: number }>;
    ai_score: number;
    signal_score: number;
  };
  rationale: string | null;
  signals: Record<string, number> | null;
  analysis_source: string;
  review_note: string | null;
  title_options: string[];
  source: {
    id: number;
    width: number;
    height: number;
    duration_s: number;
    fps: number;
    has_audio: boolean;
    media_ready: boolean;
    stream_url: string | null;
    rights_basis: string | null;
    layout_hint: { cam: CamRect } | null;
  } | null;
  exports: ExportItem[];
};

export type ExportItem = {
  id: number;
  clip_id: number;
  clip_title: string | null;
  creator_name: string | null;
  status: "queued" | "rendering" | "done" | "failed";
  quality: string;
  width: number;
  height: number;
  start_s: number;
  end_s: number;
  duration_s: number;
  size_bytes: number | null;
  error: string | null;
  job_id: number | null;
  created_at: string;
  finished_at: string | null;
  download_url: string | null;
  file_url: string | null;
  progress?: number;
  job_message?: string | null;
};

export type Job = {
  id: number;
  type: "monitor_creator" | "ingest_media" | "analyze_video" | "render_export";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  message: string | null;
  error: string | null;
  attempts: number;
  max_attempts: number;
  ref_type: string | null;
  ref_id: number | null;
  payload: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type ActivityItem = {
  id: number;
  level: "info" | "success" | "warning" | "error";
  kind: string;
  message: string;
  ref_type: string | null;
  ref_id: number | null;
  created_at: string;
};

export type Integrations = {
  ai: { configured: boolean; model: string; effort: string; env: string[] };
  youtube: { configured: boolean; env: string[] };
  twitch: { configured: boolean; env: string[] };
  drive: { configured: boolean; env: string[] };
  ffmpeg: { configured: boolean };
  transcription: { provider: string; available: boolean; detail: string };
};

export type WorkerStatus = { online: boolean; last_seen: string | null; worker_id: string | null };

export type Automation = {
  monitoring_enabled: boolean;
  monitor_interval_minutes: number;
  auto_analyze: boolean;
  max_clips_per_day: number;
  max_clips_per_video: number;
  min_clip_seconds: number;
  max_clip_seconds: number;
  priority_categories: string[];
  min_viral_score: number;
  approval_mode: "manual" | "automatic";
  auto_approve_min_score: number;
  export_quality: "standard" | "high" | "max";
  title_keywords: string[];
};

export type Dashboard = {
  stats: {
    videos_total: number;
    videos_analyzed: number;
    videos_awaiting_media: number;
    clips_total: number;
    clips_pending: number;
    clips_approved: number;
    clips_rejected: number;
    clips_exported: number;
    clips_high: number;
  };
  clips_per_day: { date: string; count: number }[];
  processing: { worker: WorkerStatus; queued: number; running: number; failed_24h: number; active_jobs: Job[] };
  sources: Creator[];
  activity: ActivityItem[];
  top_pending: Clip[];
  integrations: Integrations;
  automation: Automation;
};

export type Category = {
  key: string;
  label: string;
  count: number;
  avg_score: number;
  high_count: number;
  approved: number;
  priority: boolean;
};

export type SystemInfo = {
  integrations: Integrations;
  worker: WorkerStatus;
  ffmpeg_version: string | null;
  storage: { dir: string; usage_bytes: Record<string, number> };
  database: string;
  limits: { max_upload_mb: number };
};

export type ScoringInfo = {
  criteria: { key: string; label: string; weight: number }[];
  tiers: { key: string; label: string; min: number }[];
};

export const CATEGORY_OPTIONS: { key: string; label: string }[] = [
  { key: "engracados", label: "Momentos Engraçados" },
  { key: "curiosidades", label: "Curiosidades" },
  { key: "missoes", label: "Missões" },
  { key: "bugs", label: "Bugs e Glitches" },
  { key: "reacoes", label: "Reações" },
  { key: "perseguicoes", label: "Perseguições" },
  { key: "segredos", label: "Segredos" },
  { key: "epicos", label: "Momentos Épicos" },
  { key: "noticias", label: "Notícias e novidades" },
  { key: "outros", label: "Outros" },
];
