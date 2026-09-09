"""LCEL composition for the optional LangChain integration example."""

from __future__ import annotations

from typing import Any

from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.retrievers import BaseRetriever


SYSTEM_PROMPT = """You are answering questions about a regulatory document.
Use only the supplied context. If the context is insufficient, say that the
retrieved evidence is insufficient instead of guessing.

Each evidence block has a label such as [LC1]. Cite those labels when they
support a claim. Do not invent labels or facts that are absent from the
context.

This is a LangChain integration demo. The production RAG Document Studio uses
its own deterministic citation/provenance assembly after generation; these
[LCn] labels are only prompt-level citations for the framework example."""


def format_documents(documents: list[Document]) -> str:
    """Convert retrieved LangChain Documents into explicit evidence blocks."""

    blocks: list[str] = []
    for index, document in enumerate(documents, start=1):
        pages = document.metadata.get("pages") or []
        section_path = document.metadata.get("section_path") or []
        chunk_id = document.metadata.get("chunk_id") or "unknown"
        header_parts = [f"[LC{index}]", f"chunk={chunk_id}"]
        if pages:
            header_parts.append("pages=" + ",".join(str(page) for page in pages))
        if section_path:
            header_parts.append("section=" + " > ".join(str(item) for item in section_path))
        blocks.append(" | ".join(header_parts) + "\n" + document.page_content.strip())
    return "\n\n".join(blocks)


def build_rag_chain(*, retriever: BaseRetriever, llm: BaseChatModel):
    """Build an LCEL chain that returns both the answer and retrieved documents.

    The retriever remains the existing RAG Document Studio pipeline; LangChain
    is used here for the standard retriever interface, prompt composition, model
    invocation, and runnable orchestration.
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            (
                "human",
                "Retrieved context:\n\n{context}\n\nQuestion: {question}\n\n"
                "Answer using only the retrieved context.",
            ),
        ]
    )
    answer_chain = prompt | llm | StrOutputParser()

    def retrieve(question: str) -> dict[str, Any]:
        documents = retriever.invoke(question)
        return {
            "question": question,
            "context": format_documents(documents),
            "documents": documents,
        }

    # RunnablePassthrough.assign keeps the retrieved Document objects in the
    # output while adding the generated answer. This makes provenance easy to
    # inspect in the demo rather than hiding retrieval behind a single string.
    return RunnableLambda(retrieve) | RunnablePassthrough.assign(answer=answer_chain)
