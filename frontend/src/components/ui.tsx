import clsx from "clsx";
import { X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="sticky top-0 z-20 flex min-h-14 flex-wrap items-center justify-between gap-3 border-b hairline bg-bg/85 px-6 py-3 backdrop-blur-md max-md:pl-14">
      <div className="min-w-0">
        <h1 className="truncate text-[15px] font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 truncate text-xs text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Section({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={clsx("card animate-fade-in", className)}>
      {(title || actions) && (
        <div className="flex h-11 items-center justify-between gap-2 border-b hairline px-4">
          <h2 className="text-[13px] font-medium">{title}</h2>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Badge({ children, tone = "neutral", className, dot }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" | "info" | "accent"; className?: string; dot?: boolean }) {
  const tones = {
    neutral: "bg-line/[0.06] text-muted",
    good: "bg-good/10 text-good",
    warn: "bg-warn/10 text-warn",
    bad: "bg-bad/10 text-bad",
    info: "bg-info/10 text-info",
    accent: "bg-accent/10 text-accent",
  };
  return (
    <span className={clsx("inline-flex h-5 items-center gap-1 whitespace-nowrap rounded px-1.5 text-2xs font-medium", tones[tone], className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function tierTone(tier: string) {
  return tier === "alto" ? "good" : tier === "medio" ? "warn" : "neutral";
}

export function ScoreBadge({ score, tier, size = "md" }: { score: number; tier: string; size?: "sm" | "md" | "lg" }) {
  const color = tier === "alto" ? "text-good" : tier === "medio" ? "text-warn" : "text-muted";
  const ring = tier === "alto" ? "border-good/30" : tier === "medio" ? "border-warn/30" : "border-line/10";
  const dims = size === "lg" ? "h-12 w-12 text-lg" : size === "sm" ? "h-7 w-7 text-2xs" : "h-9 w-9 text-[13px]";
  return (
    <div
      title="Pontuação viral estimada pela IA (0-100). É uma estimativa, não uma promessa."
      className={clsx("flex shrink-0 items-center justify-center rounded-full border bg-bg/80 font-mono font-semibold tabular-nums backdrop-blur", color, ring, dims)}
    >
      {score}
    </div>
  );
}

export const CLIP_STATUS: Record<string, { label: string; tone: "neutral" | "good" | "warn" | "bad" | "info" }> = {
  pending_review: { label: "Aguardando revisão", tone: "warn" },
  approved: { label: "Aprovado", tone: "good" },
  rejected: { label: "Rejeitado", tone: "bad" },
};

export const RENDER_STATUS: Record<string, { label: string; tone: "neutral" | "good" | "warn" | "bad" | "info" }> = {
  none: { label: "Não exportado", tone: "neutral" },
  queued: { label: "Na fila", tone: "info" },
  rendering: { label: "Renderizando", tone: "info" },
  done: { label: "Exportado", tone: "good" },
  failed: { label: "Falha na exportação", tone: "bad" },
};

export function ProgressBar({ value, className, tone = "accent" }: { value: number; className?: string; tone?: "accent" | "good" | "info" }) {
  const c = tone === "good" ? "bg-good" : tone === "info" ? "bg-info" : "bg-accent";
  return (
    <div className={clsx("h-1 w-full overflow-hidden rounded-full bg-line/[0.06]", className)}>
      <div className={clsx("h-full rounded-full transition-[width] duration-500", c)} style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
    </div>
  );
}

export function EmptyState({ icon, title, description, action }: { icon: ReactNode; title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg border hairline bg-raised text-muted">{icon}</div>
      <p className="text-[13px] font-medium">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs leading-relaxed text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, size = "md", full }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; size?: "sm" | "md"; full?: boolean }) {
  return (
    <div className={clsx("rounded-md border hairline bg-bg p-0.5", full ? "flex w-full [&>button]:flex-1" : "inline-flex")}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={clsx(
            "rounded-[5px] px-2.5 font-medium transition-colors",
            size === "sm" ? "h-6 text-2xs" : "h-7 text-xs",
            value === o.value ? "bg-raised text-fg shadow-[0_0_0_1px_rgb(255_255_255/0.06)]" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; description?: ReactNode; disabled?: boolean }) {
  return (
    <label className={clsx("flex cursor-pointer items-start gap-3", disabled && "pointer-events-none opacity-50")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={clsx("relative mt-0.5 h-[18px] w-8 shrink-0 rounded-full transition-colors", checked ? "bg-accent" : "bg-line/[0.12]")}
      >
        <span className={clsx("absolute left-0 top-[2px] h-[14px] w-[14px] rounded-full bg-white shadow transition-transform", checked ? "translate-x-[16px]" : "translate-x-[2px]")} />
      </button>
      {(label || description) && (
        <span className="min-w-0">
          {label && <span className="block text-[13px] font-medium">{label}</span>}
          {description && <span className="mt-0.5 block text-xs leading-relaxed text-muted">{description}</span>}
        </span>
      )}
    </label>
  );
}

export function Select({ value, onChange, children, className }: { value: string; onChange: (v: string) => void; children: ReactNode; className?: string }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={clsx("input cursor-pointer appearance-none bg-[length:12px] bg-[right_8px_center] bg-no-repeat pr-7", className)}
      style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238f949e' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }}>
      {children}
    </select>
  );
}

export function Modal({ open, onClose, title, children, footer, width = "max-w-lg" }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; width?: string }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[10vh] backdrop-blur-[2px] animate-fade-in" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={clsx("w-full rounded-xl border border-line/10 bg-panel shadow-2xl", width)}>
        <div className="flex h-12 items-center justify-between border-b hairline px-4">
          <h3 className="text-[13px] font-semibold">{title}</h3>
          <button onClick={onClose} className="btn-ghost btn-icon h-7 w-7" aria-label="Fechar">
            <X size={15} />
          </button>
        </div>
        <div className="p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t hairline px-4 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ open, onClose, children, width = "max-w-[980px]" }: { open: boolean; onClose: () => void; children: ReactNode; width?: string }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", h);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50 animate-fade-in" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={clsx("h-full w-full overflow-y-auto border-l border-line/10 bg-panel shadow-2xl animate-slide-in", width)}>{children}</div>
    </div>,
    document.body,
  );
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; tone: "good" | "bad" | "info"; text: string };
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const id = useRef(0);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const t = { id: ++id.current, tone, text };
    setItems((s) => [...s.slice(-3), t]);
    setTimeout(() => setItems((s) => s.filter((x) => x.id !== t.id)), tone === "bad" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[360px] max-w-[calc(100vw-32px)] flex-col gap-2">
          {items.map((t) => (
            <div key={t.id} className="pointer-events-auto flex items-start gap-2.5 rounded-lg border border-line/10 bg-raised px-3.5 py-2.5 text-[13px] shadow-xl animate-slide-in">
              <span className={clsx("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", t.tone === "good" ? "bg-good" : t.tone === "bad" ? "bg-bad" : "bg-info")} />
              <span className="leading-snug">{t.text}</span>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && <p className="mt-1 text-2xs leading-relaxed text-faint">{hint}</p>}
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "warn" | "accent" }) {
  return (
    <div className="card px-4 py-3.5">
      <p className="text-xs text-muted">{label}</p>
      <p className={clsx("mt-1.5 font-mono text-[22px] font-medium tabular-nums tracking-tight", tone === "good" && "text-good", tone === "warn" && "text-warn", tone === "accent" && "text-accent")}>{value}</p>
      {sub && <p className="mt-0.5 truncate text-2xs text-faint">{sub}</p>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="rounded-md border border-bad/20 bg-bad/[0.06] px-3 py-2 text-xs text-bad">{error instanceof Error ? error.message : String(error)}</div>;
}
