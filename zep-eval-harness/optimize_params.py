"""
Multi-threaded Parameter Optimization Script
Tests multiple configurations in parallel to find optimal settings.
"""
import asyncio
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess

# Parameter grid to test
PARAM_GRID = [
    # (facts, entities, episodes) - focusing on hard questions
    (25, 15, 5),   # Balanced
    (30, 12, 5),   # More facts
    (35, 10, 5),   # Even more facts
    (40, 8, 3),    # Heavy facts focus
    (50, 5, 0),    # Maximum facts, no episodes
    (30, 20, 0),   # More entities
    (25, 25, 0),   # Equal facts/entities
    (45, 5, 5),    # Heavy facts, some episodes
]

def run_evaluation_with_params(facts_limit, entities_limit, episodes_limit):
    """Run evaluation with specific parameters."""
    print(f"\n{'='*80}")
    print(f"Testing: FACTS={facts_limit}, ENTITIES={entities_limit}, EPISODES={episodes_limit}")
    print(f"{'='*80}")
    
    # Modify the zep_evaluate.py file
    with open("zep_evaluate.py", "r") as f:
        content = f.read()
    
    # Replace the limits
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        if line.startswith('FACTS_LIMIT ='):
            new_lines.append(f'FACTS_LIMIT = {facts_limit}      # Optimized by grid search')
        elif line.startswith('ENTITIES_LIMIT ='):
            new_lines.append(f'ENTITIES_LIMIT = {entities_limit}   # Optimized by grid search')
        elif line.startswith('EPISODES_LIMIT ='):
            new_lines.append(f'EPISODES_LIMIT = {episodes_limit}    # Optimized by grid search')
        else:
            new_lines.append(line)
    
    modified_content = '\n'.join(new_lines)
    
    with open("zep_evaluate.py", "w") as f:
        f.write(modified_content)
    
    # Run evaluation
    try:
        result = subprocess.run(
            ["uv", "run", "zep_evaluate.py"],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        # Parse results from the last evaluation file
        import glob
        eval_files = glob.glob("runs/*/evaluation_results_*.json")
        if eval_files:
            latest_file = max(eval_files, key=os.path.getctime)
            with open(latest_file, 'r') as f:
                results = json.load(f)
            
            # Extract hard category accuracy
            hard_accuracy = results['category_scores']['hard']['accuracy']['accuracy_rate']
            
            print(f"✓ FACTS={facts_limit}, ENTITIES={entities_limit}, EPISODES={episodes_limit}")
            print(f"  Hard Accuracy: {hard_accuracy:.2f}%")
            
            return {
                'facts': facts_limit,
                'entities': entities_limit,
                'episodes': episodes_limit,
                'hard_accuracy': hard_accuracy,
                'results_file': latest_file,
                'completeness': results['category_scores']['hard']['completeness']['complete_rate'],
                'overall_accuracy': results['aggregate_scores']['accuracy']['accuracy_rate']
            }
    except Exception as e:
        print(f"✗ Error with FACTS={facts_limit}, ENTITIES={entities_limit}, EPISODES={episodes_limit}: {e}")
        return None

def main():
    print("="*80)
    print("PARAMETER GRID SEARCH - OPTIMIZING FOR HARD CATEGORY ACCURACY")
    print("="*80)
    print(f"\nTesting {len(PARAM_GRID)} configurations...")
    print(f"This will take approximately {len(PARAM_GRID) * 3} minutes\n")
    
    results = []
    
    # Run evaluations sequentially (parallel would conflict with file writes)
    for params in PARAM_GRID:
        result = run_evaluation_with_params(*params)
        if result:
            results.append(result)
    
    # Sort by hard accuracy
    results.sort(key=lambda x: x['hard_accuracy'], reverse=True)
    
    # Print summary
    print("\n" + "="*80)
    print("OPTIMIZATION RESULTS (Sorted by Hard Category Accuracy)")
    print("="*80)
    print(f"\n{'Rank':<6}{'Facts':<8}{'Entities':<10}{'Episodes':<10}{'Hard %':<10}{'Complete %':<12}{'Overall %'}")
    print("-"*80)
    
    for i, result in enumerate(results, 1):
        print(f"{i:<6}{result['facts']:<8}{result['entities']:<10}{result['episodes']:<10}"
              f"{result['hard_accuracy']:<10.2f}{result['completeness']:<12.2f}{result['overall_accuracy']:.2f}")
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    output_file = f"optimization_results_{timestamp}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✓ Results saved to: {output_file}")
    
    # Apply best configuration
    if results:
        best = results[0]
        print(f"\n{'='*80}")
        print(f"BEST CONFIGURATION FOUND:")
        print(f"{'='*80}")
        print(f"FACTS_LIMIT = {best['facts']}")
        print(f"ENTITIES_LIMIT = {best['entities']}")
        print(f"EPISODES_LIMIT = {best['episodes']}")
        print(f"Hard Category Accuracy: {best['hard_accuracy']:.2f}%")
        print(f"Context Completeness: {best['completeness']:.2f}%")
        
        # Apply best settings
        with open("zep_evaluate.py", "r") as f:
            content = f.read()
        
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            if line.startswith('FACTS_LIMIT ='):
                new_lines.append(f'FACTS_LIMIT = {best["facts"]}      # OPTIMIZED - Best from grid search')
            elif line.startswith('ENTITIES_LIMIT ='):
                new_lines.append(f'ENTITIES_LIMIT = {best["entities"]}   # OPTIMIZED - Best from grid search')
            elif line.startswith('EPISODES_LIMIT ='):
                new_lines.append(f'EPISODES_LIMIT = {best["episodes"]}    # OPTIMIZED - Best from grid search')
            else:
                new_lines.append(line)
        
        with open("zep_evaluate.py", "w") as f:
            f.write('\n'.join(new_lines))
        
        print(f"\n✓ Best configuration applied to zep_evaluate.py")

if __name__ == "__main__":
    main()

