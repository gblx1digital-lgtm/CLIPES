import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Pencil, Plus, RefreshCw, ShieldCheck, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, EmptyState, ErrorBox, Field, Modal, PageHeader, Toggle, useToast } from "../components/ui";
import { api, type Creator } from "../lib/api";
import { fmtRelative } from "../lib/format";

// Criadores de referência do projeto. Só o nome é pré-preenchido: canais/handles devem ser
// confirmados por você (a verificação usa as APIs oficiais e falha se o canal não existir).
const SUGGESTED = ["Coringa", "Paulinho O Loko", "Davy Jones", "Alanzoka", "Lipão Gamer"];

type Form = {
  name: string;
  youtube_handle: string;
  twitch_login: string;
  drive_folder: string;
  active: boolean;
  media_authorized: boolean;
  authorization_note: string;
  notes: string;
};
const EMPTY: Form = { name: "", youtube_handle: "", twitch_login: "", drive_folder: "", active: true, media_authorized: false, authorization_note: "", notes: "" };

export default function CreatorsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<{ id?: number; form: Form } | null>(null);
  const { data: creators, error, isLoading } = useQuery({ queryKey: ["creators"], queryFn: () => api.get<Creator[]>("/api/creators"), refetchInterval: 10000 });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["creators"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
    void qc.invalidateQueries({ queryKey: ["jobs"] });
  };
  const check = useMutation({
    mutationFn: (id: number) => api.post(`/api/creators/${id}/check`),
    onSuccess: () => { refresh(); toast("info", "Verificação agendada. Acompanhe em Descoberta com IA."); },
    onError: (e: Error) => toast("bad", e.message),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/api/creators/${id}`),
    onSuccess: () => { refresh(); toast("good", "Criador excluído."); },
    onError: (e: Error) => toast("bad", e.message),
  });
  const toggleActive = useMutation({
    mutationFn: (c: Creator) => api.patch(`/api/creators/${c.id}`, { active: !c.active }),
    onSuccess: refresh,
    onError: (e: Error) => toast("bad", e.message),
  });

  const existing = new Set((creators ?? []).map((c) => c.name.toLowerCase()));
  const missing = SUGGESTED.filter((n) => !existing.has(n.toLowerCase()));

  return (
    <>
      <PageHeader
        title="Criadores"
        description="Canais monitorados e registro de autorização de uso"
        actions={<button className="btn-primary" onClick={() => setEditing({ form: EMPTY })}><Plus size={14} /> Adicionar criador</button>}
      />
      <div className="space-y-4 p-6">
        <ErrorBox error={error} />
        {missing.length > 0 && (
          <div className="card flex flex-wrap items-center gap-2 px-4 py-3">
            <span className="mr-1 text-xs text-muted">Sugeridos:</span>
            {missing.map((n) => (
              <button key={n} className="btn-secondary btn-sm" onClick={() => setEditing({ form: { ...EMPTY, name: n } })}>
                <Plus size={12} /> {n}
              </button>
            ))}
            <span className="w-full text-2xs text-faint sm:ml-auto sm:w-auto">Confirme o @ do YouTube e o login da Twitch de cada um ao adicionar.</span>
          </div>
        )}

        <div className="card overflow-hidden">
          {isLoading ? (
            <div className="space-y-2 p-4">{Array.from({ length: 3 }).map((_, i) => <div key={i} className="skeleton h-12" />)}</div>
          ) : !creators?.length ? (
            <EmptyState icon={<Users size={16} />} title="Nenhum criador cadastrado" description="Adicione criadores de GTA 6 para monitorar novos vídeos e organizar os cortes por canal." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-xs">
                <thead className="border-b hairline text-faint">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Criador</th>
                    <th className="px-4 py-2.5 font-medium">Canais</th>
                    <th className="px-4 py-2.5 font-medium">Autorização</th>
                    <th className="px-4 py-2.5 text-right font-medium">Vídeos</th>
                    <th className="px-4 py-2.5 text-right font-medium">Cortes</th>
                    <th className="px-4 py-2.5 text-right font-medium">Média</th>
                    <th className="px-4 py-2.5 font-medium">Monitoramento</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/[0.06]">
                  {creators.map((c) => (
                    <tr key={c.id} className={clsx("transition-colors hover:bg-hover/30", !c.active && "opacity-55")}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-raised text-2xs font-semibold text-muted">{c.name.slice(0, 2).toUpperCase()}</div>
                          <div>
                            <p className="flex items-center gap-2 text-[13px] font-medium">
                              {c.name}
                              {c.live_now && <LiveBadge url={c.live_url} title={c.live_title} />}
                            </p>
                            {c.default_layout?.cam && <p className="text-2xs text-faint">Layout de webcam salvo</p>}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-muted">
                        <div className="space-y-0.5">
                          {c.youtube_handle || c.youtube_channel_id ? <p>YouTube {c.youtube_handle ?? c.youtube_channel_id}</p> : null}
                          {c.twitch_login ? <p>Twitch {c.twitch_login}</p> : null}
                          {c.drive_folder_url ? <p><a href={c.drive_folder_url} target="_blank" rel="noreferrer" className="hover:text-fg">Pasta do Drive</a></p> : null}
                          {!c.youtube_handle && !c.youtube_channel_id && !c.twitch_login && !c.drive_folder_url && <p className="text-faint">Sem canal</p>}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {c.media_authorized ? (
                          <span title={c.authorization_note ?? ""}><Badge tone="good"><ShieldCheck size={11} /> Autorizado</Badge></span>
                        ) : (
                          <Badge>Sem autorização</Badge>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums">{c.stats.videos ?? 0}</td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums">
                        {c.stats.clips ? <Link className="hover:text-accent" to={`/clipes?creator=${c.id}`}>{c.stats.clips}</Link> : 0}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums text-muted">{c.stats.clips ? c.stats.avg_score : "—"}</td>
                      <td className="px-4 py-3">
                        <p className={clsx(c.last_check_error ? "text-warn" : "text-muted")} title={c.last_check_error ?? ""}>
                          {c.last_checked_at ? `Verificado ${fmtRelative(c.last_checked_at)}` : "Nunca verificado"}
                        </p>
                        {c.last_check_error && <p className="max-w-[220px] truncate text-2xs text-warn/80">{c.last_check_error}</p>}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <button className="btn-ghost btn-icon h-7 w-7" title="Verificar novos vídeos agora" disabled={!c.active} onClick={() => check.mutate(c.id)}><RefreshCw size={13} /></button>
                          <button className="btn-ghost btn-icon h-7 w-7" title="Editar" onClick={() => setEditing({ id: c.id, form: { name: c.name, youtube_handle: c.youtube_handle ?? c.youtube_channel_id ?? "", twitch_login: c.twitch_login ?? "", drive_folder: c.drive_folder_url ?? "", active: c.active, media_authorized: c.media_authorized, authorization_note: c.authorization_note ?? "", notes: c.notes ?? "" } })}><Pencil size={13} /></button>
                          <button className="btn-ghost btn-sm" onClick={() => toggleActive.mutate(c)}>{c.active ? "Pausar" : "Ativar"}</button>
                          <button className="btn-ghost btn-icon h-7 w-7 hover:text-bad" title="Excluir" onClick={() => confirm(`Excluir ${c.name}?`) && remove.mutate(c.id)}><Trash2 size={13} /></button>
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
      {editing && <CreatorModal id={editing.id} initial={editing.form} onClose={() => setEditing(null)} onSaved={refresh} />}
    </>
  );
}

function CreatorModal({ id, initial, onClose, onSaved }: { id?: number; initial: Form; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState<Form>(initial);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((s) => ({ ...s, [k]: v }));
  const save = useMutation({
    mutationFn: () => {
      const yt = f.youtube_handle.trim();
      const body = {
        name: f.name,
        youtube_handle: yt && !(yt.startsWith("UC") && yt.length === 24) ? yt : null,
        youtube_channel_id: yt.startsWith("UC") && yt.length === 24 ? yt : null,
        twitch_login: f.twitch_login,
        drive_folder: f.drive_folder,
        active: f.active,
        media_authorized: f.media_authorized,
        authorization_note: f.authorization_note,
        notes: f.notes,
      };
      return id ? api.patch(`/api/creators/${id}`, body) : api.post("/api/creators", body);
    },
    onSuccess: () => { onSaved(); toast("good", id ? "Criador atualizado." : "Criador adicionado."); onClose(); },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={id ? "Editar criador" : "Adicionar criador"}
      footer={<><button className="btn-ghost" onClick={onClose}>Cancelar</button><button className="btn-primary" disabled={!f.name.trim() || save.isPending} onClick={() => save.mutate()}>Salvar</button></>}
    >
      <div className="space-y-4">
        <Field label="Nome"><input className="input" value={f.name} onChange={(e) => set("name", e.target.value)} autoFocus /></Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="YouTube" hint="@handle ou ID do canal (UC…)"><input className="input" value={f.youtube_handle} onChange={(e) => set("youtube_handle", e.target.value)} placeholder="@canal" /></Field>
          <Field label="Twitch" hint="Login do canal (twitch.tv/login)"><input className="input" value={f.twitch_login} onChange={(e) => set("twitch_login", e.target.value)} placeholder="login" /></Field>
        </div>
        <Field label="Pasta do Google Drive (opcional)" hint="Link da pasta compartilhada (“Qualquer pessoa com o link”). Todo vídeo novo colocado nela é baixado e analisado sozinho. Exige o criador marcado como autorizado.">
          <input className="input" value={f.drive_folder} onChange={(e) => set("drive_folder", e.target.value)} placeholder="https://drive.google.com/drive/folders/…" />
        </Field>
        <div className="space-y-3 rounded-lg border hairline p-3">
          <Toggle
            checked={f.media_authorized}
            onChange={(v) => set("media_authorized", v)}
            label="Criador autorizou o uso de conteúdo para cortes"
            description="Necessário para processar mídias marcadas como “autorizadas”. Guarde o registro (contrato, e-mail, programa de cortes)."
          />
          {f.media_authorized && (
            <Field label="Registro da autorização"><input className="input" value={f.authorization_note} onChange={(e) => set("authorization_note", e.target.value)} placeholder="Ex.: programa oficial de cortes, e-mail de 10/11/2026" /></Field>
          )}
        </div>
        <Toggle checked={f.active} onChange={(v) => set("active", v)} label="Monitoramento ativo" description="Inclui este criador nas verificações automáticas de novos vídeos." />
        <Field label="Observações"><textarea className="input h-16 py-2" value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
        {save.error && <ErrorBox error={save.error} />}
      </div>
    </Modal>
  );
}

export function LiveBadge({ url, title }: { url: string | null; title: string | null }) {
  const body = (
    <span className="inline-flex h-5 items-center gap-1 rounded bg-bad/15 px-1.5 text-2xs font-semibold text-bad" title={title ?? "Ao vivo"}>
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-bad opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-bad" />
      </span>
      AO VIVO
    </span>
  );
  return url ? <a href={url} target="_blank" rel="noreferrer">{body}</a> : body;
}
