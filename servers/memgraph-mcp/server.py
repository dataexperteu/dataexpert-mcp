"""Memgraph MCP server for DataExpert agentic AI.

Entry point for the dataexpert-memgraph-mcp package.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from core_engine.interfaces import (
    Entity,
    PathNode,
    Subgraph,
    Hypothesis,
    Finding,
    ActionCard,
    InvestigationStep,
    FindingSet,
)

from core_engine.adapters.memgraph.adapter import MemgraphAdapter

mcp = FastMCP("memgraph-adapter")
_client: Optional[MemgraphAdapter] = None


def _get_client() -> MemgraphAdapter:
    global _client
    if _client is None:
        _client = MemgraphAdapter()
    return _client


def _entity_to_dict(entity: Entity) -> Dict[str, Any]:
    return {
        "id": entity.id,
        "name": entity.name,
        "type": entity.type,
        "properties": entity.properties,
        "source_guids": entity.source_guids,
    }


def _path_to_dict(path_nodes: List[PathNode]) -> List[Dict[str, Any]]:
    return [
        {
            "entity": _entity_to_dict(step.entity),
            "relationship": step.relationship,
            "direction": step.direction,
        }
        for step in path_nodes
    ]


def _subgraph_to_dict(subgraph: Subgraph) -> Dict[str, Any]:
    return {
        "nodes": [_entity_to_dict(node) for node in subgraph.nodes],
        "edges": subgraph.edges,
    }


def _hypothesis_to_dict(hyp: Hypothesis) -> Dict[str, Any]:
    return {
        "id": hyp.id,
        "case_id": hyp.case_id,
        "statement": hyp.statement,
        "status": hyp.status,
        "confidence": hyp.confidence,
        "created_at": hyp.created_at.isoformat() if isinstance(hyp.created_at, datetime) else hyp.created_at,
        "created_by": hyp.created_by,
        "supporting_evidence_count": hyp.supporting_evidence_count,
        "contradicting_evidence_count": hyp.contradicting_evidence_count,
        "metadata": hyp.metadata,
    }


def _finding_to_dict(finding: Finding) -> Dict[str, Any]:
    return {
        "id": finding.id,
        "case_id": finding.case_id,
        "finding_set_id": finding.finding_set_id,
        "statement": finding.statement,
        "confidence": finding.confidence,
        "created_at": finding.created_at.isoformat() if isinstance(finding.created_at, datetime) else finding.created_at,
        "supported_by_guids": finding.supported_by_guids,
        "contradicted_by_guids": finding.contradicted_by_guids,
        "metadata": finding.metadata,
    }


def _action_card_to_dict(card: ActionCard) -> Dict[str, Any]:
    return {
        "id": card.id,
        "case_id": card.case_id,
        "title": card.title,
        "description": card.description,
        "status": card.status,
        "priority": card.priority,
        "assigned_to": card.assigned_to,
        "created_by": card.created_by,
        "created_at": card.created_at.isoformat() if isinstance(card.created_at, datetime) else card.created_at,
        "due_date": card.due_date.isoformat() if isinstance(card.due_date, datetime) else card.due_date,
        "expected_outcome": card.expected_outcome,
        "metadata": card.metadata,
    }


def _investigation_step_to_dict(step: InvestigationStep) -> Dict[str, Any]:
    return {
        "id": step.id,
        "case_id": step.case_id,
        "step_number": step.step_number,
        "action": step.action,
        "step_type": step.step_type,
        "executed_at": step.executed_at.isoformat() if isinstance(step.executed_at, datetime) else step.executed_at,
        "executed_by": step.executed_by,
        "result_summary": step.result_summary,
        "artifacts": step.artifacts,
        "metadata": step.metadata,
    }


def _finding_set_to_dict(fs: FindingSet) -> Dict[str, Any]:
    return {
        "id": fs.id,
        "case_id": fs.case_id,
        "name": fs.name,
        "description": fs.description,
        "created_at": fs.created_at.isoformat() if isinstance(fs.created_at, datetime) else fs.created_at,
        "created_by": fs.created_by,
        "status": fs.status,
        "metadata": fs.metadata,
    }


# ============================================================================
# EVIDENCE GRAPH TOOLS
# ============================================================================

@mcp.tool()
async def list_databases() -> List[str]:
    """List available database names on the Memgraph server."""
    client = _get_client()
    return await client.list_databases()


@mcp.tool()
async def set_database(database: Optional[str] = None) -> Dict[str, Any]:
    """Select an active database for subsequent queries."""
    client = _get_client()
    client.set_database(database)
    return {"active_database": client.get_database()}


@mcp.tool()
async def set_evidence_database() -> Dict[str, Any]:
    """Switch to the evidence graph database (dataexpert_agentic_evidence)."""
    client = _get_client()
    client.set_database("dataexpert_agentic_evidence")
    return {"active_database": client.get_database(), "graph": "evidence"}


@mcp.tool()
async def set_context_database() -> Dict[str, Any]:
    """Switch to the context graph database (dataexpert_agentic_context)."""
    client = _get_client()
    client.set_database("dataexpert_agentic_context")
    return {"active_database": client.get_database(), "graph": "context"}


@mcp.tool()
async def query(cypher: str) -> List[dict]:
    """Execute a Cypher query and return raw records on the active database."""
    client = _get_client()
    return await client.query(cypher)


@mcp.tool()
async def query_evidence(cypher: str) -> List[dict]:
    """Execute a Cypher query on the evidence graph database."""
    client = _get_client()
    return await client.query_evidence(cypher)


@mcp.tool()
async def query_context(cypher: str) -> List[dict]:
    """Execute a Cypher query on the context graph database."""
    client = _get_client()
    return await client.query_context(cypher)


@mcp.tool()
async def find_path(entity_a: str, entity_b: str) -> List[Dict[str, Any]]:
    """Find a shortest path between two entities in evidence graph."""
    client = _get_client()
    path = await client.find_path(entity_a, entity_b)
    return _path_to_dict(path)


@mcp.tool()
async def get_entity(entity_id: str) -> Dict[str, Any]:
    """Retrieve an entity by ID with all properties from evidence graph."""
    client = _get_client()
    entity = await client.get_entity(entity_id)
    return _entity_to_dict(entity)


@mcp.tool()
async def get_connected(entity_id: str, hops: int = 2) -> Dict[str, Any]:
    """Get the subgraph around an entity within N hops from evidence graph."""
    client = _get_client()
    subgraph = await client.get_connected(entity_id, hops)
    return _subgraph_to_dict(subgraph)


@mcp.tool()
async def find_entities_by_type(case_id: str, entity_type: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Find all entities of a given type within a case's evidence graph."""
    client = _get_client()
    entities = await client.find_entities_by_type(case_id, entity_type, limit)
    return [_entity_to_dict(e) for e in entities]


