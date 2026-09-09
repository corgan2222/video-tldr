export const appName = "corganshelper";
export const docsRoute = "/docs";
export const docsImageRoute = "/og/docs";
export const docsContentRoute = "/llms.mdx/docs";

export const gitConfig = {
  user: "corgan2222",
  repo: "corganshelper",
  branch: "main",
};

// GitHub Pages serves a project site under /<repo>. next.config.mjs carries
// the same value as `basePath`. Sharing it would mean an .mts config loaded
// through Node's TypeScript stripping, more machinery than one string is
// worth, so the two are kept by hand.
export const basePath = `/${gitConfig.repo}`;
export const siteUrl = `https://${gitConfig.user}.github.io${basePath}`;
