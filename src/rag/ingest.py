"""Pipeline de ingestão da base de conhecimento: PDF → chunks → ChromaDB.

Pode ser executado como CLI:

    python -m src.rag.ingest [--pdf docs/base.pdf] [--persist-dir ./chroma_db]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

if TYPE_CHECKING:
    from langchain_chroma import Chroma
    from langchain_core.embeddings import Embeddings


logger = logging.getLogger(__name__)

COLLECTION_NAME = "azapfy_kb"


def load_pdf(pdf_path: Path) -> list[Document]:
    """Carrega um PDF e retorna uma lista de `Document` (1 por página).

    Cada `Document` traz `metadata['page']` (0-indexado) e
    `metadata['source']` apontando para o arquivo de origem.
    """
    # Import tardio para que `import src.rag.ingest` continue leve.
    from langchain_community.document_loaders import PyPDFLoader

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF não encontrado em {pdf_path}. "
            "Coloque o arquivo de conhecimento em docs/base.pdf antes de rodar a ingestão."
        )

    loader = PyPDFLoader(str(pdf_path))
    documents = loader.load()
    logger.info("Carregadas %d páginas de %s", len(documents), pdf_path)
    return documents


def split_documents(
    documents: list[Document],
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[Document]:
    """Divide os documentos em chunks com overlap, preservando metadata."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    logger.info(
        "Gerados %d chunks (chunk_size=%d, overlap=%d)",
        len(chunks),
        chunk_size,
        chunk_overlap,
    )
    return chunks


def persist_chunks(
    chunks: list[Document],
    persist_dir: Path,
    embeddings: "Embeddings",
    collection_name: str = COLLECTION_NAME,
) -> "Chroma":
    """Persiste os chunks num ChromaDB em disco e devolve o vector store."""
    from langchain_chroma import Chroma

    persist_dir = Path(persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)

    store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(persist_dir),
        collection_name=collection_name,
    )
    logger.info(
        "ChromaDB persistido em %s (collection=%s, docs=%d)",
        persist_dir,
        collection_name,
        len(chunks),
    )
    return store


def ingest(
    pdf_path: Path,
    persist_dir: Path,
    embeddings: "Embeddings",
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> "Chroma":
    """Pipeline completo: carrega PDF → splita → persiste em ChromaDB."""
    documents = load_pdf(pdf_path)
    chunks = split_documents(documents, chunk_size, chunk_overlap)
    return persist_chunks(chunks, persist_dir, embeddings)


def _cli() -> None:
    from src.config import get_settings
    from src.rag.retriever import get_embeddings

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    settings = get_settings()

    parser = argparse.ArgumentParser(
        description="Ingere o PDF de conhecimento da Azapfy no ChromaDB persistido."
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=settings.pdf_path,
        help="Caminho do PDF (default: PDF_PATH do .env).",
    )
    parser.add_argument(
        "--persist-dir",
        type=Path,
        default=settings.chroma_persist_dir,
        help="Diretório de persistência do Chroma (default: CHROMA_PERSIST_DIR).",
    )
    parser.add_argument("--chunk-size", type=int, default=settings.rag_chunk_size)
    parser.add_argument("--chunk-overlap", type=int, default=settings.rag_chunk_overlap)
    args = parser.parse_args()

    embeddings = get_embeddings()
    store = ingest(
        args.pdf,
        args.persist_dir,
        embeddings,
        args.chunk_size,
        args.chunk_overlap,
    )
    total = store._collection.count()
    print(f"Ingestão concluída. Documentos indexados no Chroma: {total}")


if __name__ == "__main__":
    _cli()
