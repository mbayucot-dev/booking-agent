/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== "production";

// All app traffic is same-origin (the BFF proxy keeps the API + SSE same-origin),
// so connect-src 'self' suffices. 'unsafe-inline' covers Next's hydration bootstrap
// and Tailwind; 'unsafe-eval' + ws: are dev-only (React Refresh / HMR). Tighten to
// per-request nonces if a stricter policy is required.
const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "img-src 'self' data:",
  "font-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  `connect-src 'self'${isDev ? " ws:" : ""}`,
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-XSS-Protection", value: "0" }, // rely on CSP, not the legacy auditor
];

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false, // don't advertise the framework
  output: "standalone", // lean, self-contained server bundle for Docker
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
