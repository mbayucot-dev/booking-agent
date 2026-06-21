"use client";

import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Hourglass,
  Loader2,
  MessageSquarePlus,
  RotateCcw,
  Sparkles,
  TriangleAlert,
  WifiOff,
  Workflow,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApprovalDrawer } from "@/components/ApprovalDrawer";
import { ChatBox } from "@/components/ChatBox";
import { NodeDetailPanel } from "@/components/NodeDetailPanel";
import { RunEventLog } from "@/components/RunEventLog";
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { NodeName } from "@/flow/nodeNames";
import { isNodeStatus, type NodeStatus } from "@/flow/nodeStatus";
import { NODE_LABELS } from "@/flow/workflowDefinition";
import { useApproval } from "@/hooks/useApproval";
import { useRetry } from "@/hooks/useRetry";
import { useRun } from "@/hooks/useRun";
import { useRunNodes } from "@/hooks/useRunNodes";
import { useRunStream } from "@/hooks/useRunStream";
import { useStartRun } from "@/hooks/useStartRun";
import { ApiError } from "@/lib/api";
import type { RunStatus } from "@/lib/types";

/** Map an API failure to a friendly, actionable message (auth / rate-limit / generic). */
function friendlyError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Not authorized — check the API token.";
    if (err.code === "rate_limited") return "Too many requests — please slow down a moment.";
  }
  return err instanceof Error ? err.message : "Something went wrong. Please try again.";
}

// The React Flow canvas is heavy and client-only — load it on demand so it stays
// out of the initial bundle and isn't server-rendered.
const WorkflowCanvas = dynamic(
  () => import("@/components/WorkflowCanvas").then((m) => m.WorkflowCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <Skeleton className="h-64 w-11/12" />
      </div>
    ),
  },
);

type BadgeVariant = "default" | "success" | "destructive" | "warning" | "muted";

const RUN_STATUS: Record<RunStatus, { label: string; Icon: LucideIcon; variant: BadgeVariant; spin?: boolean }> = {
  running: { label: "Running", Icon: Loader2, variant: "default", spin: true },
  paused: { label: "Awaiting approval", Icon: Hourglass, variant: "warning" },
  completed: { label: "Completed", Icon: CheckCircle2, variant: "success" },
  failed: { label: "Failed", Icon: XCircle, variant: "destructive" },
  escalated: { label: "Escalated", Icon: TriangleAlert, variant: "warning" },
};

function RunStatusBadge({ status }: { status: RunStatus }) {
  const { label, Icon, variant, spin } = RUN_STATUS[status];
  return (
    <Badge variant={variant} className="px-2.5 py-1 text-xs">
      <Icon className={spin ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} aria-hidden="true" />
      {label}
    </Badge>
  );
}

