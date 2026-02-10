#!/bin/bash
###
 # @Author: haoxingjun
 # @Date: 2026-02-10 15:38:59
 # @Email: haoxingjun@bytedance.com
 # @LastEditors: haoxingjun
 # @LastEditTime: 2026-02-10 15:39:00
 # @Description: file information
 # @Company: ByteDance
### 

# Define common parameters
PERSIST_DIR="./chroma_db"
EMBEDDING_PROVIDER="sentence-transformers"

# 1. meta_event
echo "Ingesting meta_event..."
python ingest_csv_to_chroma.py \
    --csv_paths src/sample_data/meta_event_20260209.csv \
    --persist_dir "$PERSIST_DIR" \
    --collection_name meta_event \
    --id_field id \
    --text_fields event_name event_desc event_code \
    --metadata_fields event_type group_id business_id is_system enabled \
    --embedding_provider "$EMBEDDING_PROVIDER"

# 2. meta_event_attr
echo "Ingesting meta_event_attr..."
python ingest_csv_to_chroma.py \
    --csv_paths src/sample_data/meta_event_attr_20260209.csv \
    --persist_dir "$PERSIST_DIR" \
    --collection_name meta_event_attr \
    --id_field id \
    --text_fields attr_name attr_desc attr_code \
    --metadata_fields attr_type data_type group_id is_common \
    --embedding_provider "$EMBEDDING_PROVIDER"

# 3. meta_user_attr
echo "Ingesting meta_user_attr..."
python ingest_csv_to_chroma.py \
    --csv_paths src/sample_data/meta_user_attr_20260209.csv \
    --persist_dir "$PERSIST_DIR" \
    --collection_name meta_user_attr \
    --id_field id \
    --text_fields attr_name attr_desc attr_code \
    --metadata_fields data_type group_id business_id \
    --embedding_provider "$EMBEDDING_PROVIDER"

# 4. meta_virtual_event
echo "Ingesting meta_virtual_event..."
python ingest_csv_to_chroma.py \
    --csv_paths src/sample_data/meta_virtual_event_20260209.csv \
    --persist_dir "$PERSIST_DIR" \
    --collection_name meta_virtual_event \
    --id_field id \
    --text_fields event_name event_code condition_json \
    --metadata_fields group_id business_id enabled \
    --embedding_provider "$EMBEDDING_PROVIDER"

# 5. sys_dict
echo "Ingesting sys_dict..."
python ingest_csv_to_chroma.py \
    --csv_paths src/sample_data/sys_dict_20260209.csv \
    --persist_dir "$PERSIST_DIR" \
    --collection_name sys_dict \
    --id_field dict_id \
    --text_fields name description \
    --metadata_fields dict_type \
    --embedding_provider "$EMBEDDING_PROVIDER"

# 6. sys_dict_detail
echo "Ingesting sys_dict_detail..."
python ingest_csv_to_chroma.py \
    --csv_paths src/sample_data/sys_dict_detail_20260209.csv \
    --persist_dir "$PERSIST_DIR" \
    --collection_name sys_dict_detail \
    --id_field detail_id \
    --text_fields label value \
    --metadata_fields dict_id dict_sort \
    --embedding_provider "$EMBEDDING_PROVIDER"

echo "All ingestion tasks completed."
