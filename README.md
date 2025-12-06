# Context Engineering Contest

Welcome to the Zep/Neo4j AI Workshop context engineering contest! Compete to achieve the highest accuracy score by engineering optimal context retrieval from Zep's knowledge graph.

## Overview

This contest challenges you to optimize context retrieval for a coding agent using Zep's knowledge graph. You'll work with a dataset of conversations between a developer (Marcus Chen) and his coding assistant, then engineer the best approach to retrieve relevant context within strict constraints: **2000 characters** and **2 seconds latency**.

**Your goal**: Achieve the highest accuracy score on hard-category questions by optimizing search parameters, context formatting, and agent prompts. The top 3 solutions win prizes!

## Table of Contents

- [Quick Start](#quick-start)
- [The Use Case & Dataset](#the-use-case--dataset)
- [The Contest](#the-contest)
  - [Objective](#objective)
  - [Understanding the Metrics](#understanding-the-metrics)
  - [Contest Configuration](#contest-configuration)
- [Recommended Approach](#recommended-approach)
- [Advanced Techniques](#advanced-techniques)
- [Rules & What You Can Modify](#rules--what-you-can-modify)
- [Submitting Your Solution](#submitting-your-solution)
- [Prizes](#prizes)
- [Resources](#resources)
- [Submission License](#submission-license)

---

## Quick Start

### 1. Fork and Open in GitHub Codespaces

1. Click the **"Fork"** button in the top-right corner to create your own copy of this repository
2. On **your fork**, click the green **"Code"** button, then select **"Open with Codespaces"** to launch your development environment

Make sure you open the Codespace on your fork (not the original repository) so you can push branches and create PRs.

**What happens when you launch:**
- The entire repository opens in VS Code
- Dependencies are automatically installed with `uv sync`
- A `.env` file is automatically created from the template
- Your integrated terminal opens in the `zep-eval-harness` directory, ready to go

### 2. Set Up API Keys

After your Codespace finishes setting up, edit the automatically-created `.env` file in the workspace root directory with your API keys:

**OpenAI API Key**:

If you already have an OpenAI API key, paste it into your `.env` file:
```
OPENAI_API_KEY=your_openai_api_key_here
```

If you don't have an OpenAI account yet, follow these steps:
1. Navigate to [https://auth.openai.com/log-in](https://auth.openai.com/log-in)
2. Create an account and organization
3. Add $5 of credits. Unfortunately this is required, though each evaluation run costs on the order of $0.10 so you're unlikely to need more than these five dollars
4. Copy and use the API key that the onboarding process prompts you to create
5. Paste your API key into your `.env` file:
```
OPENAI_API_KEY=your_openai_api_key_here
```

**Zep API Key** (create your own):
1. Go to [https://app.getzep.com/](https://app.getzep.com/) and sign up for a free account
2. After sign-up, you'll be prompted to create an API key
3. Copy your API key and paste it into your `.env` file:
```
ZEP_API_KEY=your_zep_api_key_here
```

When you create your Zep account, the `marcus_chen_001` user and dataset are automatically provisioned—no ingestion scripts needed.

### 3. Run Evaluation

Once your API keys are configured, run the evaluation:

```bash
uv run zep_evaluate.py
```

This runs the evaluation using the Marcus Chen user that has already been provisioned in your account. You'll see completeness and accuracy scores for easy, medium, and hard test categories.

### Viewing Full Evaluation Results

After each evaluation run, detailed results are saved to the `zep-eval-harness/runs/` folder. Each run creates a JSON file containing:

- **Aggregate scores**: Overall completeness and accuracy rates across all test categories
- **Category scores**: Breakdown by easy, medium, and hard difficulty levels
- **Per-question results**: Individual test case outcomes including the question, expected answer, agent response, retrieved context, and judge reasoning
- **Timing metrics**: Search latency, grading time, and total execution statistics
- **Configuration snapshot**: The search limits and model settings used for the run

To view your results, open the JSON file at:
```
zep-eval-harness/runs/<run_folder>/evaluation_results_<timestamp>.json
```

This is especially useful for debugging: you can see exactly what context was retrieved for each question, whether it was marked complete/partial/insufficient, and why the judge marked a response as correct or incorrect.

Pay special attention to the `context` section: if `timed_out_count` is greater than 0, your context construction exceeded the 2-second limit. If `truncated_rate` is high and accuracy is low, restructure your context so important information appears first.

---

## The Use Case & Dataset

### Scenario: A Coding Agent's Memory

The dataset simulates a **general-purpose coding agent** (think Claude Code, Cursor, or GitHub Copilot) that has been assisting a developer named **Marcus Chen** over multiple sessions. Marcus is a Senior Full Stack Developer at TaskFlow AI, and he's been using this coding agent to help with his daily work.

The agent has accumulated knowledge about Marcus through two types of data ingested into Zep's knowledge graph:

1. **Conversations**: 12 conversation threads containing 100+ messages between Marcus and his coding assistant
2. **JSON Telemetry Data**: Structured configuration files from Marcus's development environment:
   - `vscode_settings.json` - Editor preferences (Vim mode, tab sizes, formatters)
   - `package.json` - Node.js dependencies and scripts (pnpm, React, Zustand, Vitest)
   - `pyproject.json` - Python project configuration (uv package manager)
   - `git_config.json` - Git workflow conventions (branch naming, commit types, merge strategy)
   - `docker_compose.json` - Container orchestration setup

This JSON telemetry provides a complete, unified view of Marcus Chen's development world—his tech stack, tooling preferences, and workflow conventions—complementing the conversational context with structured technical details.

Now, when Marcus asks questions, the agent needs to retrieve the right context from this knowledge graph to give accurate, personalized responses.

### Example Conversations

Here are examples of the conversations that have been ingested into Zep's knowledge graph:

**Conversation 1 - Database conventions:**
> User: "Great. First let's add the database model. Create a new model for shared_tasks - remember we use plural snake_case for table names, UUID v4 for the id column, and always include created_at and updated_at timestamps in UTC."

**Conversation 2 - TypeScript preferences:**
> User: "Good. Make sure you're using 2 spaces for indentation and single quotes in TypeScript. Also use camelCase for function names like handleAcceptShare."

### Example Test Questions

The evaluation tests whether the agent can answer questions like:

| Difficulty | Question | Expected Answer |
|------------|----------|-----------------|
| Easy | "What package manager do I use for Python?" | "You use uv for Python package management." |
| Medium | "What are my database timestamp conventions?" | "Your database tables always include created_at and updated_at timestamps, stored in UTC." |
| Hard | "What are all my database table conventions?" | "Your database conventions: plural snake_case table names, UUID v4 primary keys in a column named 'id', created_at and updated_at timestamps in UTC, soft deletes with deleted_at, and indexes on all foreign keys." |

---

## The Contest

### Objective

Achieve the **highest accuracy score on the hard category** with context truncated to **2000 characters**.

**Note**: It's OK if the context you retrieve from Zep is longer than 2000 characters. All context blocks will be truncated to the first 2000 characters before being passed to the agent. Your goal is to structure your context so that the highest-signal information appears in the first 2000 characters.

### Understanding the Metrics

The evaluation measures:

1. **Completeness** - Does the retrieved context contain the information needed to answer the question?
2. **Accuracy** - Did the agent actually answer the question correctly?

Completeness scores are often higher than accuracy scores. This gap reveals two challenges: retrieving high-signal information within the character limit (context engineering), and ensuring the agent uses the context correctly (prompt engineering).

### Contest Configuration

The evaluation script is pre-configured with:

```python
CONTEXT_CHAR_LIMIT = 2000      # Truncate context to 2000 characters
CONTEXT_LATENCY_LIMIT_MS = 2000  # Context construction must complete within 2 seconds
```

**Do not change these values.** These constraints force you to engineer context that packs maximum signal into minimal characters and retrieves with low latency.

The **2-second latency limit** is central to this contest. Zep's value proposition is retrieving unified, up-to-date context from disparate sources with low latency—without requiring agentic search loops. If your context construction exceeds 2 seconds, the context block will be empty and the query will fail. This incentivizes solutions that leverage Zep's fast graph search rather than complex multi-step retrieval strategies.

---

## Recommended Approach

### Step 1: Optimize for Completeness

First, focus on getting the right information into your context block. Tune these search parameters in `zep_evaluate.py`:

```python
FACTS_LIMIT = 20      # Number of edges (facts/relationships) to retrieve
ENTITIES_LIMIT = 10   # Number of nodes (entities) to retrieve
EPISODES_LIMIT = 10   # Number of episodes to retrieve
```

**How to debug**: Look at test cases where completeness is "partial" or "insufficient". Examine the retrieved context and the evaluation output to see what information was missing from the context. Then adjust your search parameters to ensure those details are retrieved.

### Step 2: Optimize for Accuracy

Once completeness is good, focus on helping the agent use the context correctly. Modify the system prompt in `generate_ai_response()`.

**How to debug**: Look at test cases where the context was "complete" but the agent response was marked incorrect. The context had the answer, but the agent didn't use it properly. This tells you how to improve your system prompt.

### Step 3: Optimize Token Efficiency

With limited characters, every token matters. Modify `construct_context_block()` to:
- Use concise formatting
- Prioritize high-signal content at the beginning (since truncation cuts from the end)

---

## Advanced Techniques

If you've exhausted basic optimizations, consider these advanced features. **Note**: Re-ingesting data takes 15-20 minutes as the 100 conversation messages must be processed sequentially.

### Custom Ontology

Define a custom ontology optimized for this use case. The ontology controls how Zep extracts entities and relationships, significantly improving retrieval quality.

```bash
uv run zep_ingest.py --custom-ontology
```

See: [Customizing Graph Structure](https://help.getzep.com/customizing-graph-structure)

### User Summary Instructions

Customize how Zep generates the user summary node to prioritize information relevant to your use case. Your instructions must be generalizable to coding agents, not specific to test questions.

See: [User Summary Instructions](https://help.getzep.com/users#user-summary-instructions)

### Query Expansion with a Small LLM

Use a small, fast LLM to generate multiple search queries from the original question, then combine top results from parallel graph searches. This improves recall for multi-topic questions but only works IF you stay within the 2-second latency limit.

Relatedly: [Performance & Latency](https://help.getzep.com/performance)

---

## Rules & What You Can Modify

### What You Can Change

You can make any modifications to the retrieved context block and agent system prompt. This includes:
- Search parameters (`FACTS_LIMIT`, `ENTITIES_LIMIT`, `EPISODES_LIMIT` in `zep_evaluate.py`)
- Context formatting in `construct_context_block()`
- Which nodes, edges, or episodes are fetched from Zep's knowledge graph
- The agent system prompt in `generate_ai_response()`
- Re-ingesting the dataset with a custom ontology or user summary instructions

The only requirement is that your context block must include at least some information retrieved from Zep's knowledge graph (via search or direct node/edge/episode retrieval).

### What You Cannot Change

- The dataset
- The character limit (2000 characters)
- The latency limit (2 seconds)
- LLM models (`gpt-5-mini` for both responses and judging)

### Do Not Overfit

Do not include specific test questions/answers in prompts, hardcode responses, or use strategies that only work for this specific dataset. **Solutions that overfit to the test dataset will be rejected.**

**Test for overfitting**: Ask yourself, "Would this be reasonable for a general-purpose coding agent in production?"

- Good (generalizable): "Focus on the user's coding preferences and development workflows"
- Bad (overfitting): "The user uses 4 spaces for Python and 2 spaces for TypeScript"

Your solution must work for any developer using a coding agent, not just Marcus Chen's test questions. If you're unsure whether your solution overfits, consider using an AI agent to review your approach for generalizability.

---

## Submitting Your Solution

When you achieve a score you're proud of:

1. Create a new branch for your submission (in VS Code: click the branch name in the bottom-left → "Create new branch")
2. Commit your changes and push to your fork
3. Open a Pull Request from your fork to the original repository's `main` branch:
   - Go to [github.com/getzep/context-engineering-contest](https://github.com/getzep/context-engineering-contest) and click "Pull requests" → "New pull request"
   - Click "compare across forks"
   - Set **base repository** to `getzep/context-engineering-contest` and **base** to `main`
   - Set **head repository** to your fork and **compare** to your branch
4. Your PR title **must** follow this format: `XX.XX% - Your Title Here`
   - `XX.XX%` is your **hard category accuracy score** from your best run
   - Examples: `67.32% - Optimized context with custom ontology`, `85.00% - Dense fact packing`
5. In your PR description, briefly explain your approach
6. Your strategy must comply with the rules above

**Notes**:
- The percentage prefix is required for ranking submissions
- You can run multiple evaluations while iterating—we judge by your highest accuracy run
- For multiple different approaches, submit separate PRs from separate branches, each representing a distinct strategy
- If using GitHub CLI, use `gh pr create --web` to ensure the PR template is automatically included

---

## Prizes

The **top 3 solutions** will receive a prize!

Winners will be determined by:
1. Highest accuracy score on the hard category (with 2000 character limit and 2 second latency limit)
2. Strategies must comply with all rules. If you are unsure whether a strategy complies with the rules, you can make a submission both with and without the strategy. We reserve the right to reject a solution if it does not comply with all rules.

---

## Resources

- [Zep Documentation](https://help.getzep.com/)
- [Searching the Graph](https://help.getzep.com/searching-the-graph)
- [SDK Reference](https://help.getzep.com/sdk-reference)
- [Advanced Context Block Construction](https://help.getzep.com/cookbook/advanced-context-block-construction)
- [Customizing Graph Structure](https://help.getzep.com/customizing-graph-structure)

---

## Submission License

By submitting a pull request to this contest, you agree that your submission will be licensed under the **MIT License**. This means:

- Your code and strategies will be publicly visible in the PR
- Anyone can view, use, modify, and distribute your solution
- You retain copyright but grant broad usage rights to others
- Attribution to you as the original author will be maintained

This open source approach encourages learning and collaboration within the community. If you're not comfortable with this, please do not submit a PR.

---

Good luck and happy engineering!
