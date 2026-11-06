import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/format";

/**
 * HookLens brand assets from the official kit (src/app/assest), served from /public/brand.
 *
 * - hooklens-logo-dark.svg: the "Primary signature / dark" lockup (magenta symbol, white
 *   wordmark), cropped to its paths. Used wherever the full logo appears on dark surfaces.
 * - hooklens-symbol.svg: the magenta symbol. Used where space is tight (mobile header, loaders).
 * - hooklens-app-icon.svg: favicon / app icon (src/app/icon.svg, apple-icon.png, favicon.ico).
 *
 * Aspect ratios are fixed to the source viewBoxes; never stretch or recolour these files.
 */
const LOGO_RATIO = 421.84 / 92;

export function BrandLogo({ height = 26, className, priority }: { height?: number; className?: string; priority?: boolean }) {
  return (
    <Image
      src="/brand/hooklens-logo-dark.svg"
      alt="HookLens"
      width={Math.round(height * LOGO_RATIO)}
      height={height}
      priority={priority}
      unoptimized
      className={cn("select-none", className)}
    />
  );
}

export function BrandMark({ size = 24, className, decorative }: { size?: number; className?: string; decorative?: boolean }) {
  return (
    <Image
      src="/brand/hooklens-symbol.svg"
      alt={decorative ? "" : "HookLens"}
      width={size}
      height={size}
      loading="eager"
      unoptimized
      className={cn("select-none", className)}
    />
  );
}

/** Logo linking home, with the clear space the kit asks for (≥ ¼ of the symbol height). */
export function BrandHomeLink({ height = 26, className }: { height?: number; className?: string }) {
  return (
    <Link href="/" aria-label="HookLens home" className={cn("inline-flex items-center rounded-md p-1.5", className)}>
      <BrandLogo height={height} priority />
    </Link>
  );
}
