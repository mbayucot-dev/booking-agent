"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  AtSign,
  Calendar,
  Check,
  Clock,
  Hourglass,
  Loader2,
  User,
  UserCheck,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import type { ApprovalCard } from "@/lib/types";

export interface ApprovalDrawerProps {
  card: ApprovalCard;
  onApprove: (by?: string) => void;
  onReject: (reason?: string) => void;
  pending?: boolean;
}

const FIELDS: ReadonlyArray<[keyof ApprovalCard, string, LucideIcon]> = [
  ["customer", "Customer", User],
  ["service", "Service", Wrench],
  ["date", "Date", Calendar],
  ["time", "Time", Clock],
  ["staff", "Staff", UserCheck],
  ["email", "Email", AtSign],
];

const schema = z.object({ reason: z.string() });
type RejectForm = z.infer<typeof schema>;

/**
 * Card shown when a run is paused awaiting human approval. Renders the approval
 * card fields + the prepared actions, with Approve / Reject (RHF + zod for the
 * rejection reason).
 */
export function ApprovalDrawer({ card, onApprove, onReject, pending }: ApprovalDrawerProps) {
  const form = useForm<RejectForm>({
    resolver: zodResolver(schema),
    defaultValues: { reason: "" },
  });

  const submitReject = form.handleSubmit(({ reason }) => {
    onReject(reason.trim() || undefined);
  });

  return (
    <Card
      role="dialog"
      aria-label="Approval required"
      data-testid="approval-drawer"
      className="border-warning/50 bg-warning/5"
    >
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-warning-foreground">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-warning/15">
            <Hourglass className="h-4 w-4 animate-pulse" aria-hidden="true" />
          </span>
          Approval required
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          {FIELDS.map(([key, label, Icon]) => (
            <div key={key} className="contents">
              <dt className="flex items-center gap-1.5 font-medium text-muted-foreground">
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                {label}
              </dt>
              <dd className="font-medium text-foreground" data-testid={`approval-${key}`}>
                {(card[key] as string | null) ?? "—"}
              </dd>
            </div>
          ))}
        </dl>

        <Separator />

        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Prepared actions
          </h3>
          {card.prepared_actions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No prepared actions.</p>
          ) : (
            <ul className="space-y-1.5" data-testid="prepared-actions">
              {card.prepared_actions.map((a, i) => (
                <li
                  key={i}
                  className="rounded-md border bg-card px-3 py-2 text-sm"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{a.action}</span>
                    <Badge variant="muted">action</Badge>
                  </div>
                  <code className="mt-1 block whitespace-pre-wrap break-all text-[11px] text-muted-foreground">
                    {JSON.stringify(a.payload)}
                  </code>
                </li>
              ))}
            </ul>
          )}
        </div>

        <Separator />

        <Form {...form}>
          <form onSubmit={submitReject} className="space-y-3">
            <FormField
              control={form.control}
              name="reason"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-muted-foreground">Rejection reason</FormLabel>
                  <FormControl>
                    <Input placeholder="Optional — only used when rejecting" {...field} />
                  </FormControl>
                </FormItem>
              )}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                variant="success"
                className="flex-1"
                onClick={() => onApprove()}
                disabled={pending}
              >
                {pending ? (
                  <Loader2 className="animate-spin" aria-hidden="true" />
                ) : (
                  <Check aria-hidden="true" />
                )}
                Approve
              </Button>
              <Button
                type="submit"
                variant="destructive"
                className="flex-1"
                disabled={pending}
              >
                {pending ? (
                  <Loader2 className="animate-spin" aria-hidden="true" />
                ) : (
                  <X aria-hidden="true" />
                )}
                Reject
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}
