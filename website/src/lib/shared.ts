export const appName = "video-tldr";
export const docsRoute = "/docs";
export const docsImageRoute = "/og/docs";
export const docsContentRoute = "/llms.mdx/docs";

export const gitConfig = {
  user: "corgan2222",
  repo: "video-tldr",
  branch: "main",
};

// GitHub Pages serves a project site under /<repo>. next.config.mjs carries
// the same value as `basePath`. Sharing it would mean an .mts config loaded
// through Node's TypeScript stripping, more machinery than one string is
// worth, so the two are kept by hand.
export const basePath = `/${gitConfig.repo}`;

// The store listings, empty until each one is live. Google's branding
// terms require the badge to link to a page that exists and to come down
// whenever the extension does not — so the badge renders only when the
// address beside it is filled in. Mozilla asks the same in kind.
export const storeLinks = {
  firefox: "",
  chrome: "",
};
export const siteUrl = `https://${gitConfig.user}.github.io${basePath}`;
