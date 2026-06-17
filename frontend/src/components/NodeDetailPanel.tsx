"use client";

import { useEffect } from "react";
import { Loader2, RotateCcw, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { STATUS_STYLES, type NodeStatus } from "@/flow/nodeStatus";
import { STATUS_PRESENTATION } from "@/flow/statusPresentation";
import { cn } from "@/lib/utils";
import type { NodeDetail } from "@/lib/types";

export interface NodeDetailPanelProps {
  label: string;
  status?: NodeStatus;
  detail?: NodeDetail;
  loading?: boolean;
  error?: boolean;
  showRetry?: boolean;
  retryPending?: boolean;
  onRetry?: () => void;
  onClose: () => void;
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-mono text-sm tabular-nums">{value}</span>
    </div>
  );
}

/** n8n-style node-detail view: the clicked step's status + the output it
 * contributed to state, with run-level retry when it failed. */
export function NodeDetailPanel({
  label,
  status,
  detail,
  loading,
  error,
  showRetry,
  retryPending,
  onRetry,
  onClose,
}: NodeDetailPanelProps) {
  const effective = (status ?? detail?.status ?? "idle") as NodeStatus;
  const { Icon, badge, spin } = STATUS_PRESENTATION[effective];

  // Escape closes the panel (keyboard parity with the close button / pane click).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      data-testid="node-detail-panel"
      role="complementary"
      aria-labelledby="node-detail-title"
      className="absolute inset-y-0 right-0 z-10 flex w-[360px] max-w-[80%] flex-col border-l bg-card shadow-xl"
    >
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <div className="min-w-0">
          <h3 id="node-detail-title" className="truncate text-sm font-semibold">
            {label}
          </h3>
          <Badge variant={badge} className="mt-1">
            <Icon className={cn("h-3 w-3", spin && "animate-spin")} aria-hidden="true" />
            {STATUS_STYLES[effective].label}
          </Badge>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close panel">
          <X aria-hidden="true" />
        </Button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {(detail?.duration_ms != null || detail?.tokens != null || detail?.cost_usd != null) && (
          <div className="grid grid-cols-3 gap-3">
            <Meta label="Duration" value={detail.duration_ms != null ? `${detail.duration_ms}ms` : "—"} />
            <Meta label="Tokens" value={detail.tokens != null ? String(detail.tokens) : "—"} />
            <Meta
              label="Cost"
              value={detail.cost_usd != null ? `$${detail.cost_usd.toFixed(4)}` : "—"}
            />
          </div>
        )}

        <Separator />

        <div className="space-y-2">
          <h4 id="node-output-title" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Output
          </h4>
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : error ? (
            <p role="alert" className="text-sm text-destructive">
              Failed to load output. Try again.
            </p>
          ) : detail?.output ? (
            <pre
              aria-labelledby="node-output-title"
              className="max-h-[50vh] overflow-auto rounded-md border bg-muted/40 p-3 text-[11px] leading-relaxed"
            >
              {JSON.stringify(detail.output, null, 2)}
            </pre>
          ) : effective === "running" || effective === "waiting_approval" ? (
            <p className="text-sm text-muted-foreground">Executing…</p>
          ) : (
            <p className="text-sm text-muted-foreground">
              This step hasn&apos;t produced output yet.
            </p>
          )}
        </div>

        {showRetry && (
          <>
            <Separator />
            <Button
              variant="outline"
              className="w-full"
              onClick={onRetry}
              disabled={retryPending}
            >
              {retryPending ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <RotateCcw aria-hidden="true" />
              )}
              Retry from last checkpoint
            </Button>
          </>
        )}
      </div>
    </aside>
  );
}
