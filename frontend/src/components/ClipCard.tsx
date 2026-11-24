import clsx from "clsx";
import { Film } from "lucide-react";
import type { Clip } from "../lib/api";
import { fmtDuration, fmtRelative } from "../lib/format";
import { Badge, CLIP_STATUS, RENDER_STATUS, ScoreBadge } from "./ui";

export function ClipCard({ clip, onOpen, compact }: { clip: Clip; onOpen: (c: Clip) => void; compact?: boolean }) {
  const st = CLIP_STATUS[clip.status];
  const rs = RENDER_STATUS[clip.render_status];
  return (
    <button
      onClick={() => onOpen(clip)}
      className="group card flex flex-col overflow-hidden text-left transition-[border-color,transform] duration-150 hover:-translate-y-px hover:border-line/[0.14] animate-fade-in"
    >
      <div className="relative w-full overflow-hidden bg-raised" style={{ aspectRatio: compact ? "4 / 5" : "9 / 14" }}>
        {clip.thumbnail_url ? (
          <img src={clip.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]" />
        ) : (
          <div className="flex h-full items-center justify-center text-faint">
            <Film size={20} />
          </div>
        )}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/70 to-transparent" />
        <div className="absolute right-2 top-2">
          <ScoreBadge score={clip.viral_score} tier={clip.tier} size="sm" />
        </div>
        <span className="absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 font-mono text-2xs tabular-nums text-white">{fmtDuration(clip.duration_s)}</span>
        {clip.render_status !== "none" && (
          <span className="absolute bottom-2 left-2">
            <Badge tone={rs.tone} className="bg-black/70">{rs.label}</Badge>
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <p className="line-clamp-2 text-[13px] font-medium leading-snug">{clip.title}</p>
        <p className="truncate text-xs text-muted">
          {clip.creator_name} · {clip.category_label}
        </p>
        <div className="mt-auto flex items-center justify-between gap-2 pt-1">
          <Badge tone={st.tone} dot>
            {st.label}
          </Badge>
          <span className={clsx("text-2xs text-faint")}>{fmtRelative(clip.discovered_at)}</span>
        </div>
      </div>
    </button>
  );
}

export function ClipCardSkeleton() {
  return (
    <div className="card overflow-hidden">
      <div className="skeleton rounded-none" style={{ aspectRatio: "9 / 14" }} />
      <div className="space-y-2 p-3">
        <div className="skeleton h-3.5 w-4/5" />
        <div className="skeleton h-3 w-1/2" />
      </div>
    </div>
  );
}