export default function Page() {
  const queryClient = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);
  // Bumped after approve/reject/retry to reopen the SSE stream so the next
  // execution phase animates live (the stream closes at each run boundary).
  const [streamEpoch, setStreamEpoch] = useState(0);
  // Node open in the preview panel (clicked on the canvas).
  const [selectedNode, setSelectedNode] = useState<NodeName | null>(null);
  // Bumped to remount ChatBox (resetting RHF state) on "Start over".
  const [chatKey, setChatKey] = useState(0);

  const startRun = useStartRun((run) => setRunId(run.run_id));
  const runQuery = useRun(runId);
  const { approve, reject } = useApproval(runId);
  const retry = useRetry(runId);
  const nodesQuery = useRunNodes(runId, selectedNode !== null);
  const { statuses: streamStatuses, events, error: streamError } = useRunStream(
    runId,
    () => {
      runQuery.refetch();
      // Refresh per-node detail so an open preview panel reflects new output.
      queryClient.invalidateQueries({ queryKey: ["run", runId, "nodes"] });
    },
    streamEpoch,
  );

  const reopenStream = useCallback(() => {
    setStreamEpoch((e) => e + 1);
    // Refresh per-node detail immediately, not only when the stream ends.
    queryClient.invalidateQueries({ queryKey: ["run", runId, "nodes"] });
  }, [queryClient, runId]);

  // Stable identity so the panel's keydown effect subscribes once, not per render.
  const closePanel = useCallback(() => setSelectedNode(null), []);

  // Close the preview panel when the active run resets (avoids stale detail).
  useEffect(() => {
    if (!runId) setSelectedNode(null);
  }, [runId]);

  const run = runQuery.data;

  // True once a run reaches a terminal state — shows the "Start over" action.
  const isTerminal =
    run?.status === "completed" ||
    run?.status === "escalated" ||
    run?.status === "failed";

  const handleStartOver = () => {
    setRunId(null);
    startRun.reset();
    setStreamEpoch(0);
    setSelectedNode(null);
    setChatKey((k) => k + 1);
  };

  // Merge backend node_statuses (authoritative on refetch) with the live
  // stream statuses (real-time during execution).
  const mergedStatuses = useMemo<Record<string, NodeStatus>>(() => {
    const out: Record<string, NodeStatus> = {};
    for (const [node, status] of Object.entries(run?.node_statuses ?? {})) {
      if (isNodeStatus(status)) out[node] = status;
    }
    return { ...out, ...streamStatuses };
  }, [run?.node_statuses, streamStatuses]);

  const isPaused = run?.status === "paused";
  const approvalPending = approve.isPending || reject.isPending;

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b bg-card/80 px-6 py-3 backdrop-blur">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Bot className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <h1 className="flex items-center gap-1.5 text-base font-semibold leading-tight">
              AI Booking Workflow
              <Sparkles className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
            </h1>
            <p className="text-xs text-muted-foreground">
              One message → a multi-agent booking, with a human approval gate.
            </p>
          </div>
        </div>
        <span aria-live="polite">{run && <RunStatusBadge status={run.status} />}</span>
      </header>

      {/* Body */}
      <main className="grid flex-1 grid-cols-1 gap-4 overflow-hidden p-4 lg:grid-cols-[minmax(340px,420px)_1fr]">
        {/* Control panel */}
        <section className="flex flex-col gap-4 overflow-y-auto pr-1">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <MessageSquarePlus className="h-4 w-4 text-primary" aria-hidden="true" />
                  New booking
                </CardTitle>
                {isTerminal && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1.5 px-2 text-xs"
                    onClick={handleStartOver}
                  >
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                    Start over
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <ChatBox
                key={chatKey}
                onSubmit={(message) => startRun.mutate(message)}
                pending={startRun.isPending}
              />
              {startRun.isError && (
                <p
                  role="alert"
                  className="mt-3 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive"
                >
                  <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {friendlyError(startRun.error)}
                </p>
              )}
            </CardContent>
          </Card>

          {run && (
            <p className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
              Run
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                {run.run_id.slice(0, 8)}
              </code>
            </p>
          )}

          {/* Live SSE failed mid-run: surface it and offer a manual reconnect
              (the snapshot stays authoritative; the canvas just stopped animating). */}
          {streamError && (run?.status === "running" || run?.status === "paused") && (
            <p
              role="alert"
              className="flex items-center justify-between gap-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-sm text-warning"
            >
              <span className="flex items-center gap-2">
                <WifiOff className="h-4 w-4 shrink-0" aria-hidden="true" />
                Live updates disconnected — showing last known state.
              </span>
              <Button
                variant="outline"
                className="h-7 px-2 text-xs"
                onClick={reopenStream}
              >
                Reconnect
              </Button>
            </p>
          )}

          {isPaused && run?.approval_card && (
            <div className="space-y-2">
              <ApprovalDrawer
                card={run.approval_card}
                onApprove={() => approve.mutate(undefined, { onSuccess: reopenStream })}
                onReject={(reason) => reject.mutate(reason, { onSuccess: reopenStream })}
                pending={approvalPending}
              />
              {(approve.isError || reject.isError) && (
                <p
                  role="alert"
                  className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive"
                >
                  <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {friendlyError(approve.error ?? reject.error)}
                </p>
              )}
            </div>
          )}

          {run?.status === "failed" && (
            <Card className="border-destructive/40 bg-destructive/5">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-sm text-destructive">
                  <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                  Run failed
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <p>
                  A step errored mid-run. Retrying resumes from the last checkpoint —
                  already-booked steps are not repeated.
                </p>
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={() => retry.mutate(undefined, { onSuccess: reopenStream })}
                  disabled={retry.isPending}
                >
                  {retry.isPending ? (
                    <Loader2 className="animate-spin" aria-hidden="true" />
                  ) : (
                    <RotateCcw aria-hidden="true" />
                  )}
                  Retry run
                </Button>
                {retry.isError && (
                  <p role="alert" className="flex items-center gap-2 text-destructive">
                    <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
                    {friendlyError(retry.error)}
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {run?.final_response && run.status !== "failed" && (
            // Style the outcome by status: only a genuine completion gets the
            // green "success" treatment; an escalation gets a warning card (it is
            // NOT a successful booking).
            <Card
              className={
                run.status === "completed"
                  ? "border-success/40 bg-success/5"
                  : "border-warning/40 bg-warning/5"
              }
            >
              <CardHeader className="pb-2">
                <CardTitle
                  className={`flex items-center gap-2 text-sm ${
                    run.status === "completed" ? "text-success" : "text-warning"
                  }`}
                >
                  {run.status === "completed" ? (
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <TriangleAlert className="h-4 w-4" aria-hidden="true" />
                  )}
                  {run.status === "escalated" ? "Escalated to our team" : "Final response"}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-foreground">{run.final_response}</CardContent>
            </Card>
          )}

          <Card>
            <CardContent className="pt-5">
              <RunEventLog events={events} />
            </CardContent>
          </Card>
        </section>

        {/* Canvas */}
        <section className="relative overflow-hidden rounded-xl border bg-card shadow-sm">
          <div className="flex items-center gap-2 border-b px-4 py-2.5">
            <Workflow className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-sm font-semibold">Agent graph</h2>
            <span className="text-xs text-muted-foreground">
              live execution · click a node for details
            </span>
          </div>
          <div className="h-[calc(100%-44px)]">
            <WorkflowCanvas
              statuses={mergedStatuses}
              selectedNode={selectedNode}
              onNodeSelect={setSelectedNode}
              onClear={closePanel}
            />
          </div>

          {selectedNode && (
            <NodeDetailPanel
              label={NODE_LABELS[selectedNode]}
              status={mergedStatuses[selectedNode]}
              detail={nodesQuery.data?.find((d) => d.node === selectedNode)}
              loading={nodesQuery.isLoading}
              error={nodesQuery.isError}
              showRetry={run?.status === "failed"}
              retryPending={retry.isPending}
              onRetry={() => retry.mutate(undefined, { onSuccess: reopenStream })}
              onClose={closePanel}
            />
          )}
        </section>
      </main>
    </div>
  );
}
