import { Callout } from "fumadocs-ui/components/callout";
import { Card, Cards } from "fumadocs-ui/components/card";
import {
  ImageZoom,
  type ImageZoomProps,
} from "fumadocs-ui/components/image-zoom";
import { Step, Steps } from "fumadocs-ui/components/steps";
import { Tab, Tabs } from "fumadocs-ui/components/tabs";
import defaultMdxComponents from "fumadocs-ui/mdx";
import type { MDXComponents } from "mdx/types";

// Registered globally rather than imported per page: a page that has to
// remember an import is a page somebody will write without one, and the build
// only says so at export time.
export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    // A screenshot embedded as ordinary Markdown becomes zoomable too, since
    // every <img> routes through ImageZoom. The cast is needed because MDX
    // types `img` as a plain <img>, while ImageZoom takes the wider set of
    // props next/image accepts.
    img: (props) => <ImageZoom {...(props as ImageZoomProps)} />,
    Callout,
    Card,
    Cards,
    Step,
    Steps,
    Tab,
    Tabs,
    ...components,
  } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
