"""
Zep Evaluation Script
Combines graph search, AI response generation, and evaluation into a single pipeline.
"""

import os
import sys
import json
import glob
import asyncio
import statistics
from time import time
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from openai import RateLimitError, APIError
from zep_cloud.client import AsyncZep

# ============================================================================
# Configuration Constants
# ============================================================================

# OK to change - Search configuration
FACTS_LIMIT = 5  # Number of facts (edges) to return
ENTITIES_LIMIT = 5  # Number of entities (nodes) to return
EPISODES_LIMIT = 5  # Number of episodes to return (when enabled)

# DO NOT CHANGE - Context truncation and latency configuration
CONTEXT_CHAR_LIMIT = 2000  # Maximum characters for context block (0 = no limit)
CONTEXT_LATENCY_LIMIT_MS = 2000  # Maximum milliseconds for context construction (0 = no limit)

# DO NOT CHANGE - LLM Model configuration
LLM_RESPONSE_MODEL = "gpt-5-mini"  # Model used for generating responses
LLM_JUDGE_MODEL = "gpt-5-mini"  # Model used for grading responses


# ============================================================================
# OpenAI API Retry Logic with Exponential Backoff
# ============================================================================


async def retry_with_exponential_backoff(
    func,
    max_retries: int = 6,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    max_total_wait: float = 60.0,
    *args,
    **kwargs
):
    """
    Retry an async function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts (default: 6)
        initial_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay between retries in seconds (default: 60.0)
        max_total_wait: Maximum total wait time across all retries (default: 60.0)
        *args, **kwargs: Arguments to pass to the function

    Returns:
        Result from the function call

    Raises:
        The last exception encountered if all retries fail
    """
    import random

    total_wait_time = 0.0
    last_exception = None

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except RateLimitError as e:
            last_exception = e
            if attempt == max_retries - 1:
                print(f"❌ OpenAI API rate limit: All {max_retries} retry attempts exhausted")
                raise

            # Calculate exponential backoff with jitter
            delay = min(initial_delay * (2 ** attempt), max_delay)
            # Add random jitter (±25% of delay)
            jitter = delay * (0.75 + random.random() * 0.5)

            # Check if we would exceed max total wait time
            if total_wait_time + jitter > max_total_wait:
                remaining_time = max_total_wait - total_wait_time
                if remaining_time > 0:
                    print(f"⏱️  OpenAI rate limit hit. Waiting {remaining_time:.1f}s (max time reached)")
                    await asyncio.sleep(remaining_time)
                print(f"❌ OpenAI API rate limit: Maximum wait time of {max_total_wait}s exceeded")
                raise

            print(f"⚠️  OpenAI rate limit hit (attempt {attempt + 1}/{max_retries}). Retrying in {jitter:.1f}s...")
            await asyncio.sleep(jitter)
            total_wait_time += jitter

        except APIError as e:
            last_exception = e
            if attempt == max_retries - 1:
                print(f"❌ OpenAI API error: All {max_retries} retry attempts exhausted")
                raise

            # For API errors, use a shorter backoff
            delay = min(initial_delay * (2 ** attempt) * 0.5, max_delay * 0.5)
            jitter = delay * (0.75 + random.random() * 0.5)

            if total_wait_time + jitter > max_total_wait:
                remaining_time = max_total_wait - total_wait_time
                if remaining_time > 0:
                    print(f"⏱️  OpenAI API error. Waiting {remaining_time:.1f}s (max time reached)")
                    await asyncio.sleep(remaining_time)
                print(f"❌ OpenAI API error: Maximum wait time of {max_total_wait}s exceeded")
                raise

            print(f"⚠️  OpenAI API error (attempt {attempt + 1}/{max_retries}): {str(e)}. Retrying in {jitter:.1f}s...")
            await asyncio.sleep(jitter)
            total_wait_time += jitter

    # This should never be reached, but just in case
    if last_exception:
        raise last_exception


# ============================================================================
# Data Models
# ============================================================================


class Grade(BaseModel):
    """Pydantic model for structured LLM grading output."""

    correct: bool = Field(description="True if the answer is correct, False otherwise")
    reasoning: str = Field(
        description="Explain why the answer meets or fails to meet the criteria."
    )


class CompletenessGrade(BaseModel):
    """Pydantic model for evaluating context completeness."""

    completeness: str = Field(description="COMPLETE, PARTIAL, or INSUFFICIENT")
    reasoning: str = Field(
        description="Explain why the context is sufficient or what is missing."
    )
    missing_elements: List[str] = Field(
        default_factory=list, description="List of missing information elements"
    )
    present_elements: List[str] = Field(
        default_factory=list,
        description="List of information elements found in context",
    )


# ============================================================================
# Step 1: Load Run Manifest and Test Cases
# ============================================================================


def get_latest_run() -> Optional[Tuple[int, str]]:
    """
    Get the latest run number and directory.
    Returns tuple of (run_number, run_dir) or None if no runs exist.
    Format: runs/{number}_{ISO8601_timestamp}/
    """
    existing_runs = glob.glob("runs/*")

    if not existing_runs:
        return None

    # Filter out non-directories and .gitkeep
    existing_runs = [r for r in existing_runs if os.path.isdir(r)]

    if not existing_runs:
        return None

    # Sort by directory name (which includes timestamp)
    existing_runs.sort(reverse=True)
    latest_run_dir = existing_runs[0]

    # Extract run number (format: runs/1_timestamp)
    try:
        dir_name = os.path.basename(latest_run_dir)
        run_num = int(dir_name.split("_")[0])
        return run_num, latest_run_dir
    except (IndexError, ValueError):
        return None


def load_run_manifest(run_number: Optional[int] = None) -> Tuple[Dict[str, Any], str]:
    """
    Load the run manifest for evaluation.
    If run_number is None, loads the latest run.
    Returns tuple of (manifest, run_dir).
    """
    if run_number is None:
        result = get_latest_run()
        if result is None:
            raise FileNotFoundError(
                "No runs found in runs/ directory. Please run zep_ingest.py first."
            )
        run_number, run_dir = result
        print(f"Using latest run: #{run_number}")
    else:
        # Find run directory by number (format: runs/{number}_timestamp)
        matching_runs = glob.glob(f"runs/{run_number}_*")
        if not matching_runs:
            raise FileNotFoundError(f"Run #{run_number} not found in runs/ directory.")
        run_dir = matching_runs[0]
        print(f"Using run: #{run_number}")

    manifest_path = os.path.join(run_dir, "manifest.json")
    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    print(f"Loaded manifest from: {manifest_path}")
    print(f"Users: {len(manifest['users'])}")
    print(f"Timestamp: {manifest['timestamp']}\n")

    return manifest, run_dir


