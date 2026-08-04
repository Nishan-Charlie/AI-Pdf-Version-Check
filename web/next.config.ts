import type { NextConfig } from "next";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  // The dashboard calls /api/* on its own origin; Next forwards those to the
  // Python service. One origin in the browser means no CORS preflight on
  // uploads and no API URL baked into the client bundle.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default config;
