import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronRight, ExternalLink, FileVideo, Link2, Play, RefreshCw, RotateCw, Square, Trash2, Upload } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { useDashboard } from "../components/AppShell";
import { Badge, EmptyState, ErrorBox, Field, Modal, PageHeader, ProgressBar, Section, Segmented, Select, useToast } from "../components/ui";
import { api, uploadWithProgress, type Creator, type Job, type Video } from "../lib/api";
import { fmtDuration, fmtRelative, fmtTimecode, JOB_LABELS, PLATFORM_LABELS, RIGHTS_LABELS } from "../lib/format";

const MEDIA: Record<string, { label: string; tone: "neutral" | "good" | "warn" | "bad" | "info" }> = {
  none: { label: "Aguardando mídia", tone: "neutral" },
  ingesting: { label: "Preparando mídia", tone: "info" },
  ready: { label: "Mídia pronta", tone: "good" },
  failed: { label: "Falha na mídia", tone: "bad" },
};
const ANALYSIS: Record<string, { label: string; tone: "neutral" | "good" | "warn" | "bad" | "info" }> = {
  not_started: { label: "Não analisado", tone: "neutral" },
  queued: { label: "Na fila da IA", tone: "info" },
  running: { label: "IA analisando", tone: "info" },
  done: { label: "Analisado", tone: "good" },
  failed: { label: "Análise falhou", tone: "bad" },
};