async def load_all_test_cases() -> Dict[str, List[Dict[str, Any]]]:
    """
    Load all test case files from data/test_cases/ directory.
    Returns dict mapping user_id to list of test cases.
    """
    test_case_files = glob.glob("data/test_cases/*_tests.json")

    if not test_case_files:
        raise FileNotFoundError("No test case files found in data/test_cases/")

    all_test_cases = {}

    for file_path in test_case_files:
        with open(file_path, "r") as f:
            data = json.load(f)
            user_id = data.get("user_id")
            test_cases = data.get("test_cases", [])

            if user_id and test_cases:
                all_test_cases[user_id] = test_cases

    total_tests = sum(len(tests) for tests in all_test_cases.values())
    print(f"✓ Loaded {total_tests} test case(s) for {len(all_test_cases)} user(s)\n")

    return all_test_cases


# ============================================================================
# Step 2: Graph Search
# ============================================================================


async def _perform_graph_search(
    zep_client: AsyncZep, user_id: str, query: str, include_episodes: bool = True
) -> Dict[str, Any]:
    """
    Internal helper: Perform parallel graph search across nodes and edges, optionally including episodes.
    Uses cross-encoder reranker for best accuracy.

    Args:
        zep_client: AsyncZep client instance
        user_id: User ID for graph search
        query: Search query string
        include_episodes: Whether to search episodes (default: False)

    Returns:
        Dictionary containing search results for all scopes
    """
    print(f"Searching [{user_id}]: '{query}'")

    # Search nodes and edges (facts and entities)
    nodes_task = zep_client.graph.search(
        user_id=user_id,
        query=query,
        scope="nodes",
        limit=ENTITIES_LIMIT,
        reranker="cross_encoder",
    )

    edges_task = zep_client.graph.search(
        user_id=user_id,
        query=query,
        scope="edges",
        limit=FACTS_LIMIT,
        reranker="cross_encoder",
    )

    # Optionally search episodes
    if include_episodes:
        episodes_task = zep_client.graph.search(
            user_id=user_id,
            query=query,
            scope="episodes",
            limit=EPISODES_LIMIT,
            reranker="cross_encoder",
        )
        nodes_result, edges_result, episodes_result = await asyncio.gather(
            nodes_task, edges_task, episodes_task
        )
        return {
            "episodes": episodes_result,
            "nodes": nodes_result,
            "edges": edges_result,
        }
    else:
        nodes_result, edges_result = await asyncio.gather(nodes_task, edges_task)
        return {"episodes": None, "nodes": nodes_result, "edges": edges_result}


def _format_search_results(search_results: Dict[str, Any]) -> str:
    """
    Internal helper: Format graph search results into a context block string.

    Args:
        search_results: Dictionary containing episodes, nodes, and edges

    Returns:
        Formatted context block string for LLM consumption
    """
    context_parts = []

    has_episodes = search_results.get("episodes") is not None

    # Header
    if has_episodes:
        context_parts.append(
            "FACTS, ENTITIES, and EPISODES represent relevant context to the current conversation.\n"
        )
    else:
        context_parts.append(
            "FACTS and ENTITIES represent relevant context to the current conversation.\n"
        )

    # Facts section (edges with temporal validity, labels, and attributes)
    context_parts.append("# These are the most relevant facts")
    context_parts.append('# Facts ending in "present" are currently valid')
    context_parts.append("# Facts with a past end date are NO LONGER VALID.")
    context_parts.append("<FACTS>")

    edges = getattr(search_results["edges"], "edges", [])
    if edges:
        for edge in edges:
            fact = getattr(edge, "fact", "No fact available")
            valid_at = getattr(edge, "valid_at", None)
            invalid_at = getattr(edge, "invalid_at", None)
            labels = getattr(edge, "labels", None)
            attributes = getattr(edge, "attributes", None)

            # Format temporal validity
            valid_at_str = valid_at if valid_at else "unknown"
            invalid_at_str = invalid_at if invalid_at else "present"

            context_parts.append(
                f"{fact} (Date range: {valid_at_str} - {invalid_at_str})"
            )

            # Add labels if present
            if labels and len(labels) > 0:
                context_parts.append(f"  Labels: {', '.join(labels)}")

            # Add attributes if present
            if attributes and isinstance(attributes, dict) and len(attributes) > 0:
                context_parts.append(f"  Attributes:")
                for attr_name, attr_value in attributes.items():
                    context_parts.append(f"    {attr_name}: {attr_value}")

            context_parts.append("")  # Blank line between facts
    else:
        context_parts.append("No relevant facts found")

    context_parts.append("</FACTS>\n")

    # Entities section (nodes with labels and attributes)
    context_parts.append(
        "# These are the most relevant entities (people, locations, organizations, items, and more)."
    )
    context_parts.append("<ENTITIES>")

    nodes = getattr(search_results["nodes"], "nodes", [])
    if nodes:
        for node in nodes:
            name = getattr(node, "name", "Unknown")
            labels = getattr(node, "labels", None)
            attributes = getattr(node, "attributes", None)
            summary = getattr(node, "summary", "No summary available")

            context_parts.append(f"Name: {name}")

            # Add labels if present, filtering out generic "Entity" label when multiple labels exist
            if labels and len(labels) > 0:
                filtered_labels = (
                    [l for l in labels if l != "Entity"] if len(labels) > 1 else labels
                )
                if filtered_labels:
                    context_parts.append(f"Labels: {', '.join(filtered_labels)}")

            # Add attributes if present
            if attributes and isinstance(attributes, dict) and len(attributes) > 0:
                context_parts.append(f"Attributes:")
                for attr_name, attr_value in attributes.items():
                    context_parts.append(f"  {attr_name}: {attr_value}")

            context_parts.append(f"Summary: {summary}")
            context_parts.append("")  # Blank line between entities
    else:
        context_parts.append("No relevant entities found")

    context_parts.append("</ENTITIES>")

    # Episodes section (optional)
    if has_episodes:
        context_parts.append("\n# These are the most relevant episodes")
        context_parts.append("<EPISODES>")

        episodes = getattr(search_results["episodes"], "episodes", [])
        if episodes:
            for episode in episodes:
                content = getattr(episode, "content", "No content available")
                created_at = getattr(episode, "created_at", "Unknown date")
                context_parts.append(f"({created_at}) {content}")
        else:
            context_parts.append("No relevant episodes found")

        context_parts.append("</EPISODES>")

    return "\n".join(context_parts)


