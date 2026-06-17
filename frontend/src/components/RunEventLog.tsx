"use client";

import { STATUS_STYLES } from "@/flow/nodeStatus";
import { STATUS_PRESENTATION } from "@/flow/statusPresentation";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { RunEvent } from "@/hooks/useRunStream";

export interface RunEventLogProps {
  events: RunEvent[];
}

/** Chronological list of run_events received over the SSE stream. */
export function RunEventLog({ events }: RunEventLogProps) {
  return (
    <div data-testid="run-event-log" className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Event log
      </h3>
      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground">No events yet.</p>
      ) : (
        <ul className="space-y-1">
          {events.map((e, i) => {
            const label = STATUS_STYLES[e.status].label;
            const { Icon, badge, spin } = STATUS_PRESENTATION[e.status];
            return (
              <li
                key={i}
                data-testid="run-event"
                className="flex items-center justify-between gap-2 rounded-md border bg-card px-3 py-1.5 text-sm"
              >
                <span className="truncate font-mono text-[13px] font-medium">{e.node}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {e.duration_ms != null && (
                    <span className="text-[11px] tabular-nums text-muted-foreground">
                      {e.duration_ms}ms
                    </span>
                  )}
                  <Badge variant={badge}>
                    <Icon className={cn("h-3 w-3", spin && "animate-spin")} aria-hidden="true" />
                    {label}
                  </Badge>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
