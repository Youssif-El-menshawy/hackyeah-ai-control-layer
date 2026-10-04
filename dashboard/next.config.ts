import type { NextConfig } from "next";

const backend = process.env.CONTROL_LAYER_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  turbopack: { root: process.cwd() },
  async rewrites() {
    return [{ source: "/control-api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
