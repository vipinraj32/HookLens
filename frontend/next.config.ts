import type { NextConfig } from "next";

// The browser talks to the API through this same-origin rewrite, so the anonymous
// workspace cookie (hl_ws) is first-party and no CORS credentials are needed.
// HOOKLENS_API_URL is read on the server only; it is never sent to the browser.
const apiUrl = (process.env.HOOKLENS_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  // Proxied SSE (job progress) must not be buffered by response compression.
  compress: false,
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiUrl}/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
