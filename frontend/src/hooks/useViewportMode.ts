import { useEffect, useState } from "react";

export type ViewportMode = "large" | "desktop" | "compact" | "mobile";

function resolveViewportMode(width: number): ViewportMode {
  if (width >= 1440) return "large";
  if (width >= 1180) return "desktop";
  if (width >= 768) return "compact";
  return "mobile";
}

export function useViewportMode(): ViewportMode {
  const [mode, setMode] = useState<ViewportMode>(() => {
    if (typeof window === "undefined") return "large";
    return resolveViewportMode(window.innerWidth);
  });

  useEffect(() => {
    if (typeof window === "undefined") return undefined;

    let frame = 0;
    const update = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        setMode((current) => {
          const next = resolveViewportMode(window.innerWidth);
          return current === next ? current : next;
        });
      });
    };

    window.addEventListener("resize", update, { passive: true });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", update);
    };
  }, []);

  return mode;
}
