import chromadb
import os
import argparse
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from pymilvus import connections, FieldSchema, CollectionSchema, DataType, Collection, utility
from sentence_transformers import SentenceTransformer

# Constants
CHROMA_PERSIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../chroma_db"))
MILVUS_URI = "http://s-00cq9vm3wj88.milvus.volces.com:19530"
MILVUS_USER = "user_00cq9vm3wj88"
MILVUS_PASSWORD = "Rety0515@"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"  # Ensure this matches your ingestion model
VECTOR_DIM = 384  # Dimension for all-MiniLM-L6-v2
BATCH_SIZE = 2000
MAX_WORKERS = 32

# Collections to migrate
COLLECTIONS = [
    "sys_dict_detail"
]

def connect_milvus():
    print(f"Connecting to Milvus at {MILVUS_URI}...")
    try:
        connections.connect("default", uri=MILVUS_URI, user=MILVUS_USER, password=MILVUS_PASSWORD)
        print("Connected to Milvus.")
    except Exception as e:
        print(f"Failed to connect to Milvus: {e}")
        exit(1)

def create_milvus_collection(name: str, dim: int):
    """
    Creates a collection in Milvus.
    Schema:
    - id: VARCHAR (Primary Key)
    - text: VARCHAR (The document content)
    - vector: FLOAT_VECTOR
    - metadata: JSON (Stores the original metadata)
    """
    if utility.has_collection(name):
        print(f"Collection '{name}' already exists. Dropping it for fresh migration...")
        utility.drop_collection(name)

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=65535, is_primary=True),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="metadata", dtype=DataType.JSON)
    ]
    schema = CollectionSchema(fields, description=f"Migrated from ChromaDB collection {name}")
    collection = Collection(name, schema)
    
    # Create index for vector field
    index_params = {
        "metric_type": "L2",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128}
    }
    collection.create_index(field_name="vector", index_params=index_params)
    print(f"Created collection '{name}' in Milvus.")
    return collection

def migrate():
    # Connect to Chroma
    print(f"Loading ChromaDB from {CHROMA_PERSIST_DIR}...")
    chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    
    # Connect to Milvus
    connect_milvus()
    
    # Initialize embedding model (if needed to re-embed, but Chroma usually stores embeddings)
    # Chroma `get` method returns embeddings if included.
    
    for col_name in COLLECTIONS:
        print(f"\nMigrating collection: {col_name}...")
        try:
            chroma_col = chroma_client.get_collection(col_name)
        except ValueError:
            print(f"Collection '{col_name}' not found in ChromaDB. Skipping.")
            continue
            
        # Fetch all data from Chroma
        # ChromaDB .get() limits to 10 by default, set limit to None (or a large number)
        data = chroma_col.get(include=['documents', 'metadatas', 'embeddings'])
        
        ids = data['ids']
        documents = data['documents']
        metadatas = data['metadatas']
        embeddings = data['embeddings']
        
        if not ids:
            print(f"No data in Chroma collection '{col_name}'. Skipping.")
            continue
            
        count = len(ids)
        print(f"Found {count} records in Chroma.")
        
        # Create Milvus Collection
        has_embeddings = embeddings is not None and len(embeddings) > 0
        dim = len(embeddings[0]) if has_embeddings else VECTOR_DIM
        milvus_col = create_milvus_collection(col_name, dim)
        
        # Batch Insert
        def insert_batch(start_idx):
            end_idx = min(start_idx + BATCH_SIZE, count)
            batch_ids = ids[start_idx : end_idx]
            batch_texts = documents[start_idx : end_idx]
            batch_vectors = embeddings[start_idx : end_idx]
            batch_metadatas = metadatas[start_idx : end_idx]
            
            sanitized_metas = []
            for meta in batch_metadatas:
                if meta is None:
                    meta = {}
                sanitized_metas.append(meta)
            
            data_to_insert = [
                batch_ids,
                batch_texts,
                batch_vectors,
                sanitized_metas
            ]
            milvus_col.insert(data_to_insert)

        # Use ThreadPoolExecutor for concurrent writes
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(insert_batch, i) for i in range(0, count, BATCH_SIZE)]
            for _ in tqdm(futures, total=len(futures), desc=f"Migrating {col_name}"):
                _.result()  # Wait for completion and raise exceptions if any
            
        # Load collection to memory for search
        milvus_col.load()
        print(f"Migrated {count} records to Milvus collection '{col_name}'.")

    print("\nMigration completed successfully.")

if __name__ == "__main__":
    migrate()
