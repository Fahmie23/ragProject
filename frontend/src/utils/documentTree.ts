import type { CanonicalElement, StructuredDocument } from "../types";

export type DocumentTreeNodeKind = "document" | "element";

export interface DocumentTreeContinuation {
  relationId: string;
  direction: "incoming" | "outgoing";
  pageNumber: number;
  elementId: string;
}

export interface DocumentTreeNode {
  id: string;
  kind: DocumentTreeNodeKind;
  label: string;
  type: string;
  pageNumber?: number;
  element?: CanonicalElement;
  children: DocumentTreeNode[];
  continuations: DocumentTreeContinuation[];
  contextOnly?: boolean;
}

function compactText(text: string, fallback: string) {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return fallback;
  return clean.length > 58 ? `${clean.slice(0, 55)}…` : clean;
}

export function buildDocumentTree(structure: StructuredDocument): DocumentTreeNode {
  const elements = structure.pages.flatMap((page) => page.elements);
  const elementById = new Map(elements.map((element) => [element.element_id, element] as const));
  const childrenByParent = new Map<string, Set<string>>();
  const parentByChild = new Map<string, string>();

  function addEdge(parentId: string | null | undefined, childId: string | null | undefined, force = false) {
    if (!parentId || !childId || parentId === childId || !elementById.has(parentId) || !elementById.has(childId)) return;
    if (parentByChild.has(childId) && !force) return;
    if (force) {
      const old = parentByChild.get(childId);
      if (old) childrenByParent.get(old)?.delete(childId);
    }
    parentByChild.set(childId, parentId);
    if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, new Set());
    childrenByParent.get(parentId)!.add(childId);
  }

  // Explicit canonical hierarchy takes highest priority. Clause hierarchy uses
  // parent_of; Stage 4 semantic-v2 local grouping uses introduces so those
  // dependencies remain separate from ClauseRecord-backed parent relations.
  const semanticDependencyTypes = new Set(["group_header", "clause", "subclause", "list_item"]);
  for (const relation of structure.relationships) {
    if (relation.type === "parent_of") {
      addEdge(relation.source_element_id, relation.target_element_id, true);
      continue;
    }
    if (relation.type === "introduces") {
      const source = elementById.get(relation.source_element_id);
      const target = elementById.get(relation.target_element_id);
      if (source && target && semanticDependencyTypes.has(source.type) && semanticDependencyTypes.has(target.type)) {
        addEdge(relation.source_element_id, relation.target_element_id, true);
      }
    }
  }

  // Section hierarchy and section membership.
  const sectionById = new Map(structure.sections.map((section) => [section.section_id, section] as const));
  for (const section of structure.sections) {
    const parentSection = section.parent_section_id ? sectionById.get(section.parent_section_id) : null;
    if (parentSection) addEdge(parentSection.element_id, section.element_id);
    for (const childId of section.content_element_ids) addEdge(section.element_id, childId);
  }

  // Definition term -> definition text is more useful than generic section membership.
  for (const definition of structure.definitions) {
    if (!definition.term_element_id) continue;
    const term = elementById.get(definition.term_element_id);
    if (!term) continue;
    for (const childId of definition.definition_element_ids) {
      if (childId !== definition.term_element_id) addEdge(definition.term_element_id, childId, true);
    }
    if (definition.section_id) {
      const section = sectionById.get(definition.section_id);
      if (section) addEdge(section.element_id, definition.term_element_id);
    }
  }

  // Clause / subclause hierarchy.
  const clauseById = new Map(structure.clauses.map((clause) => [clause.clause_id, clause] as const));
  for (const clause of structure.clauses) {
    if (clause.parent_clause_id) {
      const parent = clauseById.get(clause.parent_clause_id);
      if (parent) addEdge(parent.element_id, clause.element_id, true);
    } else if (clause.section_id) {
      const section = sectionById.get(clause.section_id);
      if (section) addEdge(section.element_id, clause.element_id);
    }
  }

  // Canonical element metadata can fill gaps left by records.
  for (const element of elements) {
    if (parentByChild.has(element.element_id)) continue;
    if (element.parent_clause_id) {
      const parent = clauseById.get(element.parent_clause_id);
      if (parent) addEdge(parent.element_id, element.element_id);
      continue;
    }
    if (element.section_id) {
      const section = sectionById.get(element.section_id);
      if (section && section.element_id !== element.element_id) addEdge(section.element_id, element.element_id);
    }
  }

  const continuationMap = new Map<string, DocumentTreeContinuation[]>();
  for (const relation of structure.relationships.filter((item) => item.type === "continues")) {
    const source = elementById.get(relation.source_element_id);
    const target = elementById.get(relation.target_element_id);
    if (!source || !target || source.page_number === target.page_number) continue;
    const out: DocumentTreeContinuation = {
      relationId: relation.relation_id,
      direction: "outgoing",
      pageNumber: target.page_number,
      elementId: target.element_id,
    };
    const incoming: DocumentTreeContinuation = {
      relationId: relation.relation_id,
      direction: "incoming",
      pageNumber: source.page_number,
      elementId: source.element_id,
    };
    continuationMap.set(source.element_id, [...(continuationMap.get(source.element_id) ?? []), out]);
    continuationMap.set(target.element_id, [...(continuationMap.get(target.element_id) ?? []), incoming]);
  }

  const elementNode = (element: CanonicalElement, visiting = new Set<string>()): DocumentTreeNode => {
    const nextVisiting = new Set(visiting);
    nextVisiting.add(element.element_id);
    const childIds = [...(childrenByParent.get(element.element_id) ?? [])]
      .filter((id) => !nextVisiting.has(id));
    const children = childIds
      .map((id) => elementById.get(id))
      .filter((item): item is CanonicalElement => Boolean(item))
      .sort((a, b) => a.document_order - b.document_order)
      .map((child) => elementNode(child, nextVisiting));

    return {
      id: element.element_id,
      kind: "element",
      label: compactText(element.text, element.element_id),
      type: element.type,
      pageNumber: element.page_number,
      element,
      children,
      continuations: continuationMap.get(element.element_id) ?? [],
    };
  };

  const rootCandidates = elements
    .filter((element) => !parentByChild.has(element.element_id))
    .filter((element) => !["page_header", "page_footer", "footnote"].includes(element.type))
    .sort((a, b) => a.document_order - b.document_order);

  return {
    id: "__document__",
    kind: "document",
    label: structure.title || structure.source_filename,
    type: "document",
    children: rootCandidates.map((element) => elementNode(element)),
    continuations: [],
  };
}


