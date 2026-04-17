"""
ChromaDB-backed building knowledge base for RAG.

This module provides document ingestion and retrieval functionality
using ChromaDB vector database with multilingual embeddings.
"""

import chromadb
from chromadb.config import Settings
from typing import List, Optional, Literal
from dataclasses import dataclass
import logging

from server.rag.embedder import Embedder

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """Document chunk with metadata."""
    id: str
    text: str
    lang: Literal["en", "ja"]
    floor: Optional[int]
    type: Literal["floor", "facility", "room", "emergency"]


class BuildingKB:
    """
    ChromaDB-backed building knowledge base.
    
    Provides document ingestion and language-filtered retrieval
    for building navigation assistance.
    """
    
    def __init__(self, path: str):
        """
        Initialize ChromaDB client and collection.
        
        Args:
            path: Path to ChromaDB persistent storage
        """
        self.client = chromadb.PersistentClient(
            path=path,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection("building_kb")
        self.embedder = Embedder()
        logger.info(f"Initialized BuildingKB with path: {path}")
    
    def ingest(self, docs: List[DocumentChunk]) -> None:
        """
        Ingest document chunks into ChromaDB.
        
        Args:
            docs: List of DocumentChunk objects to ingest
            
        Preconditions:
            - docs is non-empty list
            - Each chunk has unique id
            
        Postconditions:
            - All chunks stored in collection
            - Embeddings computed and indexed
        """
        if not docs:
            logger.warning("No documents to ingest")
            return
        
        texts = [d.text for d in docs]
        embeddings = self.embedder.encode(texts)
        
        self.collection.add(
            ids=[d.id for d in docs],
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=[
                {
                    "lang": d.lang,
                    "floor": d.floor if d.floor is not None else -1,
                    "type": d.type
                }
                for d in docs
            ]
        )
        
        logger.info(f"Ingested {len(docs)} document chunks")
    
    async def retrieve(
        self,
        query: str,
        lang: Literal["en", "ja"],
        n: int = 3
    ) -> str:
        """
        Retrieve top-N relevant chunks for query.
        
        Args:
            query: User query text
            lang: Language filter ("en" or "ja")
            n: Number of chunks to retrieve
            
        Returns:
            Concatenated text of top-N relevant chunks
            
        Preconditions:
            - query is non-empty string
            - lang is "en" or "ja"
            - n > 0
            
        Postconditions:
            - Returns concatenated text of top-N chunks
            - All chunks match requested language
            - Chunks ordered by relevance
        """
        # Embed query
        query_embedding = self.embedder.encode([query])
        
        # Query ChromaDB with language filter
        # results = self.collection.query(
        #     query_embeddings=query_embedding.tolist(),
        #     n_results=n,
        #     where={"lang": lang}
        # )
        try:
            count = self.collection.count()
            if count == 0:
                logger.warning("ChromaDB collection is empty — skipping RAG retrieval")
                return ""
            results = self.collection.query(
                query_embeddings=query_embedding.tolist(),
                n_results=min(n, count),   # don't request more than available
                where={"lang": lang}
            )
        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e} — continuing without context")
            return ""        
        # Concatenate results
        chunks = results["documents"][0] if results["documents"] else []
        context = "\n\n".join(chunks)
        
        logger.debug(f"Retrieved {len(chunks)} chunks for query: {query[:50]}...")
        
        return context
