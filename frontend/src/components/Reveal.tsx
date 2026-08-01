"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Reveals content as it enters the viewport.
 *
 * Motion here is structural, not decorative: elements settle *into* the grid
 * rather than travelling across it. Anything more would fight the calm the
 * Swiss layout is working to establish.
 *
 * Honours prefers-reduced-motion via CSS, and renders visible immediately if
 * IntersectionObserver is unavailable — the content must never depend on the
 * animation to be readable.
 */
export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      // Fire slightly before the element is fully in view, so the motion has
      // finished by the time the reader's eye arrives.
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={`reveal ${className}`}
      data-visible={visible}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}
