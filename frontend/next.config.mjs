import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig = {
  output: "standalone",
  turbopack: {
    root: projectRoot,
  },
  async rewrites() {
    const internalApiBaseUrl =
      process.env.INTERNAL_API_BASE_URL ?? "http://localhost:8000";

    return [
      {
        source: "/api/:path*",
        destination: `${internalApiBaseUrl}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${internalApiBaseUrl}/health`,
      },
    ];
  },
};

export default nextConfig;
