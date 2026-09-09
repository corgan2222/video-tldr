import Link from 'next/link';
import { appName } from '@/lib/shared';

export default function HomePage() {
  return (
    <main className="hero-wash flex flex-1 flex-col items-center justify-center gap-8 px-4 py-24 text-center">
      <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-6xl">
        {appName}
      </h1>
      <p className="max-w-xl text-balance text-lg text-fd-muted-foreground">
        A Manifest V3 browser extension for Firefox and Chrome.
      </p>
      <Link
        href="/docs"
        className="rounded-xl bg-fd-primary px-6 py-3 font-medium text-white transition-opacity hover:opacity-90"
      >
        Read the documentation
      </Link>
    </main>
  );
}