export default function DiscoveryPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: dash } = useDashboard();
  const [uploadFor, setUploadFor] = useState<{ video?: Video } | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [filter, setFilter] = useState<"all" | "none" | "ready">("all");

  const busy = (dash?.processing.running ?? 0) + (dash?.processing.queued ?? 0) > 0;
  const { data: videos, error, isLoading } = useQuery({
    queryKey: ["videos", filter],
    queryFn: () => api.get<Video[]>(`/api/videos${filter === "all" ? "" : `?media_status=${filter}`}`),
    refetchInterval: busy ? 2500 : 15000,
  });
  const { data: jobs } = useQuery({ queryKey: ["jobs"], queryFn: () => api.get<Job[]>("/api/jobs?limit=30"), refetchInterval: busy ? 1500 : 10000 });
  const { data: creators } = useQuery({ queryKey: ["creators"], queryFn: () => api.get<Creator[]>("/api/creators") });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["videos"] });
    void qc.invalidateQueries({ queryKey: ["jobs"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const onErr = (e: Error) => toast("bad", e.message);

  const analyze = useMutation({ mutationFn: (id: number) => api.post(`/api/videos/${id}/analyze`), onSuccess: () => { refresh(); toast("info", "Vídeo enviado para análise da IA."); }, onError: onErr });
  const remove = useMutation({ mutationFn: (id: number) => api.del(`/api/videos/${id}`), onSuccess: () => { refresh(); toast("good", "Vídeo removido."); }, onError: onErr });
  const cancel = useMutation({ mutationFn: (id: number) => api.post(`/api/jobs/${id}/cancel`), onSuccess: refresh, onError: onErr });
  const retry = useMutation({ mutationFn: (id: number) => api.post(`/api/jobs/${id}/retry`), onSuccess: refresh, onError: onErr });
  const checkAll = useMutation({
    mutationFn: async () => {
      const list = (creators ?? []).filter((c) => c.active && (c.youtube_handle || c.youtube_channel_id || c.twitch_login || c.drive_folder_id));
      if (!list.length) throw new Error("Nenhum criador ativo com canal do YouTube ou Twitch cadastrado.");
      await Promise.all(list.map((c) => api.post(`/api/creators/${c.id}/check`)));
      return list.length;
    },
    onSuccess: (n) => { refresh(); toast("info", `Verificação de ${n} ${n === 1 ? "criador agendada" : "criadores agendada"}.`); },
    onError: onErr,
  });

  const s = dash?.stats;
  return (
    <>
      <PageHeader
        title="Descoberta com IA"
        description="Monitoramento das fontes, preparação de mídia e análise dos melhores momentos"
        actions={
          <>
            <button className="btn-secondary" onClick={() => checkAll.mutate()} disabled={checkAll.isPending}>
              <RefreshCw size={14} className={clsx(checkAll.isPending && "animate-spin")} /> Verificar canais agora
            </button>
            <button className="btn-primary" onClick={() => setUploadFor({})}>
              <Upload size={14} /> Adicionar mídia
            </button>
          </>
        }
      />
      <div className="space-y-5 p-6">
        <div className="grid gap-px overflow-hidden rounded-lg border hairline bg-line/[0.07] sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["1", "Monitorar", "Novos vídeos de GTA 6 nas APIs oficiais", `${s?.videos_total ?? 0} vídeos encontrados`],
            ["2", "Mídia autorizada", "Arquivo próprio, autorizado ou licenciado", `${s?.videos_awaiting_media ?? 0} aguardando mídia`],
            ["3", "Análise com IA", "Sinais de áudio e cena + Claude avaliando cada momento", `${s?.videos_analyzed ?? 0} analisados`],
            ["4", "Revisão", "Melhores cortes primeiro, para sua aprovação", `${s?.clips_pending ?? 0} aguardando revisão`],
          ].map(([n, t, d, m]) => (
            <div key={n} className="bg-panel px-4 py-3.5">
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full border hairline font-mono text-2xs text-muted">{n}</span>
                <p className="text-[13px] font-medium">{t}</p>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-muted">{d}</p>
              <p className="mt-2 font-mono text-2xs text-faint">{m}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
          <Section
            title="Vídeos das fontes"
            actions={
              <Segmented size="sm" value={filter} onChange={setFilter} options={[{ value: "all", label: "Todos" }, { value: "none", label: "Sem mídia" }, { value: "ready", label: "Com mídia" }]} />
            }
          >
            <ErrorBox error={error} />
            {isLoading ? (
              <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="skeleton h-14" />)}</div>
            ) : !videos?.length ? (
              <EmptyState
                icon={<FileVideo size={16} />}
                title="Nenhum vídeo ainda"
                description="Cadastre os canais dos criadores para o monitoramento encontrar novos vídeos de GTA 6, ou envie uma mídia autorizada diretamente."
                action={<button className="btn-secondary" onClick={() => setUploadFor({})}><Upload size={14} /> Adicionar mídia</button>}
              />
            ) : (
              <div className="divide-y divide-line/[0.06]">
                {videos.map((v) => (
                  <Fragment key={v.id}>
                    <div className="flex items-center gap-3 px-4 py-3">
                      <button className="btn-ghost btn-icon h-6 w-6 shrink-0" onClick={() => setExpanded(expanded === v.id ? null : v.id)} aria-label="Detalhes">
                        <ChevronRight size={14} className={clsx("transition-transform", expanded === v.id && "rotate-90")} />
                      </button>
                      <div className="hidden h-11 w-[78px] shrink-0 overflow-hidden rounded bg-raised sm:block">
                        {v.thumbnail_url ? <img src={v.thumbnail_url} alt="" className="h-full w-full object-cover" loading="lazy" /> : <div className="flex h-full items-center justify-center text-faint"><FileVideo size={14} /></div>}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-medium">{v.title}</p>
                        <p className="mt-0.5 truncate text-xs text-muted">
                          {v.creator_name} · {PLATFORM_LABELS[v.platform]} · {fmtDuration(v.duration_s)} · {fmtRelative(v.published_at ?? v.discovered_at)}
                          {v.clip_count > 0 && <> · <Link to={`/clipes?q=&creator=${v.creator_id}`} className="text-fg/80 hover:text-fg">{v.clip_count} cortes</Link></>}
                        </p>
                      </div>
                      <div className="hidden shrink-0 flex-col items-end gap-1 md:flex">
                        <Badge tone={MEDIA[v.media_status].tone} dot>{MEDIA[v.media_status].label}</Badge>
                        {v.media_status === "ready" && <Badge tone={ANALYSIS[v.analysis_status].tone}>{ANALYSIS[v.analysis_status].label}</Badge>}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        {(v.media_status === "none" || v.media_status === "failed") && (
                          <button className="btn-secondary btn-sm" onClick={() => setUploadFor({ video: v })}>
                            <Upload size={12} /> Mídia
                          </button>
                        )}
                        {v.media_status === "ready" && (
                          <button className="btn-secondary btn-sm" disabled={v.analysis_status === "queued" || v.analysis_status === "running" || analyze.isPending} onClick={() => analyze.mutate(v.id)}>
                            <Play size={12} /> {v.analysis_status === "done" || v.analysis_status === "failed" ? "Reanalisar" : "Analisar"}
                          </button>
                        )}
                        {v.url && (
                          <a href={v.url} target="_blank" rel="noreferrer" className="btn-ghost btn-icon h-7 w-7" title="Abrir fonte original">
                            <ExternalLink size={13} />
                          </a>
                        )}
                        <button
                          className="btn-ghost btn-icon h-7 w-7 hover:text-bad"
                          title="Excluir vídeo e mídia"
                          onClick={() => confirm(`Excluir “${v.title}” e todos os arquivos e cortes pendentes dele?`) && remove.mutate(v.id)}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                    {expanded === v.id && <VideoDetails v={v} />}
                  </Fragment>
                ))}
              </div>
            )}
          </Section>

          <Section title="Fila de processamento">
            {!jobs?.length ? (
              <p className="px-4 py-6 text-center text-xs text-muted">Nenhum job ainda.</p>
            ) : (
              <div className="max-h-[720px] divide-y divide-line/[0.06] overflow-y-auto">
                {jobs.map((j) => <JobRow key={j.id} j={j} onCancel={() => cancel.mutate(j.id)} onRetry={() => retry.mutate(j.id)} />)}
              </div>
            )}
          </Section>
        </div>
      </div>
      {uploadFor && <MediaModal creators={creators ?? []} video={uploadFor.video} onClose={() => setUploadFor(null)} onDone={refresh} />}
    </>
  );
}

function VideoDetails({ v }: { v: Video }) {
  const m = v.analysis_meta;
  return (
    <div className="space-y-3 bg-bg/60 px-4 py-3 pl-14 text-xs">
      <div className="grid gap-x-6 gap-y-2 sm:grid-cols-3">
        <D l="Direitos">{v.rights_basis ? RIGHTS_LABELS[v.rights_basis] : "Não registrados"}{v.rights_note ? ` — ${v.rights_note}` : ""}</D>
        <D l="Resolução">{v.width ? `${v.width}×${v.height} · ${v.fps?.toFixed(0)} fps` : "—"}</D>
        <D l="Webcam detectada">{v.layout_hint ? `Sim (estabilidade ${(v.layout_hint.stability * 100).toFixed(0)}%)` : v.analysis_status === "done" ? "Não" : "—"}</D>
        {m && <D l="Sinais">{m.scene_changes ?? 0} mudanças de cena · {m.transcript_segments ? `${m.transcript_segments} trechos transcritos` : "sem transcrição"}</D>}
        {m?.ai_evaluated != null && <D l="IA">{m.ai_evaluated} avaliados · {m.ai_kept} aprovados pela IA · {v.clip_count} cortes criados</D>}
      </div>
      {v.media_status === "none" && (
        <p className="text-muted">
          Este vídeo foi encontrado pelo monitoramento (somente metadados). Para analisar, envie o arquivo de vídeo com autorização do criador
          ou use um arquivo seu/licenciado. A plataforma não baixa vídeos do YouTube/Twitch automaticamente.
        </p>
      )}
      {v.media_error && <ErrorBox error={v.media_error} />}
      {v.analysis_error && <ErrorBox error={v.analysis_error} />}
      {m?.candidates && m.candidates.length > 0 && (
        <div>
          <p className="mb-1.5 text-faint">Momentos candidatos detectados pelos sinais ({m.candidates.length})</p>
          <div className="flex flex-wrap gap-1.5">
            {m.candidates.map((c, i) => (
              <span key={i} className="rounded border hairline bg-panel px-2 py-1 font-mono text-2xs text-muted">
                {fmtTimecode(c.start_s)}–{fmtTimecode(c.end_s)} · {c.signal_score.toFixed(0)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function D({ l, children }: { l: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-faint">{l}</p>
      <p className="mt-0.5 text-muted">{children}</p>
    </div>
  );
}

const JOB_TONE: Record<string, "neutral" | "good" | "warn" | "bad" | "info"> = { queued: "neutral", running: "info", succeeded: "good", failed: "bad", cancelled: "neutral" };
const JOB_STATUS: Record<string, string> = { queued: "Na fila", running: "Executando", succeeded: "Concluído", failed: "Falhou", cancelled: "Cancelado" };

function JobRow({ j, onCancel, onRetry }: { j: Job; onCancel: () => void; onRetry: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-1.5 px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span className="truncate text-xs font-medium">{JOB_LABELS[j.type]}</span>
        <span className="font-mono text-2xs text-faint">#{j.id}</span>
        <Badge tone={JOB_TONE[j.status]} className="ml-auto">{JOB_STATUS[j.status]}</Badge>
        {(j.status === "queued" || j.status === "running") && (
          <button className="btn-ghost btn-icon h-6 w-6" title="Cancelar" onClick={onCancel}><Square size={11} /></button>
        )}
        {(j.status === "failed" || j.status === "cancelled") && (
          <button className="btn-ghost btn-icon h-6 w-6" title="Tentar novamente" onClick={onRetry}><RotateCw size={12} /></button>
        )}
      </div>
      {j.status === "running" && <ProgressBar value={j.progress} tone="info" />}
      <p className="truncate text-2xs text-faint">
        {j.status === "running" ? j.message : j.status === "failed" ? (j.error ?? "").split("\n")[0] : j.message} · {fmtRelative(j.finished_at ?? j.started_at ?? j.created_at)}
      </p>
      {/* Falhou e vai tentar de novo: mostra o motivo já, sem esperar a última tentativa */}
      {j.status === "queued" && j.error && (
        <p className="truncate text-2xs text-bad/90" title={j.error}>{j.error.split("\n")[0]}</p>
      )}
      {(j.status === "failed" || j.status === "queued") && j.error && (
        <>
          <button className="text-2xs text-muted hover:text-fg" onClick={() => setOpen(!open)}>{open ? "Ocultar detalhes" : "Ver detalhes do erro"}</button>
          {open && <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-bg p-2 font-mono text-2xs text-bad/90">{j.error}</pre>}
        </>
      )}
    </div>
  );
}

function MediaModal({ creators, video, onClose, onDone }: { creators: Creator[]; video?: Video; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [mode, setMode] = useState<"file" | "url">("file");
  const [creatorId, setCreatorId] = useState(String(video?.creator_id ?? creators[0]?.id ?? ""));
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [rights, setRights] = useState("authorized");
  const [note, setNote] = useState("");
  const [confirmRights, setConfirmRights] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const creator = creators.find((c) => String(c.id) === creatorId);

  const submit = async () => {
    setErr(null);
    try {
      if (mode === "file") {
        if (!file) throw new Error("Selecione um arquivo de vídeo.");
        const form = new FormData();
        form.append("file", file);
        form.append("creator_id", creatorId);
        form.append("title", title);
        form.append("rights_basis", rights);
        form.append("rights_note", note);
        form.append("confirm_rights", String(confirmRights));
        if (video) form.append("video_id", String(video.id));
        setProgress(0);
        await uploadWithProgress("/api/videos/upload", form, setProgress);
      } else {
        await api.post("/api/videos/from-url", { creator_id: Number(creatorId), url, title, rights_basis: rights, rights_note: note, confirm_rights: confirmRights, video_id: video?.id });
      }
      toast("good", "Mídia recebida. A preparação e a análise rodam em segundo plano.");
      onDone();
      onClose();
    } catch (e) {
      setErr((e as Error).message);
      setProgress(null);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={video ? `Enviar mídia · ${video.title}` : "Adicionar mídia para análise"}
      footer={
        <>
          <button className="btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn-primary" onClick={submit} disabled={progress !== null || !creatorId || !confirmRights}>
            {progress !== null ? `Enviando ${progress.toFixed(0)}%` : "Enviar e analisar"}
          </button>
        </>
      }
    >
      {!creators.length ? (
        <p className="text-xs text-muted">Cadastre um criador antes de enviar mídias. <Link to="/criadores" className="text-fg underline">Ir para Criadores</Link></p>
      ) : (
        <div className="space-y-4">
          <Segmented value={mode} onChange={setMode} options={[{ value: "file", label: <span className="inline-flex items-center gap-1.5"><Upload size={12} />Arquivo</span> }, { value: "url", label: <span className="inline-flex items-center gap-1.5"><Link2 size={12} />Link direto</span> }]} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Criador">
              <Select value={creatorId} onChange={setCreatorId}>
                {creators.map((c) => <option key={c.id} value={c.id} disabled={!!video && c.id !== video.creator_id}>{c.name}</option>)}
              </Select>
            </Field>
            {!video && (
              <Field label="Título (opcional)">
                <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ex.: Live GTA 6 — dia 3" />
              </Field>
            )}
          </div>
          {mode === "file" ? (
            <Field label="Arquivo de vídeo" hint="MP4, MOV, MKV, WEBM, M4V, TS ou FLV. Formatos que o navegador não reproduz são convertidos automaticamente.">
              <label className={clsx("flex h-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-md border border-dashed text-xs transition-colors", file ? "border-accent/40 bg-accent/[0.04]" : "border-line/15 hover:border-line/25")}>
                <input type="file" accept="video/*,.mkv,.ts,.flv" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                {file ? <><span className="font-medium">{file.name}</span><span className="text-faint">{(file.size / 1e6).toFixed(0)} MB</span></> : <span className="text-muted">Clique para selecionar o arquivo</span>}
              </label>
              {progress !== null && <ProgressBar value={progress} className="mt-2" />}
            </Field>
          ) : (
            <Field label="Link direto do arquivo" hint="Um link que baixa o arquivo de vídeo (ex.: enviado pelo criador). Páginas do YouTube, Twitch, TikTok etc. não são aceitas.">
              <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/live.mp4" />
            </Field>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Base de direitos">
              <Select value={rights} onChange={setRights}>
                <option value="authorized">Autorizado pelo criador</option>
                <option value="own">Conteúdo próprio</option>
                <option value="licensed">Licenciado</option>
              </Select>
            </Field>
            <Field label="Registro da autorização">
              <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ex.: contrato de 12/11, e-mail do criador" />
            </Field>
          </div>
          {rights === "authorized" && creator && !creator.media_authorized && (
            <p className="rounded-md border border-warn/20 bg-warn/[0.06] px-3 py-2 text-xs text-warn">
              {creator.name} ainda não está marcado como autorizado em Criadores. Registre a autorização lá para manter o histórico.
            </p>
          )}
          <label className="flex cursor-pointer items-start gap-2.5 text-xs text-muted">
            <input type="checkbox" className="mt-0.5 accent-[rgb(var(--accent))]" checked={confirmRights} onChange={(e) => setConfirmRights(e.target.checked)} />
            Confirmo que tenho direito de usar esta mídia para criar e publicar cortes, e que a fonte e o criador serão creditados.
          </label>
          {err && <ErrorBox error={err} />}
        </div>
      )}
    </Modal>
  );
}
