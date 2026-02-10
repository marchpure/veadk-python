import json
import os
from typing import Dict, Any, List, Optional
from pymilvus import connections, Collection, utility
from sentence_transformers import SentenceTransformer

# Constants for Milvus
MILVUS_URI = "http://s-00cq9vm3wj88.milvus.volces.com:19530"
MILVUS_USER = "user_00cq9vm3wj88"
MILVUS_PASSWORD = "replaced"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
VECTOR_DIM = 384

COLLECTION_META_EVENT = "meta_event"
COLLECTION_META_VIRTUAL_EVENT = "meta_virtual_event"
COLLECTION_META_USER_ATTR = "meta_user_attr"
COLLECTION_META_EVENT_ATTR = "meta_event_attr"
COLLECTION_SYS_DICT_DETAIL = "sys_dict_detail"

# Mapping for aggregate functions to aggregateId (Example mapping)
AGGREGATE_MAPPING = {
    "count": "1",          # 假设 1 是 count
    "count_distinct": "2", # 假设 2 是 count_distinct
    "sum": "3",            # 假设 3 是 sum
    "avg": "4",            # 假设 4 是 avg
    "max": "5",
    "min": "6"
}

# Operator semantic mapping
OPERATOR_MAPPING = {
    "=": "eq",
    "in": "in",
    "between": "between",
    ">": "gt",
    "<": "lt",
    ">=": "gte",
    "<=": "lte",
    "contains": "like"
}

