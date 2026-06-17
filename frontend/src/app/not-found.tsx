import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 text-center">
      <h2 className="text-lg font-semibold">Page not found</h2>
      <Link href="/" className="text-sm text-primary underline">
        Back to the dashboard
      </Link>
    </div>
  );
}
