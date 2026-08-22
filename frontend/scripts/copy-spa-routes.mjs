import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const dist = resolve(process.cwd(), "dist");
const index = resolve(dist, "index.html");

for (const route of ["queue", "model", "cases"]) {
  const target = resolve(dist, route, "index.html");
  await mkdir(resolve(dist, route), { recursive: true });
  await copyFile(index, target);
}
