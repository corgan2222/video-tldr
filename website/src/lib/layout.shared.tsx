import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";
import { appName, basePath, gitConfig } from "./shared";

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      // The mark, not the word. `img` rather than next/image: this is a
      // fixed 20px logo in the header, so there is nothing to optimise,
      // and basePath has to be prefixed by hand either way.
      title: (
        <span className="inline-flex items-center gap-2">
          <img
            src={`${basePath}/logo.svg`}
            alt={appName}
            width={20}
            height={20}
          />
          <span className="font-semibold">{appName}</span>
        </span>
      ),
    },
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
    // The site has one theme. A switch that cannot switch anything is a
    // control that lies.
    themeSwitch: { enabled: false },
  };
}