class ParamsBackfiller:
    def __init__(self):
        self._connect_milvus()
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        
        # Load collections
        self.col_meta_event = self._get_collection(COLLECTION_META_EVENT)
        self.col_meta_virtual_event = self._get_collection(COLLECTION_META_VIRTUAL_EVENT)
        self.col_meta_user_attr = self._get_collection(COLLECTION_META_USER_ATTR)
        self.col_meta_event_attr = self._get_collection(COLLECTION_META_EVENT_ATTR)
        self.col_sys_dict_detail = self._get_collection(COLLECTION_SYS_DICT_DETAIL)

    def _connect_milvus(self):
        try:
            connections.connect("default", uri=MILVUS_URI, user=MILVUS_USER, password=MILVUS_PASSWORD)
        except Exception as e:
            print(f"Warning: Failed to connect to Milvus. {e}")

    def _get_collection(self, name: str) -> Optional[Collection]:
        try:
            if utility.has_collection(name):
                col = Collection(name)
                col.load()
                return col
        except Exception as e:
            print(f"Warning: Failed to load collection {name}. {e}")
        return None

    def search_one(self, collection: Optional[Collection], query_text: str, expr: str = None) -> Optional[Dict[str, Any]]:
        """Helper to search and return the top result with metadata."""
        if not query_text or collection is None:
            return None
        
        try:
            # Generate embedding
            vector = self.embedding_model.encode([query_text])[0].tolist()
            
            search_params = {
                "metric_type": "L2",
                "params": {"nprobe": 10},
            }
            
            results = collection.search(
                data=[vector],
                anns_field="vector",
                param=search_params,
                limit=1,
                expr=expr,
                output_fields=["id", "text", "metadata"]
            )
            
            if results and len(results[0]) > 0:
                hit = results[0][0]
                return {
                    "id": hit.id,
                    "document": hit.entity.get("text"),
                    "metadata": hit.entity.get("metadata")
                }
        except Exception as e:
            print(f"Error searching collection {collection.name if collection else 'None'}: {e}")
        return None

    def fill_event_id(self, rule: Dict[str, Any]):
        """
        A) Fill eventRules[*].eventId / type
        Sources: meta_event (type=1) / meta_virtual_event (type=2)
        """
        alias = rule.get("alias")
        if not alias:
            return

        # 1. Try meta_event (Real Event)
        res_real = self.search_one(self.col_meta_event, alias)
        # 2. Try meta_virtual_event (Virtual Event)
        res_virtual = self.search_one(self.col_meta_virtual_event, alias)
        
        # Determine best match based on distance (Milvus returns distance in hit)
        # But search_one helper simplifies output. Let's refine if needed.
        # For L2 distance, smaller is better.
        
        # Actually, let's just pick one. To do it properly we need distance.
        # But search_one returns the hit object? No, it returns dict.
        # Let's assume real event priority for now.
        
        if res_real:
             rule["eventId"] = res_real["id"]
             rule["type"] = 1
        elif res_virtual:
             rule["eventId"] = res_virtual["id"]
             rule["type"] = 2

    def fill_aggregate(self, agg_rule: Dict[str, Any]):
        """
        B) Fill aggregateId and aggregate.attrId
        """
        raw_agg_id = agg_rule.get("aggregateId")
        if raw_agg_id in AGGREGATE_MAPPING:
            agg_rule["aggregateId"] = AGGREGATE_MAPPING[raw_agg_id]
        
        raw_attr_id = agg_rule.get("attrId")
        if raw_attr_id:
            res = self.search_one(self.col_meta_event_attr, raw_attr_id)
            if not res:
                res = self.search_one(self.col_meta_user_attr, raw_attr_id)
            
            if res:
                agg_rule["attrId"] = res["id"]

    def fill_filter_attr_and_op(self, filter_rule: Dict[str, Any], context: str = "global"):
        """
        C) Fill attrId / type
        D) Fill operation
        E) Fill param values
        """
        raw_attr_name = filter_rule.get("attrId")
        if not raw_attr_name:
            return

        # 1. Search attr
        res = None
        if context == "global":
            res = self.search_one(self.col_meta_user_attr, raw_attr_name)
            if not res:
                res = self.search_one(self.col_meta_event_attr, raw_attr_name)
        else:
            res = self.search_one(self.col_meta_event_attr, raw_attr_name)
            if not res:
                res = self.search_one(self.col_meta_user_attr, raw_attr_name)
        
        if not res:
            return

        filter_rule["attrId"] = res["id"]
        
        # Determine type
        # Check which collection it came from logic is tricky if we just search_one.
        # But we know where we found it.
        # Let's assume if found in user_attr it's type 1.
        # We need to know which search succeeded.
        # Let's re-search to be precise or improve search_one to return source?
        # Or just checking ID existence is fine if IDs are unique across collections?
        # Assuming IDs might overlap or not.
        # Simplification: If found in user_attr search -> type 1.
        
        is_user_attr = False
        if context == "global":
             # We searched user first
             check = self.search_one(self.col_meta_user_attr, raw_attr_name)
             if check and check["id"] == res["id"]:
                 is_user_attr = True
        else:
             check = self.search_one(self.col_meta_user_attr, raw_attr_name)
             if check and check["id"] == res["id"]:
                 is_user_attr = True
        
        filter_rule["type"] = 1 if is_user_attr else 2
        
        # 2. Fill Operation
        raw_op = filter_rule.get("operation")
        if raw_op:
            semantic_op = OPERATOR_MAPPING.get(raw_op, raw_op)
            filter_rule["operation"] = semantic_op

        # 3. Fill Param Values (Dict Lookup)
        metadata = res.get("metadata", {})
        dict_id = metadata.get("dict_id")
        
        if dict_id and str(dict_id) != "NULL" and str(dict_id) != "None":
            param = filter_rule.get("param", {})
            target_values = []
            if param.get("value1"): target_values.append(("value1", param["value1"]))
            if param.get("valueArr"): 
                for i, v in enumerate(param["valueArr"]):
                    target_values.append((f"valueArr_{i}", v))
            
            for key, label in target_values:
                # Search in sys_dict_detail with filter
                # Milvus filter expression: metadata["dict_id"] == "123"
                # Ensure dict_id is string in metadata
                expr = f'metadata["dict_id"] == "{dict_id}"'
                
                dict_res = self.search_one(self.col_sys_dict_detail, label, expr=expr)
                
                if dict_res:
                    # Parse value from text or metadata?
                    # Migration script put original metadata into 'metadata' field.
                    # In sys_dict_detail, we assume 'value' is in metadata or parsed from text.
                    # Let's check ingestion/migration. 
                    # If migration just copied metadata, and original CSV had 'value' column?
                    # CSV ingestion puts selected fields into metadata.
                    # Let's assume 'value' is available in metadata or we parse text.
                    
                    found_val = dict_res.get("metadata", {}).get("value")
                    
                    # Fallback to parsing text if not in metadata
                    if not found_val and dict_res.get("document"):
                        doc_text = dict_res["document"]
                        parsed = {}
                        for line in doc_text.split('\n'):
                            if ':' in line:
                                k, v = line.split(':', 1)
                                parsed[k.strip()] = v.strip()
                        found_val = parsed.get("value")

                    if found_val:
                        if key == "value1":
                            param["value1"] = found_val
                        elif key.startswith("valueArr_"):
                            idx = int(key.split("_")[1])
                            param["valueArr"][idx] = found_val

    def fill_group_attr(self, group_rule: Dict[str, Any]):
        """
        F) groupRules[*].attrId
        """
        raw_attr = group_rule.get("attrId")
        if not raw_attr:
            return
            
        res = self.search_one(self.col_meta_user_attr, raw_attr)
        if not res:
            res = self.search_one(self.col_meta_event_attr, raw_attr)
            
        if res:
            group_rule["attrId"] = res["id"]
            
            # Set type
            is_user_attr = False
            check = self.search_one(self.col_meta_user_attr, raw_attr)
            if check and check["id"] == res["id"]:
                is_user_attr = True
            group_rule["type"] = 1 if is_user_attr else 2


    def fill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point to backfill parameters."""
        
        # 1. Event Rules
        if "eventRules" in params:
            for rule in params["eventRules"]:
                self.fill_event_id(rule)
                if "aggregate" in rule:
                    self.fill_aggregate(rule["aggregate"])
                if "filters" in rule:
                    for f in rule["filters"]:
                        self.fill_filter_attr_and_op(f, context="event")

        # 2. Global Filters
        if "globalFilterRule" in params:
            for rule in params["globalFilterRule"]:
                if "filters" in rule:
                    for f in rule["filters"]:
                        self.fill_filter_attr_and_op(f, context="global")

        # 3. Group Rules
        if "groupRules" in params:
            for rule in params["groupRules"]:
                self.fill_group_attr(rule)
                
        return params

if __name__ == "__main__":
    # Test logic
    backfiller = ParamsBackfiller()
    
    # Mock input
    mock_params = {
        "groupId": "1",
        "date": {"isDynamic": True, "periods": []},
        "eventRules": [
            {
                "mark": "A",
                "alias": "直播送礼", 
                "eventId": "",
                "type": 1,
                "aggregate": {
                    "aggregateId": "sum", 
                    "attrId": "礼物数量"
                }
            }
        ],
        "globalFilterRule": [
            {
                "mark": "",
                "alias": "全体用户",
                "filters": [
                    {
                        "attrId": "状态",
                        "operation": "=",
                        "param": {"value1": "启用"}
                    }
                ]
            }
        ],
        "groupRules": [],
        "combineRules": []
    }
    
    print("Before:", json.dumps(mock_params, indent=2, ensure_ascii=False))
    filled = backfiller.fill(mock_params)
    print("After:", json.dumps(filled, indent=2, ensure_ascii=False))
