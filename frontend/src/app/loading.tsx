import { Skeleton } from "@/components/ui/skeleton";

/** Route-level Suspense fallback shown while the segment loads. */
export default function Loading() {
  return (
    <div className="flex h-screen items-center justify-center">
      <Skeleton className="h-8 w-56" />
    </div>
  );
}