async def construct_context_block(
    zep_client: AsyncZep, user_id: str, query: str, include_episodes: bool = True
) -> str:
    """
    Construct a context block by performing graph search and formatting results.
    This is the main entry point for context construction.

    Args:
        zep_client: AsyncZep client instance
        user_id: User ID for graph search
        query: Search query string
        include_episodes: Whether to search episodes (default: True)

    Returns:
        Formatted context block string for LLM consumption
    """
    search_results = await _perform_graph_search(
        zep_client, user_id, query, include_episodes
    )
    return _format_search_results(search_results)


# ============================================================================
# Step 3: Generate AI Response
# ============================================================================


def extract_assistant_answer(response) -> str:
    texts = []
    for item in getattr(response, "output", []) or []:
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", None) == "output_text":
                texts.append(getattr(block, "text", ""))
    return "\n".join(filter(None, texts)).strip()


async def generate_ai_response(
    openai_client: AsyncOpenAI, context: str, question: str
) -> Tuple[str, int, int]:
    """
    Generate an answer to a question using the provided Zep context.

    Args:
        openai_client: AsyncOpenAI client instance
        context: Retrieved context from Zep graph search
        question: Question to answer

    Returns:
        Tuple of (AI-generated answer string, input token count, output token count)
    """
    system_prompt = f"""
You are an intelligent AI assistant helping a user with their questions.

You have access to the user's conversation history and relevant information in the CONTEXT.

<CONTEXT>
{context}
</CONTEXT>

Using only the information in the CONTEXT, answer the user's questions. Keep responses SHORT - one sentence when possible.
"""

    async def _make_request():
        return await openai_client.responses.create(
            model=LLM_RESPONSE_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            reasoning=(
                {"effort": "medium"} if LLM_RESPONSE_MODEL.startswith("gpt-5") else None
            ),
            temperature=0.0 if not LLM_RESPONSE_MODEL.startswith("gpt-5") else None,
        )

    response = await retry_with_exponential_backoff(_make_request)

    # Extract token usage
    input_tokens = response.usage.input_tokens if response.usage else 0
    output_tokens = response.usage.output_tokens if response.usage else 0

    return extract_assistant_answer(response) or "", input_tokens, output_tokens


# ============================================================================
# Step 4: Grade AI Response
# ============================================================================


async def grade_ai_response(
    openai_client: AsyncOpenAI, question: str, golden_answer: str, ai_response: str
) -> Tuple[bool, str, int, int]:
    """
    Grade an AI response against golden answer using an LLM judge.

    Args:
        openai_client: AsyncOpenAI client instance
        question: The original question
        golden_answer: The expected correct answer
        ai_response: The AI-generated response to evaluate

    Returns:
        Tuple of (is_correct: bool, reasoning: str, input tokens: int, output tokens: int)
    """
    system_prompt = """
You are an expert grader that determines if AI responses are correct.
"""

    grading_prompt = f"""
I will give you a question, the golden (correct) answer, and an AI-generated response.

Please evaluate if the response is semantically equivalent to the golden answer. Return true ONLY if the response contains ALL the essential information from the golden answer.

<QUESTION>
{question}
</QUESTION>

<GOLDEN ANSWER>
{golden_answer}
</GOLDEN ANSWER>

<AI RESPONSE>
{ai_response}
</AI RESPONSE>

Evaluation Guidelines:
- The response must contain ALL key information from the golden answer (names, locations, actions, etc.)
- The response doesn't need to match exact wording, but must not omit or change critical details
- If the golden answer specifies a specific name, the response must include that name, not a generic term.
- Some variation is allowed for commonly acceptable names e.g. NYC or New York may be used to refer to New York City
- If the golden answer includes specific details (location, times, etc.), those must be present
- If the response is missing ANY critical information from the golden answer, return false
- If the response adds conversational filler but contains all essential info, return true
- If the response abstains from answering or says it doesn't know, return false

Examples of INCORRECT responses:
- Golden includes a specific person's name → Response uses a generic role/relationship term instead
- Golden includes a specific location → Response omits the location or uses a generic term
- Golden includes a complete message → Response omits part of the message

Examples of CORRECT responses:
- Golden and response have same key information with different wording
- Golden and response have same key information with different, but commonly acceptable names e.g. NYC or New York may be used to refer to New York City
- Response adds conversational elements but preserves all essential details from golden answer

Please provide your evaluation:
"""

    async def _make_request():
        return await openai_client.responses.parse(
            model=LLM_JUDGE_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": grading_prompt},
            ],
            text_format=Grade,
            reasoning=({"effort": "low"} if LLM_JUDGE_MODEL.startswith("gpt-5") else None),
            temperature=0.0 if not LLM_JUDGE_MODEL.startswith("gpt-5") else None,
        )

    response = await retry_with_exponential_backoff(_make_request)

    result = response.output_parsed

    # Extract token usage
    input_tokens = response.usage.input_tokens if response.usage else 0
    output_tokens = response.usage.output_tokens if response.usage else 0

    return result.correct, result.reasoning, input_tokens, output_tokens


# ============================================================================
# Step 4b: Evaluate Context Completeness (PRIMARY METRIC)
# ============================================================================


