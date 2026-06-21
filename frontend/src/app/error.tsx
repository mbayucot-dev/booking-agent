"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";

// `reset` re-renders the segment from scratch without a full page reload.
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Dashboard error boundary:", error);
  }, [error]);

  return (
    <div
      role="alert"
      className="flex h-screen flex-col items-center justify-center gap-4 p-6 text-center"
    >
      <AlertTriangle className="h-10 w-10 text-destructive" aria-hidden="true" />
      <div>
        <h2 className="text-lg font-semibold">Something went wrong</h2>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          The dashboard hit an unexpected error. Your data is safe on the server.
        </p>
      </div>
      <Button variant="outline" onClick={reset}>
        <RotateCcw aria-hidden="true" />
        Try again
      </Button>
    </div>
  );
}
