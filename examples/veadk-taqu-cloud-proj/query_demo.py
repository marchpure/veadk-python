import argparse
import chromadb
from ingest_csv_to_chroma import get_embedding_provider

def main():
    parser = argparse.ArgumentParser(description="Query ChromaDB")
    parser.add_argument("--query", required=True, help="Query text")
    parser.add_argument("--persist_dir", required=True, help="ChromaDB persistence directory")
    parser.add_argument("--collection_name", required=True, help="Collection name")
    parser.add_argument("--embedding_provider", default="sentence-transformers", help="Embedding provider")
    parser.add_argument("--top_k", type=int, default=5, help="Number of results to return")
    
    args = parser.parse_args()
    
    print(f"Initializing embedding provider: {args.embedding_provider}...")
    embedder = get_embedding_provider(args.embedding_provider)
    
    print(f"Connecting to ChromaDB at {args.persist_dir}...")
    client = chromadb.PersistentClient(path=args.persist_dir)
    collection = client.get_collection(name=args.collection_name)
    
    print(f"Querying: '{args.query}'")
    
    # Generate embedding for query
    query_embedding = embedder.encode([args.query])
    
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=args.top_k,
        include=["documents", "metadatas", "distances"]
    )
    
    print("\nResults:")
    for i in range(len(results['ids'][0])):
        doc_id = results['ids'][0][i]
        distance = results['distances'][0][i]
        document = results['documents'][0][i]
        metadata = results['metadatas'][0][i]
        
        print(f"[{i+1}] ID: {doc_id} | Distance: {distance:.4f}")
        print(f"    Document: {document}")
        print(f"    Metadata: {metadata}")
        print("-" * 50)

if __name__ == "__main__":
    main()
