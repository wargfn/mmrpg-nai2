"""Persistent campaign memory helpers."""

from .campaign_db import (
    CAMPAIGN_DB_PATH,
    CampaignDatabase,
    get_campaign_database,
    get_entity,
    get_npc,
    initialize_database,
    list_memories,
    load_memory,
    log_event,
    save_entity,
    save_memory,
    save_npc,
    search_entities,
    search_memory,
)

__all__ = [
    "CAMPAIGN_DB_PATH",
    "CampaignDatabase",
    "get_campaign_database",
    "initialize_database",
    "save_memory",
    "load_memory",
    "save_entity",
    "get_entity",
    "search_entities",
    "list_memories",
    "save_npc",
    "get_npc",
    "log_event",
    "search_memory",
]
