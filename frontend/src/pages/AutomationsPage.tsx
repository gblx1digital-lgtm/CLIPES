import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Save } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useDashboard } from "../components/AppShell";
import { ErrorBox, Field, PageHeader, Section, Segmented, Select, Toggle, useToast } from "../components/ui";
import { api, CATEGORY_OPTIONS, type Automation } from "../lib/api";

export default function AutomationsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: dash } = useDashboard();
  const { data, error } = useQuery({ queryKey: ["automation"], queryFn: () => api.get<Automation>("/api/automation") });
  const [f, setF] = useState<Automation | null>(null);
  const [keywords, setKeywords] = useState("");
  useEffect(() => {
    if (data) {
      setF(data);
      setKeywords(data.title_keywords.join(", "));
    }
  }, [data]);
  const save = useMutation({
    mutationFn: (body: Automation) => api.put<Automation>("/api/automation", body),
    onSuccess: (d) => {
      qc.setQueryData(["automation"], d);
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      void qc.invalidateQueries({ queryKey: ["categories"] });
      toast("good", "Automações salvas.");
    },
  });
  if (!f) return <><PageHeader title="Automações" /><div className="p-6"><ErrorBox error={error} /><div className="skeleton h-96" /></div></>;

  const set = <K extends keyof Automation>(k: K, v: Automation[K]) => setF((s) => (s ? { ...s, [k]: v } : s));
  const dirty = JSON.stringify({ ...f, title_keywords: parseKw(keywords) }) !== JSON.stringify(data);
  const integ = dash?.integrations;
  const sourcesReady = integ && (integ.youtube.configured || integ.twitch.configured);

  return (
    <>
      <PageHeader
        title="Automações"
        description="Como a IA trabalha sozinha: frequência, limites, critérios e aprovação"
        actions={
          <button className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate({ ...f, title_keywords: parseKw(keywords) })}>
            <Save size={14} /> Salvar
          </button>
        }
      />
      <div className="mx-auto max-w-4xl space-y-5 p-6">
        {save.error && <ErrorBox error={save.error} />}

        <Section title="Monitoramento de canais">
          <div className="space-y-5 p-4">
            <Toggle
              checked={f.monitoring_enabled}
              onChange={(v) => set("monitoring_enabled", v)}
              label="Verificar novos vídeos automaticamente"
              description={sourcesReady ? "O worker consulta as APIs oficiais do YouTube/Twitch na frequência abaixo." : "Configure YOUTUBE_API_KEY ou as credenciais da Twitch (veja Configurações) para o monitoramento funcionar."}
            />
            <Row>
              <Field label="Frequência de monitoramento">
                <Select value={String(f.monitor_interval_minutes)} onChange={(v) => set("monitor_interval_minutes", Number(v))}>
                  {[15, 30, 60, 120, 240, 720, 1440].map((m) => <option key={m} value={m}>{m < 60 ? `A cada ${m} minutos` : m === 60 ? "A cada hora" : m === 1440 ? "Uma vez por dia" : `A cada ${m / 60} horas`}</option>)}
                </Select>
              </Field>
              <Field label="Palavras-chave de GTA 6 nos títulos" hint="Separadas por vírgula. Só vídeos com uma delas no título entram na descoberta.">
                <input className="input" value={keywords} onChange={(e) => setKeywords(e.target.value)} />
              </Field>
            </Row>
            <Toggle checked={f.auto_analyze} onChange={(v) => set("auto_analyze", v)} label="Analisar com IA assim que a mídia estiver pronta" description="Desative para disparar cada análise manualmente em Descoberta com IA." />
          </div>
        </Section>

        <Section title="Seleção de cortes">
          <div className="space-y-5 p-4">
            <Row>
              <Num label="Máximo de clipes por dia" value={f.max_clips_per_day} min={1} max={500} onChange={(v) => set("max_clips_per_day", v)} />
              <Num label="Máximo de clipes por vídeo" value={f.max_clips_per_video} min={1} max={50} onChange={(v) => set("max_clips_per_video", v)} />
            </Row>
            <Row>
              <Num label="Duração mínima (segundos)" value={f.min_clip_seconds} min={5} max={180} onChange={(v) => set("min_clip_seconds", v)} />
              <Num label="Duração máxima (segundos)" value={f.max_clip_seconds} min={10} max={180} onChange={(v) => set("max_clip_seconds", v)} hint="Até 180 segundos. Cortes de 1 a 2 min funcionam bem no TikTok e no Reels; o Shorts aceita até 3 min." />
            </Row>
            <Field label={`Pontuação viral mínima: ${f.min_viral_score}`} hint="Momentos abaixo desta nota são descartados.">
              <input type="range" className="w-full" min={0} max={100} value={f.min_viral_score} onChange={(e) => set("min_viral_score", Number(e.target.value))} />
            </Field>
            <Field label="Categorias prioritárias" hint="Quando há mais momentos bons do que o limite, estas categorias têm preferência.">
              <div className="flex flex-wrap gap-1.5">
                {CATEGORY_OPTIONS.map((c) => {
                  const on = f.priority_categories.includes(c.key);
                  return (
                    <button key={c.key} type="button"
                      onClick={() => set("priority_categories", on ? f.priority_categories.filter((k) => k !== c.key) : [...f.priority_categories, c.key])}
                      className={clsx("h-7 rounded-md border px-2.5 text-xs transition-colors", on ? "border-accent/40 bg-accent/10 text-accent" : "hairline text-muted hover:text-fg")}>
                      {c.label}
                    </button>
                  );
                })}
              </div>
            </Field>
          </div>
        </Section>

        <Section title="Aprovação e exportação">
          <div className="space-y-5 p-4">
            <Field label="Modo de aprovação">
              <Segmented value={f.approval_mode} onChange={(v) => set("approval_mode", v)} options={[{ value: "manual", label: "Manual (recomendado)" }, { value: "automatic", label: "Automática" }]} />
            </Field>
            {f.approval_mode === "automatic" ? (
              <Field label={`Aprovar automaticamente a partir de ${f.auto_approve_min_score} pontos`} hint="Cortes abaixo dessa nota continuam aguardando sua revisão.">
                <input type="range" className="w-full" min={50} max={100} value={f.auto_approve_min_score} onChange={(e) => set("auto_approve_min_score", Number(e.target.value))} />
              </Field>
            ) : (
              <p className="text-xs text-muted">Todos os cortes aguardam sua aprovação antes de serem considerados prontos para publicação.</p>
            )}
            <Field label="Qualidade de exportação">
              <Select value={f.export_quality} onChange={(v) => set("export_quality", v as Automation["export_quality"])}>
                <option value="standard">Padrão — H.264 CRF 23, arquivo menor</option>
                <option value="high">Alta — H.264 CRF 19 (recomendado)</option>
                <option value="max">Máxima — H.264 CRF 16, arquivo maior</option>
              </Select>
            </Field>
          </div>
        </Section>
      </div>
    </>
  );
}

function parseKw(s: string) {
  return s.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
}

function Row({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 sm:grid-cols-2">{children}</div>;
}

function Num({ label, value, min, max, onChange, hint }: { label: string; value: number; min: number; max: number; onChange: (v: number) => void; hint?: string }) {
  return (
    <Field label={label} hint={hint}>
      <input type="number" className="input font-mono" value={value} min={min} max={max} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  );
}
