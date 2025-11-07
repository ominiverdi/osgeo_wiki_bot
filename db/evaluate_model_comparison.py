# analysis/evaluate_model_comparison.py
import json
import re
import statistics
from pathlib import Path
from collections import Counter
import sys

def load_results(filepath='model_comparison_results.json'):
    """Load comparison results from JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Error: {filepath} not found. Run test_models_comparison.py first.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: {filepath} is not valid JSON.")
        sys.exit(1)


def analyze_resume_quality(resume):
    """Analyze quality metrics for a resume."""
    if not resume:
        return {
            'length': 0,
            'has_bullets': False,
            'markdown_artifacts': 0,
            'escape_sequences': 0,
            'meta_text': 0,
            'duplicate_lines': 0,
            'is_error': True
        }
    
    metrics = {
        'length': len(resume),
        'has_bullets': bool(re.search(r'^\s*\*\s+', resume, re.MULTILINE)),
        'markdown_artifacts': len(re.findall(r'\*\*|##|```', resume)),
        'escape_sequences': len(re.findall(r'\\[xn0-9]|\\x[0-9a-f]{2}', resume)),
        'meta_text': len(re.findall(r'(?i)(okay|here\'s|this is|let me|i\'ve)', resume)),
        'duplicate_lines': count_duplicate_lines(resume),
        'is_error': 'error' in resume.lower()[:100]
    }
    
    return metrics


def count_duplicate_lines(text):
    """Count duplicate consecutive lines."""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    duplicates = 0
    seen = set()
    for line in lines:
        if line in seen:
            duplicates += 1
        seen.add(line)
    return duplicates


def analyze_keywords_quality(keywords):
    """Analyze quality metrics for keywords."""
    if not keywords:
        return {
            'count': 0,
            'unique_ratio': 0,
            'avg_length': 0,
            'has_meta_text': False,
            'has_artifacts': False,
            'is_error': True
        }
    
    # Split into individual keywords
    keyword_list = [k.strip() for k in keywords.split(',') if k.strip()]
    
    # Calculate uniqueness
    unique_keywords = set(k.lower() for k in keyword_list)
    unique_ratio = len(unique_keywords) / len(keyword_list) if keyword_list else 0
    
    # Average keyword length
    avg_length = statistics.mean([len(k) for k in keyword_list]) if keyword_list else 0
    
    metrics = {
        'count': len(keyword_list),
        'unique_ratio': unique_ratio,
        'avg_length': avg_length,
        'has_meta_text': bool(re.search(r'(?i)(okay|here\'s|extract)', keywords)),
        'has_artifacts': bool(re.search(r'\\[xn0-9]|\d+m', keywords)),
        'is_error': 'error' in keywords.lower()[:50]
    }
    
    return metrics


def calculate_quality_score(resume_metrics, keyword_metrics):
    """Calculate overall quality score (0-100)."""
    score = 100.0
    
    # Resume penalties
    if resume_metrics['is_error']:
        return 0
    if resume_metrics['length'] < 100:
        score -= 30
    elif resume_metrics['length'] > 2000:
        score -= 10
    
    if not resume_metrics['has_bullets']:
        score -= 10
    
    score -= resume_metrics['markdown_artifacts'] * 2
    score -= resume_metrics['escape_sequences'] * 3
    score -= resume_metrics['meta_text'] * 5
    score -= resume_metrics['duplicate_lines'] * 2
    
    # Keyword penalties
    if keyword_metrics['is_error']:
        return 0
    if keyword_metrics['count'] < 10:
        score -= 15
    elif keyword_metrics['count'] > 40:
        score -= 5
    
    if keyword_metrics['unique_ratio'] < 0.8:
        score -= (1 - keyword_metrics['unique_ratio']) * 20
    
    if keyword_metrics['has_meta_text']:
        score -= 10
    if keyword_metrics['has_artifacts']:
        score -= 10
    
    return max(0, min(100, score))


def analyze_model_results(results, model_name):
    """Analyze all results for a specific model."""
    model_data = []
    
    for page_result in results:
        # Find this model's result
        model_result = None
        for m in page_result.get('models', []):
            if m.get('model') == model_name:
                model_result = m
                break
        
        if not model_result:
            continue
        
        if 'error' in model_result:
            model_data.append({
                'page_title': page_result['page_title'],
                'error': True,
                'quality_score': 0
            })
            continue
        
        # Analyze quality
        resume_metrics = analyze_resume_quality(model_result.get('resume', ''))
        keyword_metrics = analyze_keywords_quality(model_result.get('keywords', ''))
        quality_score = calculate_quality_score(resume_metrics, keyword_metrics)
        
        model_data.append({
            'page_title': page_result['page_title'],
            'error': False,
            'resume_metrics': resume_metrics,
            'keyword_metrics': keyword_metrics,
            'quality_score': quality_score,
            'processing_time': model_result.get('total_processing_time', 0)
        })
    
    return model_data


def generate_summary(model_data, model_name):
    """Generate summary statistics for a model."""
    valid_data = [d for d in model_data if not d['error']]
    error_count = len([d for d in model_data if d['error']])
    
    if not valid_data:
        return {
            'model': model_name,
            'total_pages': len(model_data),
            'errors': error_count,
            'avg_quality_score': 0,
            'avg_processing_time': 0
        }
    
    quality_scores = [d['quality_score'] for d in valid_data]
    processing_times = [d['processing_time'] for d in valid_data]
    
    resume_lengths = [d['resume_metrics']['length'] for d in valid_data]
    keyword_counts = [d['keyword_metrics']['count'] for d in valid_data]
    
    # Count issues
    markdown_issues = sum(d['resume_metrics']['markdown_artifacts'] > 0 for d in valid_data)
    escape_issues = sum(d['resume_metrics']['escape_sequences'] > 0 for d in valid_data)
    meta_text_issues = sum(d['resume_metrics']['meta_text'] > 0 for d in valid_data)
    keyword_artifacts = sum(d['keyword_metrics']['has_artifacts'] for d in valid_data)
    
    return {
        'model': model_name,
        'total_pages': len(model_data),
        'successful': len(valid_data),
        'errors': error_count,
        'avg_quality_score': statistics.mean(quality_scores),
        'median_quality_score': statistics.median(quality_scores),
        'min_quality_score': min(quality_scores),
        'max_quality_score': max(quality_scores),
        'avg_processing_time': statistics.mean(processing_times),
        'median_processing_time': statistics.median(processing_times),
        'avg_resume_length': statistics.mean(resume_lengths),
        'avg_keyword_count': statistics.mean(keyword_counts),
        'issues': {
            'markdown_artifacts': markdown_issues,
            'escape_sequences': escape_issues,
            'meta_text': meta_text_issues,
            'keyword_artifacts': keyword_artifacts
        }
    }


def print_comparison_report(summary1, summary2):
    """Print formatted comparison report."""
    print("\n" + "="*80)
    print("MODEL COMPARISON REPORT")
    print("="*80)
    
    print(f"\n{'Metric':<35} {summary1['model']:<20} {summary2['model']:<20}")
    print("-"*80)
    
    # Success rate
    success1 = f"{summary1['successful']}/{summary1['total_pages']} ({summary1['successful']/summary1['total_pages']*100:.1f}%)"
    success2 = f"{summary2['successful']}/{summary2['total_pages']} ({summary2['successful']/summary2['total_pages']*100:.1f}%)"
    print(f"{'Success Rate':<35} {success1:<20} {success2:<20}")
    
    # Quality scores
    print(f"{'Average Quality Score':<35} {summary1['avg_quality_score']:<20.1f} {summary2['avg_quality_score']:<20.1f}")
    print(f"{'Median Quality Score':<35} {summary1['median_quality_score']:<20.1f} {summary2['median_quality_score']:<20.1f}")
    print(f"{'Quality Range':<35} {summary1['min_quality_score']:.0f}-{summary1['max_quality_score']:.0f}{'':<14} {summary2['min_quality_score']:.0f}-{summary2['max_quality_score']:.0f}")
    
    # Processing time
    print(f"{'Average Processing Time (s)':<35} {summary1['avg_processing_time']:<20.1f} {summary2['avg_processing_time']:<20.1f}")
    print(f"{'Median Processing Time (s)':<35} {summary1['median_processing_time']:<20.1f} {summary2['median_processing_time']:<20.1f}")
    
    # Content metrics
    print(f"{'Average Resume Length (chars)':<35} {summary1['avg_resume_length']:<20.0f} {summary2['avg_resume_length']:<20.0f}")
    print(f"{'Average Keyword Count':<35} {summary1['avg_keyword_count']:<20.1f} {summary2['avg_keyword_count']:<20.1f}")
    
    # Issues
    print(f"\n{'Quality Issues:':<35}")
    print(f"{'  Pages with Markdown Artifacts':<35} {summary1['issues']['markdown_artifacts']:<20} {summary2['issues']['markdown_artifacts']:<20}")
    print(f"{'  Pages with Escape Sequences':<35} {summary1['issues']['escape_sequences']:<20} {summary2['issues']['escape_sequences']:<20}")
    print(f"{'  Pages with Meta Text':<35} {summary1['issues']['meta_text']:<20} {summary2['issues']['meta_text']:<20}")
    print(f"{'  Pages with Keyword Artifacts':<35} {summary1['issues']['keyword_artifacts']:<20} {summary2['issues']['keyword_artifacts']:<20}")
    
    # Recommendation
    print("\n" + "="*80)
    print("RECOMMENDATION")
    print("="*80)
    
    winner = summary1 if summary1['avg_quality_score'] > summary2['avg_quality_score'] else summary2
    loser = summary2 if winner == summary1 else summary1
    
    quality_diff = abs(winner['avg_quality_score'] - loser['avg_quality_score'])
    speed_diff = abs(winner['avg_processing_time'] - loser['avg_processing_time'])
    
    print(f"\nBest Quality: {winner['model']}")
    print(f"  - {quality_diff:.1f} points higher quality score")
    print(f"  - {'Faster' if winner['avg_processing_time'] < loser['avg_processing_time'] else 'Slower'} by {speed_diff:.1f}s per page")
    
    if quality_diff > 10:
        print(f"\n✓ STRONG RECOMMENDATION: Use {winner['model']}")
        print(f"  Quality difference is significant ({quality_diff:.1f} points)")
    elif quality_diff > 5:
        print(f"\n✓ RECOMMENDATION: Use {winner['model']}")
        print(f"  Moderately better quality ({quality_diff:.1f} points)")
    else:
        print(f"\n≈ MARGINAL: Both models perform similarly")
        faster = summary1 if summary1['avg_processing_time'] < summary2['avg_processing_time'] else summary2
        print(f"  Consider {faster['model']} for speed ({faster['avg_processing_time']:.1f}s vs {loser['avg_processing_time']:.1f}s)")
    
    print("\n" + "="*80)


def print_worst_pages(model_data, model_name, count=5):
    """Print worst performing pages for a model."""
    valid_data = [d for d in model_data if not d['error']]
    worst = sorted(valid_data, key=lambda x: x['quality_score'])[:count]
    
    print(f"\n{model_name} - Worst {count} Pages:")
    print("-"*80)
    for i, page in enumerate(worst, 1):
        print(f"{i}. {page['page_title'][:60]}")
        print(f"   Quality Score: {page['quality_score']:.1f}/100")
        print(f"   Resume Length: {page['resume_metrics']['length']} chars")
        print(f"   Keywords: {page['keyword_metrics']['count']}")
        if page['resume_metrics']['markdown_artifacts'] > 0:
            print(f"   ⚠ Markdown artifacts: {page['resume_metrics']['markdown_artifacts']}")
        if page['resume_metrics']['escape_sequences'] > 0:
            print(f"   ⚠ Escape sequences: {page['resume_metrics']['escape_sequences']}")
        if page['resume_metrics']['meta_text'] > 0:
            print(f"   ⚠ Meta text occurrences: {page['resume_metrics']['meta_text']}")


def main():
    """Main evaluation function."""
    print("Loading comparison results...")
    data = load_results()
    
    config = data['test_config']
    results = data['results']
    
    print(f"Loaded {len(results)} page results")
    print(f"Models tested: {', '.join(config['models'])}")
    print(f"Test date: {config['timestamp']}")
    
    # Analyze each model
    print("\nAnalyzing results...")
    model1_data = analyze_model_results(results, config['models'][0])
    model2_data = analyze_model_results(results, config['models'][1])
    
    # Generate summaries
    summary1 = generate_summary(model1_data, config['models'][0])
    summary2 = generate_summary(model2_data, config['models'][1])
    
    # Print report
    print_comparison_report(summary1, summary2)
    
    # Show worst performers
    print_worst_pages(model1_data, config['models'][0], count=3)
    print_worst_pages(model2_data, config['models'][1], count=3)
    
    print("\n" + "="*80)
    print("Evaluation complete!")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()