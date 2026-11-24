import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Clapperboard,
  Download,
  FolderKanban,
  LayoutDashboard,
  Menu,
  Radar,
  Scissors,
  Settings,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { api, type Dashboard } from "../lib/api";
import { fmtRelative } from "../lib/format";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/clipes", label: "Central de Clipes", icon: Clapperboard, badge: "pending" as const },
  { to: "/descoberta", label: "Descoberta com IA", icon: Radar, badge: "jobs" as const },
  { to: "/criadores", label: "Criadores", icon: Users },
  { to: "/categorias", label: "Categorias", icon: FolderKanban },
  { to: "/editor", label: "Editor", icon: Scissors },
  { to: "/exportacoes", label: "Exportações", icon: Download },
  { to: "/automacoes", label: "Automações", icon: Workflow },
  { to: "/configuracoes", label: "Configurações", icon: Settings },
];

export function useDashboard() {
  return useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/api/dashboard"), refetchInterval: 5000 });
}

export function AppShell({ children }: { children: ReactNode }) {
  const { data } = useDashboard();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);

  const worker = data?.processing.worker;
  const busy = (data?.processing.running ?? 0) + (data?.processing.queued ?? 0);

  return (
    <div className="flex min-h-full">
      <button className="btn-ghost btn-icon fixed left-3 top-3 z-30 md:hidden" onClick={() => setOpen(true)} aria-label="Abrir menu">
        <Menu size={16} />
      </button>
      {open && <div className="fixed inset-0 z-30 bg-black/60 md:hidden" onClick={() => setOpen(false)} />}
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-40 flex w-[232px] flex-col border-r hairline bg-panel transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 items-center gap-2.5 px-4">
          <Logo />
          <div className="leading-tight">
            <p className="text-[13px] font-semibold tracking-tight">Clipes</p>
            <p className="text-2xs text-faint">Central de cortes · GTA 6</p>
          </div>
          <button className="btn-ghost btn-icon ml-auto h-7 w-7 md:hidden" onClick={() => setOpen(false)} aria-label="Fechar menu">
            <X size={15} />
          </button>
        </div>
        <nav className="flex-1 space-y-px overflow-y-auto px-2 py-2">
          {NAV.map(({ to, label, icon: Icon, end, badge }) => {
            const count = badge === "pending" ? data?.stats.clips_pending : badge === "jobs" ? busy : undefined;
            return (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx(
                    "group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors",
                    isActive ? "bg-hover text-fg" : "text-muted hover:bg-hover/60 hover:text-fg",
                  )
                }
              >
                <Icon size={15} strokeWidth={1.75} className="shrink-0" />
                <span className="truncate">{label}</span>
                {!!count && (
                  <span className={clsx("ml-auto rounded px-1.5 font-mono text-2xs tabular-nums", badge === "jobs" ? "bg-info/10 text-info" : "bg-line/[0.07] text-muted")}>
                    {count}
                  </span>
                )}
              </NavLink>
            );
          })}
        </nav>
        <div className="border-t hairline p-3">
          <div className="flex items-center gap-2 rounded-md px-1.5 py-1 text-2xs">
            <span className={clsx("relative flex h-2 w-2")}>
              {worker?.online && busy > 0 && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-good opacity-50" />}
              <span className={clsx("relative inline-flex h-2 w-2 rounded-full", worker?.online ? "bg-good" : "bg-faint")} />
            </span>
            <span className="text-muted">
              {worker === undefined ? "Conectando…" : worker.online ? (busy ? `Processando · ${busy} na fila` : "Worker ativo") : "Worker offline"}
            </span>
          </div>
          {worker && !worker.online && (
            <p className="mt-1 px-1.5 text-2xs leading-relaxed text-faint">
              {worker.last_seen ? `Visto ${fmtRelative(worker.last_seen)}. ` : ""}Inicie com <span className="kbd">make worker</span>
            </p>
          )}
        </div>
      </aside>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="rgb(var(--raised))" stroke="rgb(255 255 255 / 0.08)" />
      <rect x="11" y="6" width="10" height="20" rx="2.5" fill="none" stroke="rgb(var(--accent))" strokeWidth="2" />
      <path d="M14.5 13.2v5.6l4.6-2.8z" fill="rgb(var(--accent))" />
    </svg>
  );
}
