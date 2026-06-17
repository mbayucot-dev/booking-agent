"use client";

/** Last-resort boundary for errors in the root layout itself. It REPLACES the
 * layout, so it must render its own <html>/<body> and can't rely on app styles. */
export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          display: "flex",
          minHeight: "100vh",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
          margin: 0,
        }}
      >
        <div style={{ textAlign: "center" }}>
          <h2>Something went wrong</h2>
          <button onClick={reset} style={{ marginTop: 12, padding: "6px 14px", cursor: "pointer" }}>
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
