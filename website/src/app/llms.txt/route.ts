import { llms } from "fumadocs-core/source";
import { basePath } from "@/lib/shared";
import { source } from "@/lib/source";

export const revalidate = false;

export function GET() {
  // The index links every page by its app-internal URL, which knows nothing
  // of Next's basePath. Whoever reads llms.txt follows those links from
  // outside the app, so they get the full path here.
  const index = llms(source).index().replaceAll("](/", `](${basePath}/`);

  return new Response(index);
}
