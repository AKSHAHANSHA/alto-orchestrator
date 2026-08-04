import Link from "next/link";
import { LumoMark } from "@/components/Lumo";

/**
 * One masthead for every page.
 *
 * Previously each route hand-rolled its own, which is why the landing page,
 * the chat and the operations view had drifted into three slightly different
 * headers. The wordmark, the nav rhythm and the sticky blur now live in one
 * place; pages supply their own links and an optional trailing slot.
 */

export interface HeaderLink {
  href: string;
  label: string;
  /** Renders as the amber call to action instead of a plain nav link. */
  cta?: boolean;
}

export function SiteHeader({
  links = [],
  eyebrow,
  right,
}: {
  links?: HeaderLink[];
  /** Appended after the wordmark, e.g. "Operations". */
  eyebrow?: string;
  right?: React.ReactNode;
}) {
  return (
    <header className="sticky top-0 z-50 border-b border-rule/80 bg-canvas/80 backdrop-blur-md">
      <div className="grid-field h-[68px] items-center">
        <Link
          href="/"
          className="col-span-2 flex items-center gap-2.5 md:col-span-4"
        >
          <LumoMark size={30} />
          <span className="text-body font-bold tracking-tight text-plum">
            LUMO
          </span>
          {eyebrow && (
            <span className="hidden text-caption text-ink-faint sm:inline">
              · {eyebrow}
            </span>
          )}
        </Link>

        <nav className="col-span-2 flex items-center justify-end gap-2 md:col-span-8 md:gap-5">
          {right}
          {links.map((link) =>
            link.cta ? (
              <Link key={link.href} href={link.href} className="btn-primary">
                {link.label}
              </Link>
            ) : (
              <Link
                key={link.href}
                href={link.href}
                className="hidden rounded-full px-3 py-1.5 text-small text-ink-muted transition-colors hover:bg-plum/[0.06] hover:text-plum sm:block"
              >
                {link.label}
              </Link>
            ),
          )}
        </nav>
      </div>
    </header>
  );
}
