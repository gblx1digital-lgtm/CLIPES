import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Clapperboard, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ClipCard, ClipCardSkeleton } from "../components/ClipCard";
import { ClipViewer } from "../components/ClipViewer";
import { EmptyState, ErrorBox, PageHeader, Segmented, Select } from "../components/ui";
import { api, CATEGORY_OPTIONS, qs, type Clip, type Creator } from "../lib/api";

const PAGE_SIZE = 24;

const DURATIONS: Record<string, [number | null, number | null]> = {
  "": [null, null],
  short: [null, 20],
  medium: [20, 45],
  long: [45, null],
};
const PERIODS: Record<string, number | null> = { "": null, "1": 1, "7": 7, "30": 30 };

export default function ClipsPage() {
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!("page" in patch)) next.delete("page");
    setParams(next, { replace: true });
  };

  const [search, setSearch] = useState(get("q"));
  useEffect(() => {
    const t = setTimeout(() => search !== get("q") && set({ q: search || null }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const page = Number(get("page") || 1);
  const [dMin, dMax] = DURATIONS[get("duration")] ?? [null, null];
  const days = PERIODS[get("period")] ?? null;
  const tierParam = get("tier");
  const query = useMemo(
    () =>
      qs({
        q: get("q"),
        creator_id: get("creator"),
        category: get("category"),
        status: get("status"),
        tier: tierParam,
        min_duration: dMin,
        max_duration: dMax,
        date_from: days ? new Date(Date.now() - days * 86400000).toISOString() : null,
        sort: get("sort") || "score",
        page,
        page_size: PAGE_SIZE,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [params.toString()],
  );

  const { data, error, isLoading, isFetching } = useQuery({
    queryKey: ["clips", query],
    queryFn: () => api.get<{ items: Clip[]; total: number }>(`/api/clips${query}`),
    placeholderData: keepPreviousData,
    refetchInterval: 10000,
  });
  const { data: creators } = useQuery({ queryKey: ["creators"], queryFn: () => api.get<Creator[]>("/api/creators") });

  const openId = get("open") ? Number(get("open")) : null;
  const hasFilters = ["q", "creator", "category", "status", "tier", "duration", "period"].some((k) => get(k));
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <PageHeader
        title="Central de Clipes"
        description={data ? `${data.total} ${data.total === 1 ? "corte" : "cortes"} · ordenados por ${get("sort") === "recent" ? "data de descoberta" : get("sort") === "duration" ? "duração" : "potencial viral"}` : "Cortes encontrados pela IA"}
        actions={
          <Segmented
            value={(get("status") || "all") as string}
            onChange={(v) => set({ status: v === "all" ? null : v })}
            options={[
              { value: "all", label: "Todos" },
              { value: "pending_review", label: "Revisão" },
              { value: "approved", label: "Aprovados" },
              { value: "rejected", label: "Rejeitados" },
            ]}
          />
        }
      />
      <div className="space-y-4 p-6">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:w-64">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
            <input className="input pl-8" placeholder="Buscar por título ou resumo" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Select className="w-full sm:w-auto sm:min-w-[150px]" value={get("creator")} onChange={(v) => set({ creator: v })}>
            <option value="">Todos os criadores</option>
            {creators?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          <Select className="w-full sm:w-auto sm:min-w-[160px]" value={get("category")} onChange={(v) => set({ category: v })}>
            <option value="">Todas as categorias</option>
            {CATEGORY_OPTIONS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </Select>
          <Select className="w-full sm:w-auto sm:min-w-[150px]" value={tierParam} onChange={(v) => set({ tier: v })}>
            <option value="">Todo potencial</option>
            <option value="alto">Alto potencial</option>
            <option value="medio">Potencial médio</option>
            <option value="baixo">Baixo potencial</option>
          </Select>
          <Select className="w-full sm:w-auto sm:min-w-[150px]" value={get("duration")} onChange={(v) => set({ duration: v })}>
            <option value="">Qualquer duração</option>
            <option value="short">Até 20s</option>
            <option value="medium">20s a 45s</option>
            <option value="long">Mais de 45s</option>
          </Select>
          <Select className="w-full sm:w-auto sm:min-w-[150px]" value={get("period")} onChange={(v) => set({ period: v })}>
            <option value="">Qualquer data</option>
            <option value="1">Últimas 24h</option>
            <option value="7">Últimos 7 dias</option>
            <option value="30">Últimos 30 dias</option>
          </Select>
          <Select className="w-full sm:w-auto sm:min-w-[160px]" value={get("sort") || "score"} onChange={(v) => set({ sort: v === "score" ? null : v })}>
            <option value="score">Maior potencial viral</option>
            <option value="recent">Mais recentes</option>
            <option value="duration">Mais curtos</option>
          </Select>
          {hasFilters && (
            <button className="btn-ghost btn-sm" onClick={() => { setSearch(""); setParams(new URLSearchParams(), { replace: true }); }}>
              <X size={13} /> Limpar filtros
            </button>
          )}
          {isFetching && !isLoading && <span className="text-2xs text-faint">Atualizando…</span>}
        </div>

        <ErrorBox error={error} />

        {isLoading ? (
          <Grid>{Array.from({ length: 12 }).map((_, i) => <ClipCardSkeleton key={i} />)}</Grid>
        ) : data && data.items.length === 0 ? (
          <div className="card">
            {hasFilters ? (
              <EmptyState icon={<SlidersHorizontal size={16} />} title="Nenhum corte com esses filtros" description="Ajuste ou limpe os filtros para ver mais resultados." />
            ) : (
              <EmptyState
                icon={<Clapperboard size={16} />}
                title="Nenhum corte encontrado ainda"
                description="Envie uma mídia autorizada em Descoberta com IA. A IA analisa o vídeo, encontra os melhores momentos e eles aparecem aqui para sua revisão."
                action={<a href="/descoberta" className="btn-secondary">Ir para Descoberta com IA</a>}
              />
            )}
          </div>
        ) : (
          <Grid>{data?.items.map((c) => <ClipCard key={c.id} clip={c} onOpen={(x) => set({ open: String(x.id), page: params.get("page") })} />)}</Grid>
        )}

        {data && pages > 1 && (
          <div className="flex items-center justify-center gap-2 pt-2">
            <button className="btn-secondary btn-sm" disabled={page <= 1} onClick={() => set({ page: String(page - 1) })}>Anterior</button>
            <span className="text-xs text-muted">Página {page} de {pages}</span>
            <button className="btn-secondary btn-sm" disabled={page >= pages} onClick={() => set({ page: String(page + 1) })}>Próxima</button>
          </div>
        )}
      </div>
      <ClipViewer clipId={openId} onClose={() => set({ open: null, page: params.get("page") })} />
    </>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-7">{children}</div>;
}
