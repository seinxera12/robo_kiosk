"""
Knowledge base ingestion script.

Reads markdown documents from building_kb/ and ingests into ChromaDB.
"""

import os
import re
from pathlib import Path
from typing import List, Literal, Optional
import logging

from server.rag.chroma_store import BuildingKB, DocumentChunk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def detect_language(filename: str, content: str) -> Literal["en", "ja"]:
    """
    Detect document language from filename and content.
    
    Args:
        filename: Document filename
        content: Document content
        
    Returns:
        "en" or "ja"
    """
    # Check filename for language indicator
    if "_ja" in filename or "japanese" in filename.lower():
        return "ja"
    
    # Check content for Japanese characters
    japanese_chars = sum(
        1 for c in content 
        if '\u3000' <= c <= '\u9fff' or '\uff00' <= c <= '\uffef'
    )
    
    if japanese_chars > len(content) * 0.1:
        return "ja"
    
    return "en"


def extract_floor_number(filename: str, content: str) -> Optional[int]:
    """
    Extract floor number from filename or content.
    
    Args:
        filename: Document filename
        content: Document content
        
    Returns:
        Floor number or None
    """
    # Try filename first
    match = re.search(r'floor[_\s]?(\d+)', filename, re.IGNORECASE)
    if match:
        return int(match.group(1))
    
    # Try content
    match = re.search(r'(?:floor|階)\s*(\d+)', content, re.IGNORECASE)
    if match:
        return int(match.group(1))
    
    return None


def determine_doc_type(filename: str, content: str) -> Literal["floor", "facility", "room", "emergency"]:
    """
    Determine document type from filename and content.
    
    Args:
        filename: Document filename
        content: Document content
        
    Returns:
        Document type
    """
    filename_lower = filename.lower()
    content_lower = content.lower()
    
    if "floor" in filename_lower or "階" in filename:
        return "floor"
    elif "emergency" in filename_lower or "exit" in filename_lower:
        return "emergency"
    elif "room" in filename_lower or "会議室" in content:
        return "room"
    else:
        return "facility"


def chunk_document(content: str, chunk_size: int = 500) -> List[str]:
    """
    Chunk document into smaller pieces.
    
    Args:
        content: Document content
        chunk_size: Target chunk size in characters
        
    Returns:
        List of text chunks
    """
    # Split by paragraphs
    paragraphs = content.split('\n\n')
    
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # If adding this paragraph exceeds chunk size, start new chunk
        if len(current_chunk) + len(para) > chunk_size and current_chunk:
            chunks.append(current_chunk)
            current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
    
    # Add remaining chunk
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def ingest_directory(kb_path: str, chroma_path: str) -> None:
    """
    Ingest all markdown documents from knowledge base directory.
    
    Args:
        kb_path: Path to building_kb directory
        chroma_path: Path to ChromaDB storage
    """
    kb = BuildingKB(chroma_path)
    
    all_chunks = []
    chunk_id = 0
    
    # Walk through all markdown files
    for root, dirs, files in os.walk(kb_path):
        for filename in files:
            if not filename.endswith('.md'):
                continue
            
            filepath = os.path.join(root, filename)
            logger.info(f"Processing: {filepath}")
            
            # Read file
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Detect metadata
            lang = detect_language(filename, content)
            floor = extract_floor_number(filename, content)
            doc_type = determine_doc_type(filename, content)
            
            # Chunk document
            chunks = chunk_document(content)
            
            # Create DocumentChunk objects
            for chunk_text in chunks:
                chunk = DocumentChunk(
                    id=f"chunk_{chunk_id}",
                    text=chunk_text,
                    lang=lang,
                    floor=floor,
                    type=doc_type
                )
                all_chunks.append(chunk)
                chunk_id += 1
            
            logger.info(f"  Created {len(chunks)} chunks (lang={lang}, floor={floor}, type={doc_type})")
    
    # Ingest all chunks
    if all_chunks:
        logger.info(f"Ingesting {len(all_chunks)} total chunks into ChromaDB...")
        kb.ingest(all_chunks)
        logger.info("Ingestion complete!")
    else:
        logger.warning("No documents found to ingest")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest building knowledge base into ChromaDB")
    parser.add_argument(
        "--kb-path",
        default="building_kb",
        help="Path to building knowledge base directory"
    )
    parser.add_argument(
        "--chroma-path",
        default="./chroma_db",
        help="Path to ChromaDB storage directory"
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting ingestion from {args.kb_path} to {args.chroma_path}")
    ingest_directory(args.kb_path, args.chroma_path)


if __name__ == "__main__":
    main()
