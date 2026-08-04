import Link from "next/link";

/**
 * The shared footer. Deep purple closes every marketing page, so the eye
 * always knows it has reached the bottom of the document rather than a
 * section break.
 */
export function SiteFooter({ note }: { note?: string }) {
  return (
    <footer className="bg-plum-deep">
      <div className="grid-field py-14">
        <div className="col-span-4 md:col-span-6">
          <p className="text-body font-bold tracking-tight text-white">LUMO</p>
          <p className="mt-3 text-small text-white/55">
            Alto Motors, Velmora. Karva and Renzo are fictional brands.
          </p>
          <p className="mt-2 max-w-challenge text-caption text-white/40">
            {note ??
              "This is a demonstration platform. Vehicle prices, procedures and " +
                "policies are patterned on real UAE retail practice but are not " +
                "genuine commercial offers."}
          </p>
        </div>

        <div className="col-span-4 mt-8 flex flex-wrap gap-x-8 gap-y-3 md:col-span-4 md:col-start-9 md:mt-0 md:justify-end">
          {[
            { href: "/chat", label: "Talk to LUMO" },
            { href: "/workflow", label: "How it works" },
            { href: "/admin", label: "Operations" },
          ].map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-small text-white/60 transition-colors hover:text-brand"
            >
              {link.label}
            </Link>
          ))}
        </div>
      </div>
    </footer>
  );
}