async def evaluate_context_completeness(
    openai_client: AsyncOpenAI, question: str, golden_answer: str, context: str
) -> Tuple[str, str, List[str], List[str], int, int]:
    """
    Evaluate whether the retrieved context contains adequate information to answer the question.
    This is the PRIMARY evaluation metric - assessing context quality independent of the AI's answer.

    Args:
        openai_client: AsyncOpenAI client instance
        question: The original question
        golden_answer: The expected answer (used to determine what info is needed)
        context: Retrieved context from Zep graph search

    Returns:
        Tuple of (completeness_grade, reasoning, missing_elements, present_elements, input_tokens, output_tokens)
        where completeness_grade is one of: COMPLETE, PARTIAL, INSUFFICIENT
    """
    system_prompt = """
You are an expert evaluator assessing whether retrieved context contains adequate information to answer a question.
"""

    completeness_prompt = f"""
Your task is to evaluate whether the provided CONTEXT contains sufficient information to answer the QUESTION according to what the GOLDEN ANSWER requires.

IMPORTANT: You are NOT evaluating an answer. You are evaluating whether the CONTEXT itself has the necessary information.

<QUESTION>
{question}
</QUESTION>

<GOLDEN ANSWER>
{golden_answer}
</GOLDEN ANSWER>

<CONTEXT>
{context}
</CONTEXT>

Evaluation Guidelines:

1. **COMPLETE**: The context contains ALL information needed to fully answer the question according to the golden answer.
   - All key elements from the golden answer are present
   - Sufficient detail exists to construct a complete answer
   - Historical facts (with past date ranges) ARE valid context

2. **PARTIAL**: The context contains SOME relevant information but is missing key details.
   - Some elements from the golden answer are present
   - Some critical information is missing or incomplete
   - Additional context would be needed for a complete answer

3. **INSUFFICIENT**: The context lacks most or all critical information needed.
   - Key elements from the golden answer are absent
   - Context is off-topic or irrelevant
   - No reasonable answer could be constructed from this context

IMPORTANT temporal interpretation:
- Facts with date ranges (e.g., "2025-10-01 - 2025-10-07") represent WHEN events occurred
- These historical facts remain VALID context even if dated in the past
- Only mark information as missing if it is truly ABSENT from the context
- Do NOT mark facts as "expired" or "outdated" simply because they have past dates
- Date ranges ending before "present" indicate completed/past events, not invalid information

For your evaluation:
- Identify which information elements ARE present in the context (present_elements)
- Identify which information elements are MISSING (truly absent) from the context (missing_elements)
- Historical facts (past date ranges) count as present information
- Provide clear reasoning explaining your completeness assessment

Please evaluate the context completeness:
"""

    async def _make_request():
        return await openai_client.responses.parse(
            model=LLM_JUDGE_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": completeness_prompt},
            ],
            text_format=CompletenessGrade,
            reasoning=({"effort": "low"} if LLM_JUDGE_MODEL.startswith("gpt-5") else None),
            temperature=0.0 if not LLM_JUDGE_MODEL.startswith("gpt-5") else None,
        )

    response = await retry_with_exponential_backoff(_make_request)

    result = response.output_parsed
    completeness_grade = result.completeness.strip().upper()

    # Extract token usage
    input_tokens = response.usage.input_tokens if response.usage else 0
    output_tokens = response.usage.output_tokens if response.usage else 0

    return (
        completeness_grade,
        result.reasoning,
        result.missing_elements,
        result.present_elements,
        input_tokens,
        output_tokens,
    )


# ============================================================================
# Step 5: Process Single Query (Pipeline)
# ============================================================================


async def process_single_query(
    zep_client: AsyncZep,
    openai_client: AsyncOpenAI,
    user_id: str,
    query: str,
    golden_answer: str,
    category: str = "uncategorized",
) -> Dict[str, Any]:
    """
    Process a single query through the complete pipeline:
    Search → Evaluate Context Completeness (PRIMARY) → Generate Response → Grade Answer (SECONDARY)

    Args:
        zep_client: AsyncZep client instance
        openai_client: AsyncOpenAI client instance
        user_id: User ID for graph search
        query: Question to answer
        golden_answer: Expected answer for evaluation

    Returns:
        Dictionary containing all results for this query
    """
    start_time = time()

    # Step 1: Search and construct context (with optional timeout)
    context_timed_out = False
    try:
        if CONTEXT_LATENCY_LIMIT_MS > 0:
            context = await asyncio.wait_for(
                construct_context_block(zep_client, user_id, query),
                timeout=CONTEXT_LATENCY_LIMIT_MS / 1000.0,
            )
        else:
            context = await construct_context_block(zep_client, user_id, query)
    except asyncio.TimeoutError:
        context = ""
        context_timed_out = True
        print(f"  ⚠ Context construction timed out after {CONTEXT_LATENCY_LIMIT_MS}ms")

    # Track context size and truncation
    context_original_chars = len(context)
    context_truncated = False

    # Truncate context if limit is set
    if CONTEXT_CHAR_LIMIT > 0 and len(context) > CONTEXT_CHAR_LIMIT:
        context = context[:CONTEXT_CHAR_LIMIT]
        context_truncated = True

    context_final_chars = len(context)
    context_construction_duration_ms = (time() - start_time) * 1000

    # Steps 2 & 3: Run completeness evaluation and response generation in parallel
    completeness_start = time()
    response_start = time()

    # Create coroutines for parallel execution
    completeness_task = evaluate_context_completeness(
        openai_client, query, golden_answer, context
    )
    response_task = generate_ai_response(openai_client, context, query)

    # Execute in parallel
    (completeness_grade, completeness_reasoning, missing_elements, present_elements, completeness_input_tokens, completeness_output_tokens), (
        ai_answer,
        response_input_tokens,
        response_output_tokens,
    ) = await asyncio.gather(completeness_task, response_task)

    completeness_duration_ms = (time() - completeness_start) * 1000
    response_duration_ms = (time() - response_start) * 1000

    # Step 4: Grade Response (SECONDARY METRIC) - must wait for AI answer
    grading_start = time()
    answer_grade, answer_reasoning, grading_input_tokens, grading_output_tokens = await grade_ai_response(
        openai_client, query, golden_answer, ai_answer
    )
    grading_duration_ms = (time() - grading_start) * 1000

    total_duration_ms = (time() - start_time) * 1000

    # Print result with PRIMARY metric first
    completeness_prefix = {
        "COMPLETE": "[✓]",
        "PARTIAL": "[~]",
        "INSUFFICIENT": "[✗]",
    }.get(completeness_grade, "[ ]")

    answer_status = "[✓] CORRECT" if answer_grade else "[✗] WRONG"

    print(f"Question: {query}")
    print(f"  Gold: {golden_answer}")
    print(f"  {completeness_prefix} Context Completeness: {completeness_grade}")
    print(f"     {completeness_reasoning}")
    if missing_elements:
        print(f"     Missing: {', '.join(missing_elements)}")
    print(f"  {answer_status}")
    print(f"     Answer: {ai_answer}")
    print(f"     {answer_reasoning}\n")

    return {
        "question": query,
        "category": category,
        "context": context,
        # Context size and latency tracking
        "context_truncated": context_truncated,
        "context_timed_out": context_timed_out,
        "context_original_chars": context_original_chars,
        "context_final_chars": context_final_chars,
        "context_construction_duration_ms": context_construction_duration_ms,
        # PRIMARY METRIC: Context Completeness
        "completeness_grade": completeness_grade,
        "completeness_reasoning": completeness_reasoning,
        "completeness_missing_elements": missing_elements,
        "completeness_present_elements": present_elements,
        "completeness_duration_ms": completeness_duration_ms,
        # SECONDARY METRIC: Answer Accuracy
        "answer": ai_answer,
        "golden_answer": golden_answer,
        "answer_grade": answer_grade,
        "answer_reasoning": answer_reasoning,
        # Timing breakdown
        "response_duration_ms": response_duration_ms,
        "grading_duration_ms": grading_duration_ms,
        "total_duration_ms": total_duration_ms,
        # Token usage - detailed breakdown
        "response_input_tokens": response_input_tokens,
        "response_output_tokens": response_output_tokens,
        "completeness_input_tokens": completeness_input_tokens,
        "completeness_output_tokens": completeness_output_tokens,
        "grading_input_tokens": grading_input_tokens,
        "grading_output_tokens": grading_output_tokens,
        "total_input_tokens": response_input_tokens + completeness_input_tokens + grading_input_tokens,
        "total_output_tokens": response_output_tokens + completeness_output_tokens + grading_output_tokens,
    }


