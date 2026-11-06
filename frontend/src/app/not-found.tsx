import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center px-6 text-center">
      <div>
        <p className="font-mono text-sm text-accent">404</p>
        <h1 className="mt-2 text-xl font-semibold">Page not found</h1>
        <Link href="/app" className="mt-4 inline-block text-sm text-accent hover:underline">
          Go to the dashboard
        </Link>
      </div>
    </main>
  );
}
