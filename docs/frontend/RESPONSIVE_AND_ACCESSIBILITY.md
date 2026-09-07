# Responsive and Accessibility Contract

## Purpose

The final UI audit focuses on robustness and accessibility without changing RAG behavior.

## Responsive priorities

On smaller screens, preserve in this order:

1. current document/question context;
2. primary action/result;
3. source/provenance access;
4. advanced diagnostic controls.

Dense inspection panes may stack/collapse rather than forcing desktop-width layouts into a mobile viewport.

## Review workspace

- PDF zoom/navigation remains usable without stealing main-page scroll ownership.
- Current-page structure is preferred in the correction context; the full document tree is available in the broader Structure workspace.
- Sticky document chrome is scoped below the global application header.
- Page-number input and selected correction state must not clear each other through blur/race behavior.

## Drawers

Citation and benchmark drawers:

- move focus to their close control when opened;
- close on Escape;
- restore focus to the invoking control;
- stay inside the viewport on compact/mobile layouts.

## Async state

- Switching documents clears document-specific stale state before new artifacts load.
- Stale asynchronous completions are ignored.
- Benchmark/detail requests are aborted/replaced when a newer selection wins.
- Document-library API failure is distinct from a genuinely empty library and exposes retry.

## Keyboard/navigation semantics

- Active global navigation exposes `aria-current=page`.
- Upload remains keyboard accessible even when the native file control is visually hidden.
- Focus-visible styling is maintained for interactive elements.

## Validation matrix

The final UI was exercised across large desktop, standard desktop, compact laptop/tablet and mobile-size layouts, with regression checks for Review selection, document switching, drawers, API retry states and source navigation.
