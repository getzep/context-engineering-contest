"""
Zep Custom Ontology for Coding Agents

This ontology is optimized for capturing developer workflows and technical conventions.

Design principles:
- Search-optimized: entity names contain specific technology/convention values
- Technology-focused: captures tech stacks, frameworks, tools, and standards
- Convention-aware: tracks coding styles, naming conventions, and best practices
- Project-organized: groups context by project and component type

Entity types:
- Technology: Programming languages, frameworks, libraries, tools (e.g., "Python", "FastAPI", "React")
- Convention: Coding standards, naming rules, formatting rules (e.g., "2-space indentation", "camelCase functions")
- Project: Codebases and software projects (e.g., "taskflow-frontend", "taskflow-api")
- Schedule: Meeting times, deployment windows, recurring events
- Person: Team members and their roles

Edge types:
- Uses: Developer/Project uses a Technology
- Follows: Code follows a Convention
- HasConvention: Project has an associated Convention
- ScheduledFor: Events scheduled at specific times/days
- ResponsibleFor: Team member responsible for a domain
"""

from pydantic import Field
from zep_cloud.external_clients.ontology import EntityModel, EdgeModel, EntityText


# ============================================================================
# Entity Types (5 entities optimized for coding agents)
# ============================================================================

EMPTY_STRING = "Empty string if not available or applicable."
MAX_LENGTH = 100


class Technology(EntityModel):
    """Programming languages, frameworks, libraries, tools, or technologies.
    Entity names should be the technology name (e.g., "React", "PostgreSQL", "FastAPI").
    Descriptions should include version, purpose, or usage context.
    """

    category: EntityText = Field(
        default=None,
        description="language, framework, library, database, tool, platform, other. "
        + EMPTY_STRING,
        max_length=MAX_LENGTH,
    )


class Convention(EntityModel):
    """Coding standards, naming rules, formatting rules, or architectural patterns.
    Entity names should describe the convention clearly (e.g., "2-space indentation", "snake_case_functions").
    Descriptions should explain rationale or scope (e.g., "TypeScript convention", "Database tables").
    """

    scope: EntityText = Field(
        default=None,
        description="python, typescript, javascript, database, api, git, general, other. "
        + EMPTY_STRING,
        max_length=MAX_LENGTH,
    )


class Project(EntityModel):
    """A software project, codebase, or service.
    Entity names should be the project name (e.g., "taskflow-frontend", "taskflow-api").
    Descriptions should include type, purpose, and tech stack summary.
    """

    project_type: EntityText = Field(
        default=None,
        description="frontend, backend, fullstack, service, library, infrastructure, other. "
        + EMPTY_STRING,
        max_length=MAX_LENGTH,
    )


class Schedule(EntityModel):
    """Meeting times, deployment windows, or recurring events.
    Entity names should describe the event clearly (e.g., "Daily standup", "Tuesday Thursday deployments").
    Descriptions should include frequency, time, and attendees.
    """

    frequency: EntityText = Field(
        default=None,
        description="daily, weekly, biweekly, monthly, fixed_day, flexible, once, other. "
        + EMPTY_STRING,
        max_length=MAX_LENGTH,
    )


class Person(EntityModel):
    """Team members, developers, or roles.
    Entity names should be the person's name or role.
    Descriptions should include team affiliation, responsibilities, and expertise.
    """

    role: EntityText = Field(
        default=None,
        description="frontend_engineer, backend_engineer, devops_engineer, lead, manager, other. "
        + EMPTY_STRING,
        max_length=MAX_LENGTH,
    )


# ============================================================================
# Edge Types (5 relationships, no attributes)
# ============================================================================


class Uses(EdgeModel):
    """Project or Person uses a Technology.
    Description should explain how/why the technology is used."""

    ...


class Follows(EdgeModel):
    """Code or Project follows a Convention.
    Description should specify which parts/contexts follow the convention."""

    ...


class HasConvention(EdgeModel):
    """Project explicitly has an associated Convention as a standard.
    Description should explain scope and when to apply."""

    ...


class ScheduledFor(EdgeModel):
    """An event or meeting is scheduled at specific times/days.
    Description should include frequency, time windows, and purpose."""

    ...


class ResponsibleFor(EdgeModel):
    """Person is responsible for reviewing, maintaining, or owning a domain/project/technology.
    Description should include scope and responsibilities."""

    ...


# ============================================================================
# Ontology Constants - Single Source of Truth
# ============================================================================

# Entity type names
ENTITY_TYPES = ["Technology", "Convention", "Project", "Schedule", "Person"]

# Edge type names
EDGE_TYPES = [
    "USES",
    "FOLLOWS",
    "HAS_CONVENTION",
    "SCHEDULED_FOR",
    "RESPONSIBLE_FOR",
]


# ============================================================================
# Ontology Setup Function
# ============================================================================


async def set_custom_ontology(zep_client, user_ids=None):
    """
    Set a custom ontology optimized for coding agents and developer workflows.

    This ontology captures:
    - Technology: Languages, frameworks, libraries, tools
    - Convention: Coding standards, naming rules, formatting
    - Project: Software projects and codebases
    - Schedule: Meetings, deployments, recurring events
    - Person: Team members and their roles

    Relationships track how technologies are used, conventions are followed,
    responsibilities are assigned, and schedules are maintained.

    Args:
        zep_client: AsyncZep client instance
        user_ids: Optional list of user IDs to apply ontology to.
                 If None, applies to entire project.

    Returns:
        Response from set_ontology call

    Example usage:
        ```python
        from zep_cloud import AsyncZep
        client = AsyncZep(api_key="your-key")
        await set_custom_ontology(client)
        ```
    """
    from zep_cloud import EntityEdgeSourceTarget

    kwargs = {
        "entities": {
            "Technology": Technology,
            "Convention": Convention,
            "Project": Project,
            "Schedule": Schedule,
            "Person": Person,
        },
        "edges": {
            # Project or Person uses a Technology
            "USES": (
                Uses,
                [
                    EntityEdgeSourceTarget(source="User", target="Technology"),
                    EntityEdgeSourceTarget(source="Project", target="Technology"),
                    EntityEdgeSourceTarget(source="Person", target="Technology"),
                ],
            ),
            # Code/Project follows a Convention
            "FOLLOWS": (
                Follows,
                [
                    EntityEdgeSourceTarget(source="User", target="Convention"),
                    EntityEdgeSourceTarget(source="Project", target="Convention"),
                ],
            ),
            # Project has an explicit Convention as a standard
            "HAS_CONVENTION": (
                HasConvention,
                [
                    EntityEdgeSourceTarget(source="Project", target="Convention"),
                    EntityEdgeSourceTarget(source="Technology", target="Convention"),
                ],
            ),
            # Event/Meeting scheduled at specific times
            "SCHEDULED_FOR": (
                ScheduledFor,
                [
                    EntityEdgeSourceTarget(source="Schedule", target="Person"),
                    EntityEdgeSourceTarget(source="User", target="Schedule"),
                ],
            ),
            # Person responsible for domain/project/technology
            "RESPONSIBLE_FOR": (
                ResponsibleFor,
                [
                    EntityEdgeSourceTarget(source="Person", target="Project"),
                    EntityEdgeSourceTarget(source="Person", target="Technology"),
                    EntityEdgeSourceTarget(source="Person", target="Convention"),
                ],
            ),
        },
    }

    # Apply to specific users if provided
    if user_ids:
        kwargs["user_ids"] = user_ids

    response = await zep_client.graph.set_ontology(**kwargs)
    return response
