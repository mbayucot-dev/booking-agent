// Visual presentation for each node status: a lucide icon + a Badge variant +
// Tailwind classes for the canvas node. The human-readable label still comes
// from STATUS_STYLES (nodeStatus.ts) so it stays the single source of truth.

import {
  CheckCircle2,
  Circle,
  CircleDashed,
  Clock,
  Loader2,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import type { NodeStatus } from "./nodeStatus";

type BadgeVariant = "default" | "success" | "destructive" | "warning" | "muted";

export interface StatusPresentation {
  Icon: LucideIcon;
  /** Badge variant used in the event log. */
  badge: BadgeVariant;
  /** Tailwind classes for the canvas node card (border + bg + text). */
  node: string;
  /** Spin/pulse the icon while the step is active. */
  spin?: boolean;
  pulse?: boolean;
}

export const STATUS_PRESENTATION: Record<NodeStatus, StatusPresentation> = {
  idle: {
    Icon: Circle,
    badge: "muted",
    node: "border-border bg-card text-muted-foreground",
  },
  running: {
    Icon: Loader2,
    badge: "default",
    node: "border-primary bg-accent text-primary shadow-md ring-2 ring-primary/30",
    spin: true,
    pulse: true,
  },
  success: {
    Icon: CheckCircle2,
    badge: "success",
    node: "border-success/60 bg-success/5 text-success",
  },
  failed: {
    Icon: XCircle,
    badge: "destructive",
    node: "border-destructive/60 bg-destructive/5 text-destructive",
  },
  waiting_approval: {
    Icon: Clock,
    badge: "warning",
    node: "border-warning bg-warning/10 text-warning-foreground",
    pulse: true,
  },
  approved: {
    Icon: CheckCircle2,
    badge: "success",
    node: "border-success/60 bg-card text-success",
  },
  rejected: {
    Icon: XCircle,
    badge: "destructive",
    node: "border-destructive/60 bg-card text-destructive",
  },
  skipped: {
    Icon: CircleDashed,
    badge: "muted",
    node: "border-dashed border-border bg-card text-muted-foreground",
  },
};
