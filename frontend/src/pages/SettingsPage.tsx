import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, CircleDashed } from "lucide-react";
import type { ReactNode } from "react";
import { ErrorBox, PageHeader, Section } from "../components/ui";
import { api, type ScoringInfo, type SystemInfo } from "../lib/api";
import { fmtBytes, fmtRelative } from "../lib/format";

export default function SettingsPage() {
  const { data, error } = useQuery({ queryKey: ["system"], queryFn: () => api.get<SystemInfo>("/api/system"), refetchInterval: 15000 });
  const { data: scoring } = useQuery({ queryKey: ["scoring"], queryFn: () => api.get<ScoringInfo>("/api/scoring") });
  const i = data?.integrations;

  return (
    <>
      <PageHeader title="Configurações" description="Integrações, serviços e armazenamento. Chaves ficam no arquivo .env do servidor, nunca no navegador." />
      <div className="mx-auto max-w-4xl space-y-5 p-6">
        <ErrorBox error={error} />
        <Section title="Integrações">
          <div className="divide-y divide-line/[0.06]">
            <Item ok={i?.ai.configured} title="IA — Claude (Anthropic)" env={["ANTHROPIC_API_KEY", "AI_MODEL", "AI_EFFORT"]}
              detail={i ? `Modelo ${i.ai.model} · esforço ${i.ai.effort}` : undefined}>
              Avalia cada momento candidato (quadros do vídeo + sinais + transcrição), escolhe início/fim, categoria e notas.
              Crie a chave em <span className="text-fg">console.anthropic.com</span> → API Keys. Serviço pago por uso.
            </Item>
            <Item ok={i?.youtube.configured} title="YouTube Data API v3" env={["YOUTUBE_API_KEY"]}>
              Monitora novos vídeos dos canais (apenas metadados). Google Cloud Console → APIs e serviços → ativar “YouTube Data API v3” → Credenciais → Chave de API. Gratuita dentro da cota diária.
            </Item>
            <Item ok={i?.twitch.configured} title="Twitch Helix API" env={["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"]}>
              Monitora VODs e destaques (apenas metadados). dev.twitch.tv/console → Register Your Application (OAuth Redirect: http://localhost) → Client ID e Secret.
            </Item>
            <Item ok={i?.transcription.available} title="Transcrição de fala (opcional)" env={["TRANSCRIPTION_PROVIDER=faster_whisper", "WHISPER_MODEL"]}
              detail={i?.transcription.detail} optional>
              Whisper local melhora a detecção de piadas e diálogos. Instale com <span className="font-mono text-fg">pip install -r backend/requirements-transcription.txt</span>. Sem ela, a IA usa quadros e sinais de áudio.
            </Item>
            <Item ok={i?.ffmpeg.configured} title="FFmpeg" detail={data?.ffmpeg_version ?? undefined}>
              Necessário para análise de áudio/cena, miniaturas e renderização 1080×1920.
            </Item>
          </div>
        </Section>

        <Section title="Processamento">
          <div className="grid gap-4 p-4 sm:grid-cols-3">
            <KV k="Worker">{data?.worker.online ? <span className="text-good">Online</span> : <span className="text-warn">Offline</span>}{data?.worker.last_seen && <span className="text-faint"> · {fmtRelative(data.worker.last_seen)}</span>}</KV>
            <KV k="Banco de dados">{data?.database === "postgresql" ? "PostgreSQL" : "SQLite"}</KV>
            <KV k="Upload máximo">{data ? `${data.limits.max_upload_mb} MB` : "—"}</KV>
          </div>
        </Section>

        <Section title="Armazenamento">
          <div className="space-y-3 p-4">
            <p className="font-mono text-2xs text-faint">{data?.storage.dir}</p>
            <div className="grid gap-4 sm:grid-cols-4">
              <KV k="Vídeos de origem">{fmtBytes(data?.storage.usage_bytes.sources)}</KV>
              <KV k="Arquivos de trabalho">{fmtBytes(data?.storage.usage_bytes.work)}</KV>
              <KV k="Exportações">{fmtBytes(data?.storage.usage_bytes.exports)}</KV>
              <KV k="Miniaturas">{fmtBytes(data?.storage.usage_bytes.thumbnails)}</KV>
            </div>
          </div>
        </Section>

        <Section title="Como a pontuação viral é calculada">
          <div className="space-y-3 p-4 text-xs">
            <p className="text-muted">A IA dá uma nota de 0 a 10 para cada critério. A pontuação final (0–100) combina esses critérios (85%) com a intensidade medida no áudio e nas cenas (15%). É uma estimativa para priorizar a revisão — não uma promessa de viralização.</p>
            <div className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {scoring?.criteria.map((c) => (
                <div key={c.key} className="flex justify-between border-b hairline py-1.5">
                  <span>{c.label}</span>
                  <span className="font-mono text-muted">{Math.round(c.weight * 100)}%</span>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-4 pt-1 text-muted">
              {scoring?.tiers.map((t) => <span key={t.key}>{t.label}: <span className="font-mono text-fg">≥ {t.min}</span></span>)}
            </div>
          </div>
        </Section>

        <Section title="Direitos autorais e fontes">
          <div className="space-y-2 p-4 text-xs leading-relaxed text-muted">
            <p>O monitoramento usa apenas as APIs oficiais do YouTube e da Twitch para ler metadados (título, data, link). A plataforma não baixa vídeos dessas plataformas.</p>
            <p>Para analisar e cortar, a mídia precisa ser própria, autorizada pelo criador ou licenciada — enviada por upload ou por um link direto de arquivo. Cada vídeo guarda a base de direitos e o registro da autorização; cada corte guarda o criador e o link da fonte original.</p>
          </div>
        </Section>
      </div>
    </>
  );
}

function Item({ ok, title, env, detail, optional, children }: { ok?: boolean; title: string; env?: string[]; detail?: string; optional?: boolean; children: ReactNode }) {
  return (
    <div className="flex gap-3 px-4 py-3.5">
      {ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-good" /> : <CircleDashed size={16} className={clsx("mt-0.5 shrink-0", optional ? "text-faint" : "text-warn")} />}
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[13px] font-medium">{title}</p>
          <span className={clsx("text-2xs", ok ? "text-good" : optional ? "text-faint" : "text-warn")}>{ok ? "Configurado" : optional ? "Opcional · desativado" : "Não configurado"}</span>
        </div>
        {detail && <p className="font-mono text-2xs text-faint">{detail}</p>}
        <p className="text-xs leading-relaxed text-muted">{children}</p>
        {env && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {env.map((e) => <span key={e} className="kbd">{e}</span>)}
          </div>
        )}
      </div>
    </div>
  );
}

function KV({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-2xs text-faint">{k}</p>
      <p className="mt-0.5 text-[13px]">{children}</p>
    </div>
  );
}
