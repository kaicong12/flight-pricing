import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Docker image runs .next/standalone/server.js rather than `next start`, so node_modules
  // never ships. See docs/deploy.md.
  output: "standalone",
};

export default nextConfig;
