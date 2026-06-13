import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig = {
  output: "standalone",
  turbopack: {
    root: projectRoot,
  },
};

export default nextConfig;
