import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, ExternalLink, Scissors, Sparkles, Undo2, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, CATEGORY_OPTIONS, type ClipDetail, type ExportItem } from "../lib/api";
import { fmtDateTime, fmtDuration, fmtTimecode, PLATFORM_LABELS, RIGHTS_LABELS } from "../lib/format";
import { Badge, CLIP_STATUS, Drawer, ErrorBox, ProgressBar, RENDER_STATUS, ScoreBadge, Select, useToast } from "./ui";
import { ExportedPlayer, VerticalPreview } from "./VerticalPlayer";

export function useClipActions() {
  const qc = useQueryClient();
  const toast = useToast();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["clips"] });
    void qc.invalidateQueries({ queryKey: ["clip"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
    void qc.invalidateQueries({ queryKey: ["categories"] });
    void qc.invalidateQueries({ queryKey: ["exports"] });
  };
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.patch<ClipDetail>(`/api/clips/${id}`, body),
    onSuccess: (c, vars) => {
      invalidate();
      if ("status" in vars.body) toast("good", c.status === "approved" ? "Corte aprovado." : c.status === "rejected" ? "Corte rejeitado." : "Corte voltou para revisão.");
    },
    onError: (e: Error) => toast("bad", e.message),
  });
  const exportClip = useMutation({
    mutationFn: ({ id, quality }: { id: number; quality?: string }) => api.post<ExportItem>(`/api/clips/${id}/export`, quality ? { quality } : {}),
    onSuccess: () => {
      invalidate();
      toast("info", "Exportação adicionada à fila de renderização.");
    },
    onError: (e: Error) => toast("bad", e.message),
  });
  return { update, exportClip };
}