# ============================================================================
# Step 6: Run Complete Evaluation Pipeline
# ============================================================================


async def evaluate_all_questions(
    zep_client: AsyncZep,
    openai_client: AsyncOpenAI,
    manifest: Dict[str, Any],
    test_cases_by_user: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Run the complete evaluation pipeline for all users and their test cases.

    Returns:
        Dictionary mapping user_id to list of evaluation results
    """
    all_results = {}

    # Map base user IDs to actual Zep user IDs
    user_mapping = {}
    for user_data in manifest["users"]:
        base_id = user_data["base_user_id"]
        zep_id = user_data["zep_user_id"]
        user_mapping[base_id] = zep_id

    # Process each user
    for base_user_id, test_cases in test_cases_by_user.items():
        if base_user_id not in user_mapping:
            print(f"Warning: User {base_user_id} not found in manifest, skipping")
            continue

        zep_user_id = user_mapping[base_user_id]
        print(f"\n{'='*80}")
        print(f"Evaluating user: {base_user_id} → {zep_user_id}")
        print(f"Test cases: {len(test_cases)}")
        print(f"{'='*80}\n")

        # Warm the user cache before running tests
        print(f"Warming user cache for {zep_user_id}...")
        await zep_client.user.warm(user_id=zep_user_id)
        # Wait 1 second to allow the cache to fully warm
        await asyncio.sleep(1)
        print("Cache warmed, starting evaluation...\n")

        # Process queries in batches of 5 to avoid overwhelming the API
        batch_size = 15
        user_results = []

        for i in range(0, len(test_cases), batch_size):
            batch = test_cases[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(test_cases) + batch_size - 1) // batch_size

            print(
                f"Processing batch {batch_num}/{total_batches} ({len(batch)} queries)..."
            )

            tasks = [
                process_single_query(
                    zep_client,
                    openai_client,
                    zep_user_id,
                    test_case["query"],
                    test_case["golden_answer"],
                    test_case.get("category", "uncategorized"),
                )
                for test_case in batch
            ]

            batch_results = await asyncio.gather(*tasks)
            user_results.extend(batch_results)

        all_results[base_user_id] = user_results

        print(f"\n✓ Completed evaluation for user {base_user_id}\n")

    return all_results


# ============================================================================
# Step 6: Save and Analyze Results
# ============================================================================


def calculate_aggregate_statistics(
    results: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Calculate aggregate statistics across all users, per-user, and per-category.
    Returns structured statistics dictionary.
    """
    # Calculate per-user statistics
    user_scores = {}
    for user_id, user_results in results.items():
        if not user_results:
            continue

        user_total = len(user_results)
        user_complete = sum(
            1 for r in user_results if r["completeness_grade"] == "COMPLETE"
        )
        user_partial = sum(
            1 for r in user_results if r["completeness_grade"] == "PARTIAL"
        )
        user_insufficient = sum(
            1 for r in user_results if r["completeness_grade"] == "INSUFFICIENT"
        )
        user_correct = sum(1 for r in user_results if r["answer_grade"])

        user_scores[user_id] = {
            "total_tests": user_total,
            "completeness": {
                "complete": user_complete,
                "partial": user_partial,
                "insufficient": user_insufficient,
                "complete_rate": (
                    (user_complete / user_total * 100) if user_total > 0 else 0
                ),
                "partial_rate": (
                    (user_partial / user_total * 100) if user_total > 0 else 0
                ),
                "insufficient_rate": (
                    (user_insufficient / user_total * 100) if user_total > 0 else 0
                ),
            },
            "accuracy": {
                "correct": user_correct,
                "incorrect": user_total - user_correct,
                "accuracy_rate": (
                    (user_correct / user_total * 100) if user_total > 0 else 0
                ),
            },
        }

    # Calculate per-category statistics
    all_user_results = []
    for user_results in results.values():
        all_user_results.extend(user_results)

    category_scores = {}
    categories = set(r.get("category", "uncategorized") for r in all_user_results)

    for category in categories:
        cat_results = [r for r in all_user_results if r.get("category") == category]
        if not cat_results:
            continue

        cat_total = len(cat_results)
        cat_complete = sum(
            1 for r in cat_results if r["completeness_grade"] == "COMPLETE"
        )
        cat_partial = sum(
            1 for r in cat_results if r["completeness_grade"] == "PARTIAL"
        )
        cat_insufficient = sum(
            1 for r in cat_results if r["completeness_grade"] == "INSUFFICIENT"
        )
        cat_correct = sum(1 for r in cat_results if r["answer_grade"])

        category_scores[category] = {
            "total_tests": cat_total,
            "completeness": {
                "complete": cat_complete,
                "partial": cat_partial,
                "insufficient": cat_insufficient,
                "complete_rate": (
                    (cat_complete / cat_total * 100) if cat_total > 0 else 0
                ),
                "partial_rate": (
                    (cat_partial / cat_total * 100) if cat_total > 0 else 0
                ),
                "insufficient_rate": (
                    (cat_insufficient / cat_total * 100) if cat_total > 0 else 0
                ),
            },
            "accuracy": {
                "correct": cat_correct,
                "incorrect": cat_total - cat_correct,
                "accuracy_rate": (
                    (cat_correct / cat_total * 100) if cat_total > 0 else 0
                ),
            },
        }

    # Calculate aggregate statistics across all users
    all_user_results = []
    for user_results in results.values():
        all_user_results.extend(user_results)

    total_questions = len(all_user_results)

    if total_questions == 0:
        return {"user_scores": user_scores, "aggregate_scores": {}}

    # Completeness metrics
    complete_count = sum(
        1 for r in all_user_results if r["completeness_grade"] == "COMPLETE"
    )
    partial_count = sum(
        1 for r in all_user_results if r["completeness_grade"] == "PARTIAL"
    )
    insufficient_count = sum(
        1 for r in all_user_results if r["completeness_grade"] == "INSUFFICIENT"
    )

    complete_rate = complete_count / total_questions * 100
    partial_rate = partial_count / total_questions * 100
    insufficient_rate = insufficient_count / total_questions * 100

    # Accuracy metrics
    correct_answer_count = sum(1 for r in all_user_results if r["answer_grade"])
    answer_accuracy = correct_answer_count / total_questions * 100

    # Timing statistics
    total_durations = [r["total_duration_ms"] for r in all_user_results]
    completeness_durations = [r["completeness_duration_ms"] for r in all_user_results]
    grading_durations = [r["grading_duration_ms"] for r in all_user_results]

    if total_questions > 1:
        median_total = statistics.median(total_durations)
        stdev_total = statistics.stdev(total_durations)
        median_completeness = statistics.median(completeness_durations)
        stdev_completeness = statistics.stdev(completeness_durations)
        median_grading = statistics.median(grading_durations)
        stdev_grading = statistics.stdev(grading_durations)
    else:
        median_total = total_durations[0]
        stdev_total = 0
        median_completeness = completeness_durations[0]
        stdev_completeness = 0
        median_grading = grading_durations[0]
        stdev_grading = 0

    # Token statistics
    total_input_tokens = sum(r["total_input_tokens"] for r in all_user_results)
    total_output_tokens = sum(r["total_output_tokens"] for r in all_user_results)

    # Per-function token breakdown
    total_response_input = sum(r["response_input_tokens"] for r in all_user_results)
    total_response_output = sum(r["response_output_tokens"] for r in all_user_results)
    total_completeness_input = sum(r["completeness_input_tokens"] for r in all_user_results)
    total_completeness_output = sum(r["completeness_output_tokens"] for r in all_user_results)
    total_grading_input = sum(r["grading_input_tokens"] for r in all_user_results)
    total_grading_output = sum(r["grading_output_tokens"] for r in all_user_results)

    # Context truncation, timeout, and latency statistics
    truncated_count = sum(1 for r in all_user_results if r.get("context_truncated", False))
    timed_out_count = sum(1 for r in all_user_results if r.get("context_timed_out", False))
    context_original_chars_list = [r.get("context_original_chars", 0) for r in all_user_results]
    context_final_chars_list = [r.get("context_final_chars", 0) for r in all_user_results]
    context_construction_durations = [r.get("context_construction_duration_ms", 0) for r in all_user_results]

    # Pre-truncation (original) stats
    if total_questions > 1 and context_original_chars_list:
        median_original_chars = statistics.median(context_original_chars_list)
        stdev_original_chars = statistics.stdev(context_original_chars_list)
    elif context_original_chars_list:
        median_original_chars = context_original_chars_list[0]
        stdev_original_chars = 0
    else:
        median_original_chars = 0
        stdev_original_chars = 0

    # Post-truncation (final) stats
    if total_questions > 1 and context_final_chars_list:
        median_final_chars = statistics.median(context_final_chars_list)
        stdev_final_chars = statistics.stdev(context_final_chars_list)
    elif context_final_chars_list:
        median_final_chars = context_final_chars_list[0]
        stdev_final_chars = 0
    else:
        median_final_chars = 0
        stdev_final_chars = 0

    # Context construction latency stats
    if total_questions > 1 and context_construction_durations:
        median_context_construction = statistics.median(context_construction_durations)
        stdev_context_construction = statistics.stdev(context_construction_durations)
    elif context_construction_durations:
        median_context_construction = context_construction_durations[0]
        stdev_context_construction = 0
    else:
        median_context_construction = 0
        stdev_context_construction = 0

    # Correlation analysis
    complete_and_correct = sum(
        1
        for r in all_user_results
        if r["completeness_grade"] == "COMPLETE" and r["answer_grade"]
    )
    complete_but_wrong = sum(
        1
        for r in all_user_results
        if r["completeness_grade"] == "COMPLETE" and not r["answer_grade"]
    )

    aggregate_scores = {
        "total_tests": total_questions,
        "completeness": {
            "complete": complete_count,
            "partial": partial_count,
            "insufficient": insufficient_count,
            "complete_rate": complete_rate,
            "partial_rate": partial_rate,
            "insufficient_rate": insufficient_rate,
        },
        "accuracy": {
            "correct": correct_answer_count,
            "incorrect": total_questions - correct_answer_count,
            "accuracy_rate": answer_accuracy,
        },
        "timing": {
            "total_median_ms": median_total,
            "total_stdev_ms": stdev_total,
            "grading_median_ms": median_grading,
            "grading_stdev_ms": stdev_grading,
            "completeness_median_ms": median_completeness,
            "completeness_stdev_ms": stdev_completeness,
        },
        "tokens": {
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "response_input_tokens": total_response_input,
            "response_output_tokens": total_response_output,
            "completeness_input_tokens": total_completeness_input,
            "completeness_output_tokens": total_completeness_output,
            "grading_input_tokens": total_grading_input,
            "grading_output_tokens": total_grading_output,
        },
        "context": {
            "truncated_count": truncated_count,
            "truncated_rate": (truncated_count / total_questions * 100) if total_questions > 0 else 0,
            "timed_out_count": timed_out_count,
            "timed_out_rate": (timed_out_count / total_questions * 100) if total_questions > 0 else 0,
            "char_limit": CONTEXT_CHAR_LIMIT,
            "latency_limit_ms": CONTEXT_LATENCY_LIMIT_MS,
            "construction_median_ms": median_context_construction,
            "construction_stdev_ms": stdev_context_construction,
            "original_median_chars": median_original_chars,
            "original_stdev_chars": stdev_original_chars,
            "final_median_chars": median_final_chars,
            "final_stdev_chars": stdev_final_chars,
        },
        "correlation": {
            "complete_and_correct": complete_and_correct,
            "complete_but_wrong": complete_but_wrong,
            "complete_total": complete_count,
            "accuracy_when_complete": (
                (complete_and_correct / complete_count * 100)
                if complete_count > 0
                else 0
            ),
        },
    }

    return {
        "user_scores": user_scores,
        "aggregate_scores": aggregate_scores,
        "category_scores": category_scores,
    }


def save_results(
    results: Dict[str, List[Dict[str, Any]]], run_dir: str, manifest: Dict[str, Any]
):
    """
    Save evaluation results with comprehensive aggregate statistics to JSON file.
    """
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    results_file = os.path.join(run_dir, f"evaluation_results_{timestamp}.json")

    # Calculate statistics
    stats = calculate_aggregate_statistics(results)

    # Prepare output structure
    output_data = {
        "evaluation_timestamp": timestamp,
        "run_number": manifest.get("run_number"),
        "search_configuration": {
            "facts_limit": FACTS_LIMIT,
            "entities_limit": ENTITIES_LIMIT,
            "episodes_limit": EPISODES_LIMIT,
        },
        "model_configuration": {
            "response_model": LLM_RESPONSE_MODEL,
            "judge_model": LLM_JUDGE_MODEL,
        },
        "aggregate_scores": stats["aggregate_scores"],
        "category_scores": stats["category_scores"],
        "user_scores": stats["user_scores"],
        "detailed_results": results,
    }

    with open(results_file, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\n{'='*80}")
    print(f"Results saved to: {results_file}")
    print(f"{'='*80}")

    return results_file, stats


def print_summary(stats: Dict[str, Any]):
    """
    Print summary statistics for the evaluation.
    """
    aggregate = stats["aggregate_scores"]
    user_scores = stats["user_scores"]
    category_scores = stats.get("category_scores", {})

    if not aggregate:
        print("No results to summarize")
        return

    total_tests = aggregate["total_tests"]

    print(f"\n{'='*80}")
    print(f"AGGREGATE SCORES ({total_tests} total tests)")
    print(f"{'='*80}\n")

    # PRIMARY METRIC - Context Completeness
    print("PRIMARY METRIC - Context Completeness:")
    print(
        f"  COMPLETE:     {aggregate['completeness']['complete']:3d} / {total_tests} ({aggregate['completeness']['complete_rate']:.1f}%)"
    )
    print(
        f"  PARTIAL:      {aggregate['completeness']['partial']:3d} / {total_tests} ({aggregate['completeness']['partial_rate']:.1f}%)"
    )
    print(
        f"  INSUFFICIENT: {aggregate['completeness']['insufficient']:3d} / {total_tests} ({aggregate['completeness']['insufficient_rate']:.1f}%)"
    )

    # SECONDARY METRIC - Answer Accuracy
    print(f"\nSECONDARY METRIC - Answer Accuracy:")
    print(
        f"  CORRECT:   {aggregate['accuracy']['correct']:3d} / {total_tests} ({aggregate['accuracy']['accuracy_rate']:.1f}%)"
    )
    print(f"  INCORRECT: {aggregate['accuracy']['incorrect']:3d} / {total_tests}")

    # Correlation Analysis
    print(f"\nCorrelation Analysis:")
    corr = aggregate["correlation"]
    if corr["complete_total"] > 0:
        print(
            f"  When context is COMPLETE: {corr['complete_and_correct']}/{corr['complete_total']} answers correct ({corr['accuracy_when_complete']:.1f}%)"
        )
    print(
        f"  Complete but wrong: {corr['complete_but_wrong']}/{corr['complete_total']}"
    )

    # Timing
    print(f"\nTiming:")
    print(
        f"  Total time per query:     {aggregate['timing']['total_median_ms']:.0f} ± {aggregate['timing']['total_stdev_ms']:.0f}ms"
    )
    print(
        f"  Accuracy eval:            {aggregate['timing']['grading_median_ms']:.0f} ± {aggregate['timing']['grading_stdev_ms']:.0f}ms"
    )
    print(
        f"  Completeness eval:        {aggregate['timing']['completeness_median_ms']:.0f} ± {aggregate['timing']['completeness_stdev_ms']:.0f}ms"
    )

    # Token Usage
    print(f"\nToken Usage:")
    print(f"  Total input tokens:      {aggregate['tokens']['total_input_tokens']:,}")
    print(f"  Total output tokens:     {aggregate['tokens']['total_output_tokens']:,}")
    print(f"  Total tokens:            {aggregate['tokens']['total_tokens']:,}")
    print(f"\n  Breakdown by function:")
    print(f"    Response generation:   {aggregate['tokens']['response_input_tokens']:,} in / {aggregate['tokens']['response_output_tokens']:,} out")
    print(f"    Completeness eval:     {aggregate['tokens']['completeness_input_tokens']:,} in / {aggregate['tokens']['completeness_output_tokens']:,} out")
    print(f"    Answer grading:        {aggregate['tokens']['grading_input_tokens']:,} in / {aggregate['tokens']['grading_output_tokens']:,} out")

    # Context Stats
    print(f"\nContext:")
    ctx = aggregate.get("context", {})
    char_limit = ctx.get("char_limit", 0)
    latency_limit = ctx.get("latency_limit_ms", 0)
    if char_limit > 0:
        print(f"  Character limit:         {char_limit}")
        print(
            f"  Truncated:               {ctx.get('truncated_count', 0)}/{total_tests} ({ctx.get('truncated_rate', 0):.1f}%)"
        )
    else:
        print(f"  Character limit:         None (unlimited)")
    if latency_limit > 0:
        print(f"  Latency limit:           {latency_limit}ms")
        print(
            f"  Timed out:               {ctx.get('timed_out_count', 0)}/{total_tests} ({ctx.get('timed_out_rate', 0):.1f}%)"
        )
    else:
        print(f"  Latency limit:           None (unlimited)")
    print(
        f"  Construction time:       {ctx.get('construction_median_ms', 0):.0f} ± {ctx.get('construction_stdev_ms', 0):.0f}ms"
    )
    print(
        f"  Original size (chars):   {ctx.get('original_median_chars', 0):.0f} ± {ctx.get('original_stdev_chars', 0):.0f}"
    )
    print(
        f"  Final size (chars):      {ctx.get('final_median_chars', 0):.0f} ± {ctx.get('final_stdev_chars', 0):.0f}"
    )

    # Per-User Scores
    print(f"\n\n{'='*80}")
    print("PER-USER SCORES")
    print(f"{'='*80}\n")

    for user_id, scores in user_scores.items():
        print(f"User: {user_id} ({scores['total_tests']} tests)")
        print("-" * 80)
        print(
            f"  Completeness: COMPLETE={scores['completeness']['complete_rate']:.1f}%, "
            f"PARTIAL={scores['completeness']['partial_rate']:.1f}%, "
            f"INSUFFICIENT={scores['completeness']['insufficient_rate']:.1f}%"
        )
        print(
            f"  Accuracy:     {scores['accuracy']['accuracy_rate']:.1f}% "
            f"({scores['accuracy']['correct']}/{scores['total_tests']} correct)"
        )
        print()

    # Per-Category Scores
    if category_scores:
        print(f"\n{'='*80}")
        print("PER-CATEGORY SCORES")
        print(f"{'='*80}\n")

        # Define category display order and descriptions
        category_info = {
            "easy": ("Easy", "1 needle"),
            "medium": ("Medium", "3 needles"),
            "hard": ("Hard", "5 needles"),
        }

        # Sort categories in order: easy, medium, hard, then any others
        ordered_categories = []
        for cat in ["easy", "medium", "hard"]:
            if cat in category_scores:
                ordered_categories.append(cat)
        for cat in category_scores:
            if cat not in ordered_categories:
                ordered_categories.append(cat)

        for category in ordered_categories:
            scores = category_scores[category]
            display_name, needle_desc = category_info.get(
                category, (category.capitalize(), "")
            )
            header = f"{display_name} ({needle_desc})" if needle_desc else display_name

            # Highlight hard category
            is_hard = category == "hard"
            if is_hard:
                print(f"\n{'*'*80}")
                print(f"*** {header} - {scores['total_tests']} tests (KEY CONTEST METRIC) ***")
                print(f"{'*'*80}")
            else:
                print(f"{header} - {scores['total_tests']} tests:")
                print("-" * 80)

            print(
                f"  Completeness: COMPLETE={scores['completeness']['complete_rate']:.1f}%, "
                f"PARTIAL={scores['completeness']['partial_rate']:.1f}%, "
                f"INSUFFICIENT={scores['completeness']['insufficient_rate']:.1f}%"
            )

            # Highlight accuracy for hard category
            if is_hard:
                print(
                    f"  >>> Accuracy: {scores['accuracy']['accuracy_rate']:.2f}% <<<"
                    f" ({scores['accuracy']['correct']}/{scores['total_tests']} correct)"
                )
            else:
                print(
                    f"  Accuracy:     {scores['accuracy']['accuracy_rate']:.1f}% "
                    f"({scores['accuracy']['correct']}/{scores['total_tests']} correct)"
                )

            if is_hard:
                print(f"{'*'*80}\n")
            else:
                print()


# ============================================================================
# Main Function
# ============================================================================


async def main():
    # Load environment variables from workspace root
    load_dotenv()

    # Parse command-line arguments
    run_number = None
    if len(sys.argv) > 1:
        try:
            run_number = int(sys.argv[1])
        except ValueError:
            print(f"Error: Invalid run number '{sys.argv[1]}'")
            print("Usage: python zep_evaluate.py [run_number]")
            exit(1)

    # Validate environment variables
    zep_api_key = os.getenv("ZEP_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not zep_api_key:
        print("Error: Missing ZEP_API_KEY environment variable")
        exit(1)

    if not openai_api_key:
        print("Error: Missing OPENAI_API_KEY environment variable")
        exit(1)

    # Initialize clients
    zep_client = AsyncZep(api_key=zep_api_key)
    openai_client = AsyncOpenAI(api_key=openai_api_key)

    print("=" * 80)
    print("ZEP EVALUATION SCRIPT")
    print("=" * 80)

    try:
        # Load run manifest
        manifest, run_dir = load_run_manifest(run_number)

        # Load test cases
        test_cases_by_user = await load_all_test_cases()

        # Run evaluation
        print("Starting evaluation...\n")
        results = await evaluate_all_questions(
            zep_client, openai_client, manifest, test_cases_by_user
        )

        # Save results with aggregate statistics
        results_file, stats = save_results(results, run_dir, manifest)

        # Print summary
        print_summary(stats)

        print(f"\n{'='*80}")
        print("EVALUATION COMPLETE")
        print(f"{'='*80}")
        print(f"\nDetailed results saved to: {results_file}")

    except Exception as e:
        print(f"\nEvaluation failed: {e}")
        import traceback

        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
