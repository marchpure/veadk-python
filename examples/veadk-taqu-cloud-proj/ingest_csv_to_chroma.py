import argparse
import os
import sys
from typing import List, Dict, Any, Optional, Union
from abc import ABC, abstractmethod

import pandas as pd
import chromadb
from chromadb.config import Settings
import tqdm

# --- Embedding Interfaces ---

class BaseEmbedding(ABC):
    @abstractmethod
    def encode(self, texts: List[str]) -> List[List[float]]:
        pass

class LocalSentenceTransformerEmbedding(BaseEmbedding):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
        except ImportError:
            raise ImportError("Please install sentence-transformers: pip install sentence-transformers")

    def encode(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

class OpenAIEmbedding(BaseEmbedding):
    def __init__(self, model_name: str = "text-embedding-ada-002"):
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            self.model_name = model_name
        except ImportError:
            raise ImportError("Please install openai: pip install openai")
        except Exception as e:
             raise ValueError(f"Failed to initialize OpenAI client. Ensure OPENAI_API_KEY is set. Error: {e}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        # OpenAI usually supports batching, but we should be careful with limits.
        # Here we assume the batch size passed to the script is reasonable.
        response = self.client.embeddings.create(input=texts, model=self.model_name)
        return [data.embedding for data in response.data]

def get_embedding_provider(provider_name: str) -> BaseEmbedding:
    if provider_name == "openai":
        return OpenAIEmbedding()
    else:
        # Default to local sentence-transformers
        return LocalSentenceTransformerEmbedding()

# --- Data Processing ---

def construct_document_text(row: pd.Series, text_fields: List[str]) -> str:
    """
    Constructs document text by concatenating key: value pairs for non-empty fields.
    """
    parts = []
    for field in text_fields:
        if field in row and pd.notna(row[field]) and str(row[field]).strip():
            parts.append(f"{field}: {row[field]}")
    return "\n".join(parts)

def construct_search_alias(row: pd.Series) -> str:
    """
    Constructs search_alias metadata by merging potential alias columns.
    Logic: Looks for 'synonyms' column as per requirement example. 
    Splits by '|' and rejoins with ', ' for better readability/searchability in metadata.
    """
    aliases = []
    # Heuristic: Check for 'synonyms' column
    if 'synonyms' in row and pd.notna(row['synonyms']):
        val = str(row['synonyms'])
        # Split by | and strip
        parts = [p.strip() for p in val.split('|') if p.strip()]
        aliases.extend(parts)
    
    return ", ".join(aliases)

def process_chunk(
    chunk: pd.DataFrame,
    id_field: str,
    text_fields: List[str],
    metadata_fields: List[str],
    collection: chromadb.Collection,
    embedding_provider: BaseEmbedding,
    upsert: bool = True,
    skip_if_exists: bool = False
):
    # 1. Clean data: Remove rows with empty ID
    chunk = chunk.dropna(subset=[id_field])
    # Remove rows where all columns are empty (optional, but good practice)
    chunk = chunk.dropna(how='all')
    
    if chunk.empty:
        return

    # 2. Prepare data for Chroma
    ids = []
    documents = []
    metadatas = []
    
    # Check existence if needed
    if skip_if_exists:
        existing_ids = set()
        # Chroma doesn't have a cheap "exists" check for a batch of IDs without fetching?
        # get() can be used.
        chunk_ids = chunk[id_field].astype(str).tolist()
        try:
            # Fetch existing IDs to filter
            existing = collection.get(ids=chunk_ids, include=[])
            existing_ids = set(existing['ids'])
        except Exception as e:
            print(f"Warning: Error checking existing IDs: {e}")
    
    rows_to_process = []
    
    for _, row in chunk.iterrows():
        doc_id = str(row[id_field]).strip()
        if not doc_id:
            continue
            
        if skip_if_exists and doc_id in existing_ids:
            continue
            
        # Text construction
        doc_text = construct_document_text(row, text_fields)
        if not doc_text:
            # Skip if no text content? Or index empty?
            # Let's skip empty documents to avoid noise
            continue
            
        # Metadata construction
        meta = {}
        for field in metadata_fields:
            if field in row and pd.notna(row[field]):
                meta[field] = row[field]
        
        # Add search_alias
        search_alias = construct_search_alias(row)
        if search_alias:
            meta['search_alias'] = search_alias
            
        rows_to_process.append({
            "id": doc_id,
            "document": doc_text,
            "metadata": meta
        })

    if not rows_to_process:
        return

    # Batch embedding generation
    batch_docs = [item["document"] for item in rows_to_process]
    embeddings = embedding_provider.encode(batch_docs)
    
    batch_ids = [item["id"] for item in rows_to_process]
    batch_metadatas = [item["metadata"] for item in rows_to_process]
    
    # Write to Chroma
    if upsert:
        collection.upsert(
            ids=batch_ids,
            embeddings=embeddings,
            documents=batch_docs,
            metadatas=batch_metadatas
        )
    else:
        # add() throws error if ID exists
        collection.add(
            ids=batch_ids,
            embeddings=embeddings,
            documents=batch_docs,
            metadatas=batch_metadatas
        )

# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Ingest CSV to ChromaDB")
    parser.add_argument("--csv_paths", nargs='+', required=True, help="List of CSV file paths")
    parser.add_argument("--persist_dir", required=True, help="ChromaDB persistence directory")
    parser.add_argument("--collection_name", required=True, help="Collection name")
    parser.add_argument("--id_field", required=True, help="Column name for Document ID")
    parser.add_argument("--text_fields", nargs='+', required=True, help="Columns to concatenate for search text")
    parser.add_argument("--metadata_fields", nargs='+', required=True, help="Columns to store in metadata")
    parser.add_argument("--embedding_provider", default="sentence-transformers", help="Embedding provider: 'sentence-transformers' or 'openai'")
    parser.add_argument("--batch_size", type=int, default=100, help="Batch size for processing")
    parser.add_argument("--skip_if_exists", action="store_true", help="Skip processing if ID already exists")
    
    args = parser.parse_args()
    
    # Validate CSV paths
    for path in args.csv_paths:
        if not os.path.exists(path):
            print(f"Error: File not found: {path}")
            sys.exit(1)
            
    # Initialize Embedding Provider
    print(f"Initializing embedding provider: {args.embedding_provider}...")
    embedder = get_embedding_provider(args.embedding_provider)
    
    # Initialize ChromaDB
    print(f"Initializing ChromaDB at {args.persist_dir}...")
    client = chromadb.PersistentClient(path=args.persist_dir)
    
    # Get or Create Collection
    # Note: We don't pass the embedding function to Chroma because we compute embeddings manually 
    # and pass them to upsert/add. This gives us more control.
    collection = client.get_or_create_collection(name=args.collection_name)
    
    print(f"Starting ingestion into collection '{args.collection_name}'...")
    
    total_processed = 0
    
    for csv_path in args.csv_paths:
        print(f"Processing file: {csv_path}")
        
        # Use pandas chunksize for memory efficiency
        # Handle CSV reading options (encoding, etc.) - sticking to defaults for now
        try:
            # First, read header to validate columns
            header = pd.read_csv(csv_path, nrows=0)
            missing_text = [col for col in args.text_fields if col not in header.columns]
            missing_meta = [col for col in args.metadata_fields if col not in header.columns]
            missing_id = args.id_field not in header.columns
            
            if missing_id:
                print(f"Error: ID field '{args.id_field}' not found in {csv_path}")
                continue
            
            if missing_text:
                print(f"Warning: Missing text fields in {csv_path}: {missing_text}")
                
            # Force ID field to be string to avoid float/int mismatch (e.g. "1" vs "1.0")
            chunk_iterator = pd.read_csv(
                csv_path, 
                chunksize=args.batch_size, 
                dtype={args.id_field: str}
            )
            
            for chunk in tqdm.tqdm(chunk_iterator, desc=f"Ingesting {os.path.basename(csv_path)}"):
                process_chunk(
                    chunk=chunk,
                    id_field=args.id_field,
                    text_fields=args.text_fields,
                    metadata_fields=args.metadata_fields,
                    collection=collection,
                    embedding_provider=embedder,
                    upsert=True, # Default to upsert as per requirements
                    skip_if_exists=args.skip_if_exists
                )
                total_processed += len(chunk)
                
        except Exception as e:
            print(f"Error processing {csv_path}: {e}")
            import traceback
            traceback.print_exc()

    print(f"Ingestion complete. Total rows processed (approx): {total_processed}")

if __name__ == "__main__":
    main()