/**
 * Filter a canonical tree to one or more page numbers while preserving the
 * ancestor path required to understand hierarchy. Nodes outside the current
 * page are retained as lightweight context only when they are in the requested
 * page set or contain matching descendants.
 */
export function filterDocumentTreeForPages(
  tree: DocumentTreeNode,
  pageNumbers: number[],
  currentPage: number,
): DocumentTreeNode {
  const pages = new Set(pageNumbers.filter((page) => page > 0));

  const filterNode = (node: DocumentTreeNode): DocumentTreeNode | null => {
    if (node.kind === "document") {
      return {
        ...node,
        children: node.children
          .map(filterNode)
          .filter((child): child is DocumentTreeNode => Boolean(child)),
      };
    }

    const children = node.children
      .map(filterNode)
      .filter((child): child is DocumentTreeNode => Boolean(child));
    const inWindow = Boolean(node.pageNumber && pages.has(node.pageNumber));

    if (!inWindow && children.length === 0) return null;

    return {
      ...node,
      children,
      contextOnly: node.pageNumber !== currentPage,
    };
  };

  return filterNode(tree) ?? { ...tree, children: [] };
}

/** Keep only the active page plus structural ancestors. */
export function filterDocumentTreeForPage(tree: DocumentTreeNode, pageNumber: number): DocumentTreeNode {
  return filterDocumentTreeForPages(tree, [pageNumber], pageNumber);
}

/**
 * Keep Review/nearby inspection focused on previous, current, and next page.
 * The current page remains visually primary; neighboring pages and inherited
 * ancestors are marked as context.
 */
export function filterDocumentTreeForPageWindow(tree: DocumentTreeNode, pageNumber: number): DocumentTreeNode {
  return filterDocumentTreeForPages(tree, [pageNumber - 1, pageNumber, pageNumber + 1], pageNumber);
}