@mcp.tool()
async def find_entities_by_name(case_id: str, name_pattern: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Find entities matching a name pattern within a case's evidence graph."""
    client = _get_client()
    entities = await client.find_entities_by_name(case_id, name_pattern, limit)
    return [_entity_to_dict(e) for e in entities]


@mcp.tool()
async def get_entity_documents(case_id: str, entity_id: str) -> List[Dict[str, Any]]:
    """Get all documents mentioning a specific entity within a case's evidence graph."""
    client = _get_client()
    return await client.get_entity_documents(case_id, entity_id)


@mcp.tool()
async def trace_financial_flow(sender_id: str, receiver_id: str) -> List[Dict[str, Any]]:
    """Trace financial transactions between two entities from evidence graph."""
    client = _get_client()
    return await client.trace_financial_flow(sender_id, receiver_id)


# ============================================================================
# EVIDENCE GRAPH TOOLS - WRITE
# ============================================================================

@mcp.tool()
async def create_entity(
    entity_id: str,
    name: str,
    entity_type: str,
    confidence: float = 1.0,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new entity node in the evidence graph."""
    client = _get_client()
    created_id = await client.create_entity(
        entity_id=entity_id,
        name=name,
        entity_type=entity_type,
        confidence=confidence,
        properties=properties,
    )
    return {"created_id": created_id, "entity_type": "Entity"}


@mcp.tool()
async def create_document(
    guid: str,
    doc_type: str,
    timestamp: str,
    summary: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new document node in the evidence graph."""
    client = _get_client()
    created_id = await client.create_document(
        guid=guid,
        doc_type=doc_type,
        timestamp=timestamp,
        summary=summary,
        properties=properties,
    )
    return {"created_id": created_id, "entity_type": "Document"}


@mcp.tool()
async def create_event(
    event_id: str,
    event_type: str,
    timestamp: str,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new event node in the evidence graph."""
    client = _get_client()
    created_id = await client.create_event(
        event_id=event_id,
        event_type=event_type,
        timestamp=timestamp,
        properties=properties,
    )
    return {"created_id": created_id, "entity_type": "Event"}


@mcp.tool()
async def create_location(
    location_id: str,
    name: str,
    location_type: str,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new location node in the evidence graph."""
    client = _get_client()
    created_id = await client.create_location(
        location_id=location_id,
        name=name,
        location_type=location_type,
        properties=properties,
    )
    return {"created_id": created_id, "entity_type": "Location"}


# ============================================================================
# CONTEXT GRAPH TOOLS - READ
# ============================================================================

@mcp.tool()
async def list_hypotheses(case_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all hypotheses for a case from context graph."""
    client = _get_client()
    hypotheses = await client.list_hypotheses(case_id, status)
    return [_hypothesis_to_dict(h) for h in hypotheses]


@mcp.tool()
async def get_hypothesis(hypothesis_id: str) -> Dict[str, Any]:
    """Get a specific hypothesis by ID from context graph."""
    client = _get_client()
    hyp = await client.get_hypothesis(hypothesis_id)
    return _hypothesis_to_dict(hyp)


@mcp.tool()
async def list_findings(case_id: str) -> List[Dict[str, Any]]:
    """List all findings for a case from context graph."""
    client = _get_client()
    findings = await client.list_findings(case_id)
    return [_finding_to_dict(f) for f in findings]


@mcp.tool()
async def get_finding(finding_id: str) -> Dict[str, Any]:
    """Get a specific finding by ID from context graph."""
    client = _get_client()
    finding = await client.get_finding(finding_id)
    return _finding_to_dict(finding)


@mcp.tool()
async def list_finding_sets(case_id: str) -> List[Dict[str, Any]]:
    """List all finding sets for a case from context graph."""
    client = _get_client()
    finding_sets = await client.list_finding_sets(case_id)
    return [_finding_set_to_dict(fs) for fs in finding_sets]


@mcp.tool()
async def list_action_cards(case_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List action cards for a case from context graph."""
    client = _get_client()
    cards = await client.list_action_cards(case_id, status)
    return [_action_card_to_dict(c) for c in cards]


@mcp.tool()
async def get_action_card(card_id: str) -> Dict[str, Any]:
    """Get a specific action card by ID from context graph."""
    client = _get_client()
    card = await client.get_action_card(card_id)
    return _action_card_to_dict(card)


@mcp.tool()
async def get_investigation_steps(case_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get the ordered sequence of investigation steps from context graph."""
    client = _get_client()
    steps = await client.get_investigation_steps(case_id, limit)
    return [_investigation_step_to_dict(s) for s in steps]


# ============================================================================
# CONTEXT GRAPH TOOLS - WRITE
# ============================================================================

@mcp.tool()
async def create_hypothesis(
    case_id: str,
    statement: str,
    created_by: str,
    confidence: float = 0.5,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new hypothesis in context graph."""
    client = _get_client()
    hyp_id = await client.create_hypothesis(case_id, statement, created_by, confidence, metadata)
    return {"hypothesis_id": hyp_id, "case_id": case_id, "status": "created"}


@mcp.tool()
async def update_hypothesis(
    hypothesis_id: str,
    status: str,
    confidence: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update a hypothesis in context graph."""
    client = _get_client()
    success = await client.update_hypothesis(hypothesis_id, status, confidence, metadata)
    return {"hypothesis_id": hypothesis_id, "success": success}


@mcp.tool()
async def create_finding_set(
    case_id: str,
    name: str,
    description: str,
    created_by: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new finding set in context graph."""
    client = _get_client()
    fs_id = await client.create_finding_set(case_id, name, description, created_by, metadata)
    return {"finding_set_id": fs_id, "case_id": case_id, "status": "created"}


@mcp.tool()
async def create_finding(
    case_id: str,
    statement: str,
    finding_set_id: str,
    supported_by_guids: List[str],
    created_by: str,
    confidence: float = 0.7,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new finding backed by evidence documents in context graph."""
    client = _get_client()
    finding_id = await client.create_finding(
        case_id, statement, finding_set_id, supported_by_guids, created_by, confidence, metadata
    )
    return {"finding_id": finding_id, "case_id": case_id, "status": "created"}


@mcp.tool()
async def create_action_card(
    case_id: str,
    title: str,
    description: str,
    priority: str,
    assigned_to: Optional[str] = None,
    created_by: str = "system",
    due_date: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an action card in context graph."""
    client = _get_client()
    due_date_dt = None
    if due_date:
        due_date_dt = datetime.fromisoformat(due_date) if isinstance(due_date, str) else due_date
    card_id = await client.create_action_card(
        case_id, title, description, priority, assigned_to, created_by, due_date_dt, metadata
    )
    return {"action_card_id": card_id, "case_id": case_id, "status": "created"}


@mcp.tool()
async def update_action_card_status(card_id: str, status: str) -> Dict[str, Any]:
    """Update action card status in context graph."""
    client = _get_client()
    success = await client.update_action_card_status(card_id, status)
    return {"action_card_id": card_id, "success": success}


@mcp.tool()
async def record_investigation_step(
    case_id: str,
    action: str,
    step_type: str,
    executed_by: str,
    result_summary: str,
    artifacts: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record an investigation step in context graph."""
    client = _get_client()
    step_id = await client.record_investigation_step(
        case_id, action, step_type, executed_by, result_summary, artifacts, metadata
    )
    return {"investigation_step_id": step_id, "case_id": case_id, "status": "recorded"}


# ============================================================================
# CONTEXT GRAPH TOOLS - CROSS-GRAPH LINKING
# ============================================================================

@mcp.tool()
async def link_finding_to_entity(
    finding_id: str,
    entity_id: str,
    relevance: str = "supports",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Link a finding to an entity from evidence graph."""
    client = _get_client()
    success = await client.link_finding_to_entity(finding_id, entity_id, relevance, metadata)
    return {"finding_id": finding_id, "entity_id": entity_id, "success": success}


@mcp.tool()
async def link_hypothesis_to_entity(
    hypothesis_id: str,
    entity_id: str,
    relevance: str = "involves",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Link a hypothesis to an entity from evidence graph."""
    client = _get_client()
    success = await client.link_hypothesis_to_entity(hypothesis_id, entity_id, relevance, metadata)
    return {"hypothesis_id": hypothesis_id, "entity_id": entity_id, "success": success}


# ============================================================================
# CASE-SCOPED UPSERT TOOLS (idempotent — used by investigation graph_ingestion)
# ============================================================================

@mcp.tool()
async def ensure_case_database(case_id: str) -> Dict[str, Any]:
    """Create the per-case Memgraph database if it does not yet exist (idempotent)."""
    client = _get_client()
    await client._ensure_case_database(case_id)
    db_name = client._case_db(case_id)
    return {"db_name": db_name, "case_id": case_id}


@mcp.tool()
async def upsert_entity(
    case_id: str,
    name: str,
    entity_type: str,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """MERGE a named entity into the per-case graph (idempotent)."""
    client = _get_client()
    entity_id = await client.upsert_entity(
        case_id=case_id,
        name=name,
        entity_type=entity_type,
        properties=properties,
    )
    return {"entity_id": entity_id, "case_id": case_id, "name": name}


@mcp.tool()
async def upsert_relationship(
    case_id: str,
    from_name: str,
    to_name: str,
    rel_type: str,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """MERGE a relationship between two named entities in the per-case graph (idempotent)."""
    client = _get_client()
    success = await client.upsert_relationship(
        case_id=case_id,
        from_name=from_name,
        to_name=to_name,
        rel_type=rel_type,
        properties=properties,
    )
    return {"case_id": case_id, "from_name": from_name, "to_name": to_name, "success": success}


@mcp.tool()
async def upsert_event(
    case_id: str,
    name: str,
    event_type: str,
    date: str,
    participants: Optional[List[str]] = None,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """MERGE an event with participant links in the per-case graph (idempotent)."""
    client = _get_client()
    event_id = await client.upsert_event(
        case_id=case_id,
        name=name,
        event_type=event_type,
        date=date,
        participants=participants or [],
        properties=properties,
    )
    return {"event_id": event_id, "case_id": case_id, "name": name}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
