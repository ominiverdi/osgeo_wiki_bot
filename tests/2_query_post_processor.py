# tests/3_apply_post_processor.py
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Union, Optional

# Official categories - ensure these match exactly with your production list
OFFICIAL_CATEGORIES = [
    "OSGeo Member", "Board", "FOSS4G", "Incubation", 
    "Past Events", "Education", "Local Chapters", "Infrastructure",
    "Code Sprints", "Events", "Marketing", "Conference Committee",
    "Advocacy", "Journal", "OSGeoLive", "Projects"
]

class QueryPostProcessor:
    """Post-processes LLM-generated query understanding results."""
    
    def __init__(self, official_categories: Optional[List[str]] = None):
        """Initialize with optional custom category list."""
        self.official_categories = official_categories or OFFICIAL_CATEGORIES
    
    def process(self, query: str, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """Apply all post-processing steps to LLM result."""
        # Create a copy to avoid modifying the original
        processed = llm_result.copy()
        
        # Apply each correction in sequence
        processed = self._validate_categories(processed)
        processed = self._enhance_temporal_queries(query, processed)
        processed = self._clean_quotations(query, processed)
        
        return processed
    
    def _validate_categories(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure only official categories are used."""
        if "categories" not in result:
            result["categories"] = []
            return result
        
        # Filter categories to only include official ones
        valid_categories = []
        for category in result["categories"]:
            # Try exact match first
            if category in self.official_categories:
                valid_categories.append(category)
                continue
                
            # Try case-insensitive match
            for official in self.official_categories:
                if official.lower() == category.lower():
                    valid_categories.append(official)  # Use the official spelling
                    break
                    
            # Try fuzzy match for close variations
            for official in self.official_categories:
                # Simple similarity check - if the official category is contained in the result
                if official.lower() in category.lower() or category.lower() in official.lower():
                    if official not in valid_categories:
                        valid_categories.append(official)
                        break
        
        # Ensure we have at least one category if available
        if not valid_categories and self.official_categories:
            if result.get("query_type") == "temporal" or "time" in result.get("query_type", "").lower():
                valid_categories.append("Past Events")
            elif "project" in result.get("query_type", "").lower():
                valid_categories.append("Projects")
        
        result["categories"] = valid_categories
        return result
    
    def _enhance_temporal_queries(self, query: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance temporal queries with appropriate year patterns."""
        if result.get("query_type") != "temporal" or "keyword_tiers" not in result:
            return result
            
        # Get current year
        current_year = datetime.now().year
        
        # Check if this is a "next" or "upcoming" query
        is_next_query = any(word in query.lower() for word in ["next", "upcoming", "future", "scheduled"])
        is_last_query = any(word in query.lower() for word in ["last", "previous", "recent"])
        is_first_query = any(word in query.lower() for word in ["first", "initial", "earliest", "beginning"])
        
        # Clone the tiers to avoid modifying the original
        tiers = [tier.copy() for tier in result["keyword_tiers"]]
        
        if is_next_query:
            # Check if we already have future years
            has_future_years = False
            future_years = [str(current_year), str(current_year + 1), str(current_year + 2)]
            
            for tier in tiers:
                for keyword in tier:
                    if any(year in keyword for year in future_years):
                        has_future_years = True
                        break
            
            # If no future years found, add them to the first tier
            if not has_future_years and tiers:
                entity = query.split()[-1] if query else "FOSS4G"  # Extract entity from query
                entity = entity.strip("?.,!").upper()  # Clean up and normalize
                if not any(c.isalpha() for c in entity):
                    entity = "FOSS4G"  # Fallback if no letters
                
                # Add future years to first tier
                future_keywords = [f"{entity} {current_year + i}" for i in range(3)]
                tiers[0].extend(future_keywords)
                
        elif is_first_query:
            # Ensure we have "first", "founding", "inaugural" terms for first queries
            first_terms = ["first", "founding", "inaugural", "origin", "beginning"]
            
            # Check if we already have first-related terms
            has_first_terms = False
            
            for tier in tiers:
                for keyword in tier:
                    if any(term in keyword.lower() for term in first_terms):
                        has_first_terms = True
                        break
            
            # If no first terms found, add them to the first tier
            if not has_first_terms and tiers:
                entity = query.split()[-1] if query else "FOSS4G"  # Extract entity from query
                entity = entity.strip("?.,!").upper()  # Clean up and normalize
                
                # Add first terms to first tier
                first_keywords = [f"first {entity}", f"inaugural {entity}", f"{entity} origin"]
                tiers[0].extend(first_keywords)
                
        elif is_last_query:
            # Check if we already have recent years
            has_recent_years = False
            recent_years = [str(current_year), str(current_year - 1), str(current_year - 2)]
            
            for tier in tiers:
                for keyword in tier:
                    if any(year in keyword for year in recent_years):
                        has_recent_years = True
                        break
            
            # If no recent years found, add them to the first tier
            if not has_recent_years and tiers:
                entity = query.split()[-1] if query else "FOSS4G"  # Extract entity from query
                entity = entity.strip("?.,!").upper()  # Clean up and normalize
                
                # Add recent years to first tier
                recent_keywords = [f"{entity} {current_year - i}" for i in range(3)]
                tiers[0].extend(recent_keywords)
        
        # Update the result with enhanced tiers
        result["keyword_tiers"] = tiers
        return result
    
    def _clean_quotations(self, query: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Clean up problematic quotations in keywords."""
        if "keyword_tiers" not in result:
            return result
            
        # Clone the tiers to avoid modifying the original
        tiers = []
        
        for tier in result["keyword_tiers"]:
            cleaned_tier = []
            for keyword in tier:
                # Remove quotes if they contain the exact query
                if keyword.lower().replace('"', '').strip() == query.lower():
                    keyword = query.split()[-1] if len(query.split()) > 1 else query
                
                # Remove quotes around very long phrases (likely full questions)
                if keyword.startswith('"') and keyword.endswith('"'):
                    content = keyword[1:-1]  # Remove surrounding quotes
                    if len(content.split()) > 5:  # If more than 5 words
                        keyword = content
                        
                        # Extract 2-3 key terms from the long phrase
                        words = content.split()
                        important_words = [w for w in words if len(w) > 3 and w.lower() not in ["what", "when", "where", "who", "how", "does", "is", "are", "was", "were"]]
                        if important_words:
                            keyword = " ".join(important_words[:3])  # Take up to 3 important words
                
                # Still add the cleaned keyword if it's non-empty
                if keyword.strip():
                    cleaned_tier.append(keyword.strip())
            
            # Ensure we don't have empty tiers
            if cleaned_tier:
                tiers.append(cleaned_tier)
        
        # Ensure we have at least one tier with at least one keyword
        if not tiers:
            # Extract main terms from query for fallback
            words = query.split()
            fallback = [w for w in words if len(w) > 3 and w.lower() not in ["what", "when", "where", "who", "how", "does", "is", "are", "was", "were"]]
            if not fallback:
                fallback = [words[-1]] if words else ["OSGeo"]
            tiers = [fallback]
            
        # Update the result with cleaned tiers
        result["keyword_tiers"] = tiers
        return result


def main():
    # Path to the input file
    input_file = "query_understanding_results.json"
    
    # Path to the output file
    output_file = "processed_query_results.json"
    
    # Load the original results
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            query_results = json.load(f)
        print(f"Loaded {len(query_results)} results from {input_file}")
    except Exception as e:
        print(f"Error loading input file: {e}")
        return
    
    # Initialize the post-processor
    processor = QueryPostProcessor()
    
    # Process each result
    processed_results = []
    for item in query_results:
        query = item["query"]
        original_result = item["result"]
        
        # Process the result
        processed = processor.process(query, original_result)
        
        # Add to the processed results
        processed_results.append({
            "query": query,
            "original_result": original_result,
            "processed_result": processed
        })
        
        # Print a summary of changes
        print(f"\nProcessing: {query}")
        
        # Compare categories
        orig_cats = original_result.get("categories", [])
        proc_cats = processed.get("categories", [])
        if set(orig_cats) != set(proc_cats):
            print(f"  Categories changed: {orig_cats} → {proc_cats}")
        
        # Compare keyword tiers
        if "keyword_tiers" in original_result and "keyword_tiers" in processed:
            orig_tiers = original_result["keyword_tiers"]
            proc_tiers = processed["keyword_tiers"]
            
            if len(orig_tiers) != len(proc_tiers):
                print(f"  Tier count changed: {len(orig_tiers)} → {len(proc_tiers)}")
            
            # Check first tier for significant changes
            if orig_tiers and proc_tiers:
                if set(orig_tiers[0]) != set(proc_tiers[0]):
                    print(f"  First tier changed: {orig_tiers[0]} → {proc_tiers[0]}")
    
    # Save the processed results
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(processed_results, f, indent=2)
        print(f"\nSaved processed results to {output_file}")
    except Exception as e:
        print(f"Error saving output file: {e}")
        return
    
    # Print overall summary
    print("\nProcessing Summary:")
    print(f"  Total queries processed: {len(processed_results)}")
    
    # Count significant changes
    category_changes = sum(1 for item in processed_results 
                          if set(item["original_result"].get("categories", [])) != 
                             set(item["processed_result"].get("categories", [])))
    
    tier_changes = sum(1 for item in processed_results 
                      if "keyword_tiers" in item["original_result"] and 
                         "keyword_tiers" in item["processed_result"] and
                         (len(item["original_result"]["keyword_tiers"]) != len(item["processed_result"]["keyword_tiers"]) or
                          (item["original_result"]["keyword_tiers"] and item["processed_result"]["keyword_tiers"] and
                           set(item["original_result"]["keyword_tiers"][0]) != set(item["processed_result"]["keyword_tiers"][0]))))
    
    print(f"  Queries with category changes: {category_changes}")
    print(f"  Queries with keyword tier changes: {tier_changes}")

if __name__ == "__main__":
    main()