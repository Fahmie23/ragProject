import type { WorkspaceTab } from "../../app/workspace";

export function DocumentWorkflowNav({
  tab,
  extractionReady,
  structureReady,
  reviewReady,
  reviewDone,
  chunkingAvailable,
  chunkingDone,
  indexAvailable,
  indexDone,
  onChange,
}: {
  tab: WorkspaceTab;
  extractionReady: boolean;
  structureReady: boolean;
  reviewReady: boolean;
  reviewDone: boolean;
  chunkingAvailable: boolean;
  chunkingDone: boolean;
  indexAvailable: boolean;
  indexDone: boolean;
  onChange: (tab: WorkspaceTab) => void;
}) {
  const items: Array<{
    id: WorkspaceTab;
    label: string;
    enabled: boolean;
    done: boolean;
  }> = [
    { id: "overview", label: "Overview", enabled: true, done: true },
    { id: "extraction", label: "Content", enabled: extractionReady, done: extractionReady },
    { id: "structure", label: "Structure", enabled: structureReady, done: structureReady },
    { id: "review", label: "Review", enabled: reviewReady, done: reviewDone },
    { id: "chunking", label: "Knowledge", enabled: chunkingAvailable, done: chunkingDone },
    { id: "index", label: "Search Index", enabled: indexAvailable, done: indexDone },
  ];

  return (
    <nav className="v2-workflow-nav" aria-label="Document workflow">
      {items.map((item) => {
        const active = item.id === tab;
        return (
          <button
            key={item.id}
            type="button"
            disabled={!item.enabled}
            className={`${active ? "active" : ""} ${item.done ? "done" : ""}`}
            onClick={() => onChange(item.id)}
            title={item.id === "chunking" && !item.enabled
              ? "Complete document structure review before preparing knowledge."
              : item.id === "index" && !item.enabled
                ? "Prepare knowledge chunks before opening the search index."
                : undefined}
          >
            <span className="v2-workflow-state" aria-hidden="true">{item.done ? "✓" : active ? "●" : "○"}</span>
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
