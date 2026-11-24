import clsx from "clsx";
import { AlertTriangle, ArrowRight, CheckCircle2, Circle, Radar, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useDashboard } from "../components/AppShell";
import { LiveBadge } from "./CreatorsPage";
import { ClipCard } from "../components/ClipCard";
import { ClipViewer } from "../components/ClipViewer";
import { EmptyState, ErrorBox, PageHeader, ProgressBar, Section, Stat } from "../components/ui";
import type { ActivityItem, Dashboard } from "../lib/api";
import { fmtNumber, fmtRelative, JOB_LABELS } from "../lib/format";

export default function DashboardPage() {
  const { data, error, isLoading } = useDashboard();
  const [openClip, setOpenClip] = useState<number | null>(null);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Visão geral da descoberta, revisão e exportação de cortes"
        actions={
          <Link to="/clipes?status=pending_review" className="btn-secondary">
            Revisar cortes <ArrowRight size={14} />
          </Link>
        }
      />
      <div className="space-y-5 p-6">
        <ErrorBox error={error} />
        {data && <SetupChecklist data={data} />}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {isLoading || !data ? (
            Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-[88px]" />)
          ) : (
            <>
              <Stat label="Vídeos analisados" value={fmtNumber(data.stats.videos_analyzed)} sub={`${data.stats.videos_total} vídeos encontrados`} />
              <Stat label="Clipes encontrados" value={fmtNumber(data.stats.clips_total)} sub={`${data.stats.clips_rejected} rejeitados`} />
              <Stat label="Aguardando revisão" value={fmtNumber(data.stats.clips_pending)} tone={data.stats.clips_pending ? "warn" : undefined} />
              <Stat label="Aprovados" value={fmtNumber(data.stats.clips_approved)} />
              <Stat label="Exportados" value={fmtNumber(data.stats.clips_exported)} />
              <Stat label="Alto potencial viral" value={fmtNumber(data.stats.clips_high)} tone={data.stats.clips_high ? "good" : undefined} sub="pontuação ≥ 75" />
            </>
          )}
        </div>

        <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
          <div className="space-y-5">
            <Section title="Cortes descobertos · últimos 14 dias">
              <div className="px-4 pb-3 pt-4">{data ? <BarChart data={data.clips_per_day} /> : <div className="skeleton h-36" />}</div>
            </Section>

            <Section
              title="Melhores cortes aguardando revisão"
              actions={<Link to="/clipes?status=pending_review" className="text-xs text-muted hover:text-fg">Ver todos</Link>}
            >
              {data && data.top_pending.length === 0 ? (
                <EmptyState icon={<Sparkles size={16} />} title="Nada aguardando revisão" description="Quando a IA encontrar novos momentos, os melhores aparecem aqui primeiro." />
              ) : (
                <div className="grid grid-cols-2 gap-3 p-4 lg:grid-cols-4">
                  {data?.top_pending.map((c) => <ClipCard key={c.id} clip={c} onOpen={(x) => setOpenClip(x.id)} compact />)}
                </div>
              )}
            </Section>

            <Section title="Fontes monitoradas" actions={<Link to="/criadores" className="text-xs text-muted hover:text-fg">Gerenciar</Link>}>
              {data && data.sources.length === 0 ? (
                <EmptyState icon={<Radar size={16} />} title="Nenhum criador cadastrado" action={<Link to="/criadores" className="btn-secondary">Adicionar criadores</Link>} />
              ) : (
                <div className="divide-y divide-line/[0.06]">
                  {data?.sources.map((c) => (
                    <div key={c.id} className="flex items-center gap-3 px-4 py-2.5 text-xs">
                      <span className={clsx("h-1.5 w-1.5 rounded-full", !c.active ? "bg-faint" : c.last_check_error ? "bg-warn" : c.last_checked_at ? "bg-good" : "bg-faint")} />
                      <span className="flex w-48 items-center gap-2 truncate text-[13px] font-medium">{c.name}{c.live_now && <LiveBadge url={c.live_url} title={c.live_title} />}</span>
                      <span className="hidden truncate text-muted sm:block">
                        {c.live_now && c.live_title ? c.live_title : [c.youtube_handle && `YouTube ${c.youtube_handle}`, c.twitch_login && `Twitch ${c.twitch_login}`, c.drive_folder_id && "Google Drive"].filter(Boolean).join(" · ") || "Sem canal cadastrado"}
                      </span>
                      <span className="ml-auto whitespace-nowrap text-faint">
                        {!c.active ? "Pausado" : c.last_checked_at ? `Verificado ${fmtRelative(c.last_checked_at)}` : "Nunca verificado"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          </div>

          <div className="space-y-5">
            <Section title="Status do processamento" actions={<Link to="/descoberta" className="text-xs text-muted hover:text-fg">Fila</Link>}>
              {data ? <Processing data={data} /> : <div className="skeleton m-4 h-24" />}
            </Section>
            <Section title="Últimas atividades da IA">
              {data && data.activity.length === 0 ? (
                <p className="px-4 py-6 text-center text-xs text-muted">Nenhuma atividade registrada ainda.</p>
              ) : (
                <ol className="relative space-y-0 px-4 py-3">
                  {data?.activity.map((a) => <ActivityRow key={a.id} a={a} />)}
                </ol>
              )}
            </Section>
          </div>
        </div>
      </div>
      <ClipViewer clipId={openClip} onClose={() => setOpenClip(null)} />
    </>
  );
}

function SetupChecklist({ data }: { data: Dashboard }) {
  const i = data.integrations;
  const items = [
    { ok: data.processing.worker.online, label: "Worker de processamento rodando", hint: "make worker" },
    { ok: i.ffmpeg.configured, label: "FFmpeg instalado", hint: "necessário para análise e exportação" },
    { ok: i.ai.configured, label: "Chave da Anthropic (Claude) configurada", hint: "ANTHROPIC_API_KEY no .env" },
    { ok: i.youtube.configured || i.twitch.configured, label: "API do YouTube ou da Twitch configurada", hint: "para monitorar novos vídeos" },
    { ok: data.sources.length > 0, label: "Criadores cadastrados", hint: "em Criadores" },
  ];
  if (items.every((x) => x.ok)) return null;
  return (
    <div className="card flex flex-col gap-3 px-4 py-3.5 lg:flex-row lg:items-center">
      <div className="flex items-center gap-2 text-[13px] font-medium lg:w-56">
        <AlertTriangle size={15} className="text-warn" /> Configuração pendente
      </div>
      <div className="flex flex-1 flex-wrap gap-x-5 gap-y-1.5">
        {items.map((x) => (
          <span key={x.label} className={clsx("inline-flex items-center gap-1.5 text-xs", x.ok ? "text-muted" : "text-fg")} title={x.hint}>
            {x.ok ? <CheckCircle2 size={13} className="text-good" /> : <Circle size={13} className="text-faint" />}
            {x.label}
          </span>
        ))}
      </div>
      <Link to="/configuracoes" className="btn-secondary btn-sm">Ver detalhes</Link>
    </div>
  );
}

function Processing({ data }: { data: Dashboard }) {
  const p = data.processing;
  return (
    <div className="space-y-3 p-4">
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          ["Em execução", p.running],
          ["Na fila", p.queued],
          ["Falhas 24h", p.failed_24h],
        ].map(([l, v]) => (
          <div key={l as string} className="rounded-md bg-bg px-2 py-2">
            <p className={clsx("font-mono text-lg tabular-nums", l === "Falhas 24h" && (v as number) > 0 && "text-bad")}>{v}</p>
            <p className="text-2xs text-faint">{l}</p>
          </div>
        ))}
      </div>
      {p.active_jobs.length === 0 ? (
        <p className="text-center text-xs text-muted">{p.worker.online ? "Nenhum job em andamento." : "Worker offline: jobs ficam na fila até ele iniciar."}</p>
      ) : (
        <div className="space-y-2.5">
          {p.active_jobs.slice(0, 5).map((j) => (
            <div key={j.id} className="space-y-1.5">
              <div className="flex justify-between gap-2 text-xs">
                <span className="truncate">{JOB_LABELS[j.type]} <span className="text-faint">#{j.id}</span></span>
                <span className="shrink-0 font-mono text-2xs text-muted">{j.status === "running" ? `${j.progress.toFixed(0)}%` : "na fila"}</span>
              </div>
              <ProgressBar value={j.status === "running" ? j.progress : 0} tone="info" />
              {j.message && j.status === "running" && <p className="truncate text-2xs text-faint">{j.message}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const LEVEL_DOT: Record<string, string> = { info: "bg-info", success: "bg-good", warning: "bg-warn", error: "bg-bad" };

function ActivityRow({ a }: { a: ActivityItem }) {
  const href = a.ref_type === "clip" ? `/clipes?open=${a.ref_id}` : a.ref_type === "video" ? "/descoberta" : a.ref_type === "creator" ? "/criadores" : undefined;
  const body = (
    <>
      <span className={clsx("mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full", LEVEL_DOT[a.level])} />
      <div className="min-w-0 flex-1">
        <p className="text-xs leading-relaxed text-fg/90">{a.message}</p>
        <p className="text-2xs text-faint">{fmtRelative(a.created_at)}</p>
      </div>
    </>
  );
  return (
    <li>
      {href ? (
        <Link to={href} className="-mx-2 flex gap-2.5 rounded-md px-2 py-1.5 hover:bg-hover/50">{body}</Link>
      ) : (
        <div className="flex gap-2.5 py-1.5">{body}</div>
      )}
    </li>
  );
}

function BarChart({ data }: { data: { date: string; count: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((s, d) => s + d.count, 0);
  return (
    <div>
      <div className="flex h-32 items-end gap-1.5">
        {data.map((d) => (
          <div key={d.date} className="group relative flex h-full flex-1 flex-col justify-end">
            <div
              className={clsx("w-full rounded-sm transition-colors", d.count ? "bg-fg/25 group-hover:bg-accent" : "bg-line/[0.05]")}
              style={{ height: d.count ? `${Math.max(4, (d.count / max) * 100)}%` : "2px" }}
            />
            <div className="pointer-events-none absolute -top-7 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-raised px-1.5 py-0.5 text-2xs shadow group-hover:block">
              {d.count} · {new Date(d.date + "T12:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-2xs text-faint">
        <span>{new Date(data[0]?.date + "T12:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })}</span>
        <span>{total} cortes no período</span>
        <span>Hoje</span>
      </div>
    </div>
  );
}
