import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Film, Play, RotateCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, EmptyState, ErrorBox, Modal, PageHeader, ProgressBar, Segmented, useToast } from "../components/ui";
import { api, type ExportItem } from "../lib/api";
import { fmtBytes, fmtDateTime, fmtTimecode } from "../lib/format";

const STATUS: Record<string, { label: string; tone: "good" | "bad" | "info" | "neutral" }> = {
  queued: { label: "Na fila", tone: "neutral" },
  rendering: { label: "Renderizando", tone: "info" },
  done: { label: "Pronto", tone: "good" },
  failed: { label: "Falhou", tone: "bad" },
};
const QUALITY: Record<string, string> = { standard: "Padrão", high: "Alta", max: "Máxima" };

export default function ExportsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<"all" | "done" | "active" | "failed">("all");
  const [playing, setPlaying] = useState<ExportItem | null>(null);
  const status = filter === "all" ? "" : filter === "active" ? "?status=queued,rendering" : `?status=${filter}`;
  const { data, error, isLoading } = useQuery({
    queryKey: ["exports", filter],
    queryFn: () => api.get<ExportItem[]>(`/api/exports${status}`),
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === "queued" || e.status === "rendering") ? 1500 : 10000),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["exports"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
    void qc.invalidateQueries({ queryKey: ["clip"] });
  };
  const remove = useMutation({ mutationFn: (id: number) => api.del(`/api/exports/${id}`), onSuccess: () => { refresh(); toast("good", "Exportação excluída."); }, onError: (e: Error) => toast("bad", e.message) });
  const retry = useMutation({ mutationFn: (jobId: number) => api.post(`/api/jobs/${jobId}/retry`), onSuccess: () => { refresh(); toast("info", "Renderização reenviada para a fila."); }, onError: (e: Error) => toast("bad", e.message) });
  const totalSize = data?.reduce((s, e) => s + (e.size_bytes ?? 0), 0) ?? 0;

  return (
    <>
      <PageHeader
        title="Exportações"
        description={data ? `${data.filter((e) => e.status === "done").length} arquivos prontos · ${fmtBytes(totalSize)}` : "Vídeos MP4 1080×1920 prontos para publicação"}
        actions={<Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: "Todas" }, { value: "done", label: "Prontas" }, { value: "active", label: "Em andamento" }, { value: "failed", label: "Falhas" }]} />}
      />
      <div className="p-6">
        <ErrorBox error={error} />
        <div className="card overflow-hidden">
          {isLoading ? (
            <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="skeleton h-12" />)}</div>
          ) : !data?.length ? (
            <EmptyState icon={<Film size={16} />} title="Nenhuma exportação" description="Aprove um corte e clique em Exportar MP4 na Central de Clipes ou no Editor." action={<Link to="/clipes?status=approved" className="btn-secondary">Ver cortes aprovados</Link>} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-xs">
                <thead className="border-b hairline text-faint">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Corte</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    <th className="px-4 py-2.5 font-medium">Formato</th>
                    <th className="px-4 py-2.5 text-right font-medium">Duração</th>
                    <th className="px-4 py-2.5 text-right font-medium">Tamanho</th>
                    <th className="px-4 py-2.5 font-medium">Criado</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/[0.06]">
                  {data.map((e) => (
                    <tr key={e.id} className="hover:bg-hover/30">
                      <td className="max-w-[320px] px-4 py-3">
                        <Link to={`/clipes?open=${e.clip_id}`} className="block truncate text-[13px] font-medium hover:text-accent">{e.clip_title}</Link>
                        <p className="truncate text-faint">{e.creator_name}</p>
                      </td>
                      <td className="w-48 px-4 py-3">
                        <Badge tone={STATUS[e.status].tone} dot>{STATUS[e.status].label}</Badge>
                        {(e.status === "rendering" || e.status === "queued") && (
                          <div className="mt-1.5 space-y-1">
                            <ProgressBar value={e.progress ?? 0} tone="info" />
                            <p className="truncate text-2xs text-faint">{e.job_message}</p>
                          </div>
                        )}
                        {e.status === "failed" && e.error && <p className="mt-1 max-w-[200px] truncate text-2xs text-bad" title={e.error}>{e.error.split("\n")[0]}</p>}
                      </td>
                      <td className="px-4 py-3 text-muted">{e.width}×{e.height} · {QUALITY[e.quality] ?? e.quality}</td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums text-muted">{fmtTimecode(e.duration_s)}</td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums text-muted">{fmtBytes(e.size_bytes)}</td>
                      <td className="px-4 py-3 text-muted">{fmtDateTime(e.created_at)}</td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          {e.file_url && <button className="btn-ghost btn-icon h-7 w-7" title="Assistir" onClick={() => setPlaying(e)}><Play size={13} /></button>}
                          {e.download_url && <a className="btn-secondary btn-sm" href={e.download_url}><Download size={12} /> MP4</a>}
                          {e.status === "failed" && e.job_id && <button className="btn-ghost btn-icon h-7 w-7" title="Tentar novamente" onClick={() => retry.mutate(e.job_id!)}><RotateCw size={13} /></button>}
                          {(e.status === "done" || e.status === "failed") && (
                            <button className="btn-ghost btn-icon h-7 w-7 hover:text-bad" title="Excluir arquivo" onClick={() => confirm("Excluir este arquivo exportado?") && remove.mutate(e.id)}><Trash2 size={13} /></button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      <Modal open={!!playing} onClose={() => setPlaying(null)} title={playing?.clip_title ?? ""} width="max-w-sm">
        {playing?.file_url && (
          <div className="overflow-hidden rounded-md bg-black" style={{ aspectRatio: "9/16" }}>
            <video src={playing.file_url} controls autoPlay playsInline className="h-full w-full" />
          </div>
        )}
      </Modal>
    </>
  );
}