export function ClipViewer({ clipId, onClose }: { clipId: number | null; onClose: () => void }) {
  const navigate = useNavigate();
  const { update, exportClip } = useClipActions();
  const { data: clip, error, isLoading } = useQuery({
    queryKey: ["clip", clipId],
    queryFn: () => api.get<ClipDetail>(`/api/clips/${clipId}`),
    enabled: clipId != null,
    refetchInterval: (q) => (q.state.data?.render_status === "queued" || q.state.data?.render_status === "rendering" ? 2000 : false),
  });

  const lastExport = clip?.exports.find((e) => e.status === "done");
  const activeExport = clip?.exports.find((e) => e.status === "queued" || e.status === "rendering");
  const { data: liveExports } = useQuery({
    queryKey: ["exports", "active"],
    queryFn: () => api.get<ExportItem[]>("/api/exports?status=queued,rendering"),
    enabled: !!activeExport,
    refetchInterval: 1500,
  });
  const live = liveExports?.find((e) => e.id === activeExport?.id);

  return (
    <Drawer open={clipId != null} onClose={onClose}>
      <div className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b hairline bg-panel/90 px-5 backdrop-blur">
        {clip && <ScoreBadge score={clip.viral_score} tier={clip.tier} />}
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-semibold">{clip?.title ?? "Carregando…"}</p>
          {clip && (
            <p className="truncate text-xs text-muted">
              {clip.creator_name} · {clip.tier_label} · {fmtDuration(clip.duration_s)}
            </p>
          )}
        </div>
        <button className="btn-ghost btn-icon" onClick={onClose} aria-label="Fechar">
          <X size={16} />
        </button>
      </div>
      {isLoading && <div className="p-6"><div className="skeleton h-96 w-full" /></div>}
      {error && <div className="p-5"><ErrorBox error={error} /></div>}
      {clip && (
        <div className="grid gap-6 p-5 md:grid-cols-[300px_1fr]">
          <div className="space-y-3">
            {lastExport?.file_url ? (
              <>
                <ExportedPlayer src={lastExport.file_url} />
                <p className="text-center text-2xs text-faint">MP4 exportado · {lastExport.width}×{lastExport.height}</p>
              </>
            ) : clip.source?.stream_url ? (
              <>
                <VerticalPreview src={clip.source.stream_url} start={clip.start_s} end={clip.end_s} layout={clip.layout} />
                <p className="text-center text-2xs text-faint">Prévia 9:16 do enquadramento final</p>
              </>
            ) : (
              <div className="card flex items-center justify-center text-center text-xs text-muted" style={{ aspectRatio: "9/16" }}>
                Mídia original indisponível
              </div>
            )}
          </div>

          <div className="min-w-0 space-y-5">
            <div className="flex flex-wrap gap-2">
              {clip.status !== "approved" && (
                <button className="btn-primary" disabled={update.isPending} onClick={() => update.mutate({ id: clip.id, body: { status: "approved" } })}>
                  <Check size={14} /> Aprovar
                </button>
              )}
              {clip.status !== "rejected" && (
                <button className="btn-secondary" disabled={update.isPending} onClick={() => update.mutate({ id: clip.id, body: { status: "rejected" } })}>
                  <X size={14} /> Rejeitar
                </button>
              )}
              {clip.status !== "pending_review" && (
                <button className="btn-ghost" disabled={update.isPending} onClick={() => update.mutate({ id: clip.id, body: { status: "pending_review" } })}>
                  <Undo2 size={14} /> Voltar para revisão
                </button>
              )}
              <button className="btn-secondary" onClick={() => navigate(`/editor?clip=${clip.id}`)}>
                <Scissors size={14} /> Abrir no editor
              </button>
              <button
                className="btn-secondary"
                disabled={clip.status !== "approved" || !!activeExport || exportClip.isPending}
                title={clip.status !== "approved" ? "Aprove o corte para exportar" : undefined}
                onClick={() => exportClip.mutate({ id: clip.id })}
              >
                <Download size={14} /> Exportar MP4
              </button>
              {lastExport?.download_url && (
                <a className="btn-ghost" href={lastExport.download_url}>
                  <Download size={14} /> Baixar
                </a>
              )}
            </div>

            {activeExport && (
              <div className="card space-y-2 px-4 py-3">
                <div className="flex justify-between text-xs">
                  <span>{live?.job_message ?? RENDER_STATUS[clip.render_status].label}</span>
                  <span className="font-mono text-muted">{(live?.progress ?? 0).toFixed(0)}%</span>
                </div>
                <ProgressBar value={live?.progress ?? 0} tone="info" />
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={CLIP_STATUS[clip.status].tone} dot>{CLIP_STATUS[clip.status].label}</Badge>
              <Badge tone={RENDER_STATUS[clip.render_status].tone}>{RENDER_STATUS[clip.render_status].label}</Badge>
              {clip.auto_approved && <Badge tone="info">Aprovado automaticamente</Badge>}
              <div className="ml-auto w-48">
                <Select value={clip.category} onChange={(v) => update.mutate({ id: clip.id, body: { category: v } })}>
                  {CATEGORY_OPTIONS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                </Select>
              </div>
            </div>

            <div className="space-y-3 text-[13px] leading-relaxed">
              {clip.summary && <p>{clip.summary}</p>}
              {clip.hook && (
                <p className="text-muted"><span className="text-faint">Gancho: </span>{clip.hook}</p>
              )}
              {clip.rationale && (
                <p className="text-muted"><span className="text-faint">Avaliação da IA: </span>{clip.rationale}</p>
              )}
            </div>

            <TitleOptions clip={clip} />

            <div className="card">
              <div className="flex items-center justify-between border-b hairline px-4 py-2.5">
                <p className="text-xs font-medium">Pontuação de potencial viral</p>
                <p className="text-2xs text-faint">Estimativa da IA · não é garantia</p>
              </div>
              <div className="space-y-2.5 px-4 py-3">
                {Object.entries(clip.score_breakdown.criteria).map(([k, c]) => (
                  <div key={k} className="grid grid-cols-[1fr_120px_28px] items-center gap-3 text-xs">
                    <span className="truncate text-muted">{c.label}</span>
                    <div className="h-1 rounded-full bg-line/[0.07]">
                      <div className="h-full rounded-full bg-fg/70" style={{ width: `${c.value * 10}%` }} />
                    </div>
                    <span className="text-right font-mono tabular-nums">{c.value}</span>
                  </div>
                ))}
                <div className="flex justify-between border-t hairline pt-2.5 text-2xs text-faint">
                  <span>IA {clip.score_breakdown.ai_score} × 85% + sinais {clip.score_breakdown.signal_score} × 15%</span>
                  <span className="font-mono">{clip.analysis_source}</span>
                </div>
              </div>
            </div>

            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-xs">
              <Info label="Trecho">{fmtTimecode(clip.start_s)} → {fmtTimecode(clip.end_s)}</Info>
              <Info label="Descoberto em">{fmtDateTime(clip.discovered_at)}</Info>
              <Info label="Fonte">
                {clip.source_url ? (
                  <a href={clip.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-fg">
                    {clip.source_title} <ExternalLink size={11} />
                  </a>
                ) : clip.source_title}
              </Info>
              <Info label="Plataforma">{PLATFORM_LABELS[clip.source_platform ?? ""] ?? clip.source_platform}</Info>
              <Info label="Direitos da mídia">{RIGHTS_LABELS[clip.source?.rights_basis ?? ""] ?? "—"}</Info>
              <Info label="Layout">{clip.layout.mode === "split" ? "Webcam + gameplay" : "Gameplay em tela cheia"}</Info>
            </dl>

            {clip.exports.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium">Exportações</p>
                <div className="divide-y divide-line/[0.06] rounded-lg border hairline">
                  {clip.exports.map((e) => (
                    <div key={e.id} className="flex items-center gap-3 px-3 py-2 text-xs">
                      <span className="font-mono text-faint">#{e.id}</span>
                      <span>{e.width}×{e.height} · {e.quality}</span>
                      <Badge tone={e.status === "done" ? "good" : e.status === "failed" ? "bad" : "info"}>{e.status === "done" ? "Pronto" : e.status === "failed" ? "Falhou" : "Processando"}</Badge>
                      <span className="ml-auto text-faint">{fmtDateTime(e.created_at)}</span>
                      {e.download_url && <a href={e.download_url} className="btn-ghost btn-sm"><Download size={12} /></a>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-faint">{label}</dt>
      <dd className="mt-0.5 truncate text-muted">{children}</dd>
    </div>
  );
}

/** Opções de título/legenda geradas pela IA: copiar para colar no TikTok/Reels/Shorts ou usar como título do corte. */
function TitleOptions({ clip }: { clip: ClipDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { update } = useClipActions();
  const [copied, setCopied] = useState<number | null>(null);
  const generate = useMutation({
    mutationFn: () => api.post<ClipDetail>(`/api/clips/${clip.id}/title-options`),
    onSuccess: (c) => {
      qc.setQueryData(["clip", clip.id], c);
      toast("good", "Novas opções de título prontas.");
    },
    onError: (e: Error) => toast("bad", e.message),
  });
  const copy = async (text: string, i: number) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(i);
    toast("good", "Título copiado.");
    setTimeout(() => setCopied((c) => (c === i ? null : c)), 1500);
  };
  const options = clip.title_options ?? [];
  return (
    <div className="card">
      <div className="flex items-center justify-between gap-3 border-b hairline px-4 py-2.5">
        <p className="text-xs font-medium">Títulos para postar</p>
        <button className="btn-ghost btn-sm" disabled={generate.isPending} onClick={() => generate.mutate()}>
          <Sparkles size={12} /> {generate.isPending ? "Gerando…" : options.length ? "Gerar outras" : "Gerar opções"}
        </button>
      </div>
      {options.length === 0 ? (
        <p className="px-4 py-3 text-xs text-muted">
          {generate.isPending ? "A IA está escrevendo as opções…" : "Ainda não há opções para este corte. Clique em Gerar opções."}
        </p>
      ) : (
        <ul className="divide-y divide-line/[0.06]">
          {options.map((t, i) => (
            <li key={t} className="flex items-center gap-2 px-4 py-2 text-[13px]">
              <span className="min-w-0 flex-1 select-text">{t}</span>
              {t === clip.title ? (
                <Badge tone="good">Em uso</Badge>
              ) : (
                <button
                  className="btn-ghost btn-sm"
                  disabled={update.isPending}
                  title="Usar como título do corte"
                  onClick={() => update.mutate({ id: clip.id, body: { title: t } }, { onSuccess: () => toast("good", "Título do corte atualizado.") })}
                >
                  Usar
                </button>
              )}
              <button className="btn-ghost btn-icon h-7 w-7" title="Copiar título" aria-label="Copiar título" onClick={() => void copy(t, i)}>
                {copied === i ? <Check size={13} /> : <Copy size={13} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
