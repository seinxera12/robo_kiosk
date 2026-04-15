"""
Multilingual E5 embedder for RAG.

**Validates: Requirements 7.2, 24.6**
"""

import numpy as np
from typing import List
from sentence_transformers import SentenceTransformer


class Embedder:
    """
    Multilingual E5 embedder for RAG.
    
    Preconditions:
    - Model downloaded to cache
    - Runs on CPU (offload from GPU)
    
    Postconditions:
    - Returns 1024-dim embeddings
    - Embedding time ~30ms per query
    """
    
    def __init__(self, model_name: str = "intfloat/multilingual-e5-large"):
        """
        Initialize the embedder with the specified model.
        
        Args:
            model_name: HuggingFace model identifier
        """
        self.model = SentenceTransformer(model_name, device="cpu")
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """
        Encode texts to embeddings.
        
        Preconditions:
        - texts is non-empty list of strings
        
        Postconditions:
        - Returns array of shape (len(texts), 1024)
        - All embeddings are L2-normalized
        
        Loop Invariants:
        - Each text produces exactly one embedding
        - Embedding dimension is constant
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            L2-normalized embeddings of shape (len(texts), 1024)
        """
        # Add E5 instruction prefix
        texts_with_prefix = [f"query: {t}" for t in texts]
        embeddings = self.model.encode(texts_with_prefix, normalize_embeddings=True)
        return embeddings
