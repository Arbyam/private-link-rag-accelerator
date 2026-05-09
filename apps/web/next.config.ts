import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    serverActions: {
      bodySizeLimit: "10mb",
    },
  },
  // Ensure trailing slashes are handled consistently
  trailingSlash: false,
  // Disable x-powered-by header for security
  poweredByHeader: false,
};

export default nextConfig;
