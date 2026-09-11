import Image from "next/image";
import Link from "next/link";
import { appName, basePath, gitConfig, storeLinks } from "@/lib/shared";

// What the extension does, in the order someone new needs it: what comes
// out, where it lands, which model writes it, and what the window shows
// while it runs. The same four points carry README.md; a visitor who
// reads both should not find two different products.
const points = [
  {
    title: "A summary you can read",
    body: "The service fetches title, description, chapters and captions, transcribes the audio when there are none, and has a language model sort and summarise it. Still frames come from the moments worth seeing.",
  },
  {
    title: "Where you keep things",
    body: "Markdown, a note in an Obsidian vault with the video embedded, PDF and Word. Timestamps link back into the video.",
  },
  {
    title: "Your machine, your model",
    body: "The service runs locally. The Claude Code CLI, the Anthropic or OpenAI API, or LM Studio and Ollama, which never send a word off the machine.",
  },
  {
    title: "Fast or Thorough",
    body: "The toolbar icon offers Fast and Thorough. The window shows every step, the seconds it took and an estimate from your earlier runs.",
  },
];

export default function HomePage() {
  return (
    <main className="hero-wash flex flex-1 flex-col items-center px-4 py-20">
      {/* The banner carries the name and the tagline, so the page does
          not say them again — see docs/design-system.md. */}
      <Image
        src={`${basePath}/banner.png`}
        alt={`${appName} — Watch it. Vault it.`}
        width={2560}
        height={640}
        priority
        className="w-full max-w-3xl rounded-xl border border-fd-border"
      />
      <p className="mt-6 max-w-2xl text-balance text-center text-lg text-fd-muted-foreground">
        Too long to read? A Firefox and Chrome extension with a local service
        that turns the YouTube video in the active tab into a summary with
        pictures.
      </p>

      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/docs/getting-started"
          className="rounded-xl bg-fd-primary px-6 py-3 font-medium text-white transition-opacity hover:opacity-90"
        >
          Install it
        </Link>
        <Link
          href="/docs"
          className="rounded-xl border border-fd-border px-6 py-3 font-medium transition-colors hover:bg-fd-accent"
        >
          Read the documentation
        </Link>
        <a
          href={`https://github.com/${gitConfig.user}/${gitConfig.repo}`}
          className="rounded-xl border border-fd-border px-6 py-3 font-medium transition-colors hover:bg-fd-accent"
        >
          Source on GitHub
        </a>
      </div>

      {(storeLinks.firefox || storeLinks.chrome) && (
        <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
          {storeLinks.firefox && (
            <a href={storeLinks.firefox}>
              <Image
                src={`${basePath}/badges/firefox-get-the-addon.png`}
                alt="Get the add-on for Firefox"
                width={172}
                height={60}
                unoptimized
              />
            </a>
          )}
          {storeLinks.chrome && (
            <a href={storeLinks.chrome}>
              <Image
                src={`${basePath}/badges/chrome-web-store.png`}
                alt="Available in the Chrome Web Store"
                width={170}
                height={48}
                unoptimized
              />
            </a>
          )}
        </div>
      )}

      <p className="mt-4 text-sm text-fd-muted-foreground">
        <Link href="/docs/de" className="underline underline-offset-4">
          Auf Deutsch lesen
        </Link>
      </p>

      <div className="mt-16 grid w-full max-w-4xl gap-6 sm:grid-cols-2">
        {points.map((point) => (
          <div
            key={point.title}
            className="rounded-xl border border-fd-border p-5"
          >
            <h2 className="font-semibold">{point.title}</h2>
            <p className="mt-2 text-sm text-fd-muted-foreground">
              {point.body}
            </p>
          </div>
        ))}
      </div>

      <p className="mt-16 max-w-2xl text-balance text-center text-sm text-fd-muted-foreground">
        Free software under the MIT licence. The extension needs a companion
        service on your machine; it installs with one command, and the extension
        shows that command when it cannot find it.
      </p>
    </main>
  );
}
