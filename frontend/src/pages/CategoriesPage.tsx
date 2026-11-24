import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bug, Car, Eye, FolderKanban, Laugh, Lightbulb, Map, Newspaper, Shapes, Sparkles, Star } from "lucide-react";
import { Link } from "react-router-dom";
import { ErrorBox, PageHeader, useToast } from "../components/ui";
import { api, type Automation, type Category } from "../lib/api";

const ICONS: Record<string, typeof Laugh> = {
  engracados: Laugh,
  curiosidades: Lightbulb,
  missoes: Map,
  bugs: Bug,
  reacoes: Sparkles,
  perseguicoes: Car,
  segredos: Eye,
  epicos: Star,
  noticias: Newspaper,
  outros: Shapes,
};

export default function CategoriesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error, isLoading } = useQuery({ queryKey: ["categories"], queryFn: () => api.get<Category[]>("/api/categories") });
  const togglePriority = useMutation({
    mutationFn: async (key: string) => {
      const auto = await api.get<Automation>("/api/automation");
      const set = new Set(auto.priority_categories);
      if (set.has(key)) set.delete(key);
      else set.add(key);
      return api.put<Automation>("/api/automation", { priority_categories: [...set] });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["categories"] });
      void qc.invalidateQueries({ queryKey: ["automation"] });
      toast("good", "Categorias prioritárias atualizadas.");
    },
    onError: (e: Error) => toast("bad", e.message),
  });
  const total = data?.reduce((s, c) => s + c.count, 0) ?? 0;

  return (
    <>
      <PageHeader title="Categorias" description="Classificação automática feita pela IA · categorias prioritárias ganham preferência na seleção" />
      <div className="space-y-4 p-6">
        <ErrorBox error={error} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {isLoading
            ? Array.from({ length: 10 }).map((_, i) => <div key={i} className="skeleton h-[132px]" />)
            : data?.map((c) => {
                const Icon = ICONS[c.key] ?? FolderKanban;
                const share = total ? (c.count / total) * 100 : 0;
                return (
                  <div key={c.key} className="card group flex flex-col p-4 transition-colors hover:border-line/[0.14]">
                    <div className="flex items-start justify-between">
                      <div className="flex h-8 w-8 items-center justify-center rounded-md border hairline bg-raised text-muted group-hover:text-fg">
                        <Icon size={15} strokeWidth={1.75} />
                      </div>
                      <button
                        onClick={() => togglePriority.mutate(c.key)}
                        className={clsx("rounded px-1.5 py-0.5 text-2xs font-medium transition-colors", c.priority ? "bg-accent/10 text-accent" : "text-faint hover:bg-hover hover:text-muted")}
                        title="Categorias prioritárias recebem preferência quando há limite de cortes por vídeo/dia"
                      >
                        {c.priority ? "Prioritária" : "Priorizar"}
                      </button>
                    </div>
                    <Link to={`/clipes?category=${c.key}`} className="mt-3 block">
                      <p className="text-[13px] font-medium">{c.label}</p>
                      <p className="mt-1 font-mono text-xl tabular-nums">{c.count}</p>
                      <div className="mt-2 h-1 rounded-full bg-line/[0.06]">
                        <div className="h-full rounded-full bg-fg/40" style={{ width: `${share}%` }} />
                      </div>
                      <p className="mt-2 text-2xs text-faint">
                        {c.count ? <>média {c.avg_score} · {c.high_count} alto potencial · {c.approved} aprovados</> : "Nenhum corte ainda"}
                      </p>
                    </Link>
                  </div>
                );
              })}
        </div>
      </div>
    </>
  );
}
