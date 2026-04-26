"""Tests for v0.3 memory types."""
from datetime import datetime, timezone
from mori.types import (
    MemoryConfig, MemoryFilters, MemoryLayer, MemoryRecordId, MemoryStats,
    ForgetPolicy, ForgetReport,
)

def test_memory_config_defaults():
    c = MemoryConfig()
    assert c.default_ttl_seconds[MemoryLayer.WORKING] == 3600
    assert c.default_ttl_seconds[MemoryLayer.EPISODIC] is None
    assert c.max_records_per_layer[MemoryLayer.WORKING] == 200
    assert c.deduplication_threshold == 0.95
    assert c.embedding_dimensions == 1536

def test_memory_filters_defaults():
    f = MemoryFilters()
    assert f.min_confidence is None
    assert f.max_age_seconds is None
    assert f.exclude_ids == []

def test_memory_filters_with_values():
    f = MemoryFilters(min_confidence=0.5, max_age_seconds=3600, provenance="tool:search",
        metadata_match={"source": "docs"}, exclude_ids=[MemoryRecordId("rec_1")])
    assert f.min_confidence == 0.5
    assert len(f.exclude_ids) == 1

def test_forget_policy_defaults():
    p = ForgetPolicy()
    assert p.expire_ttl is True
    assert p.prune_below_confidence == 0.2
    assert p.deduplicate is True

def test_forget_report():
    r = ForgetReport(expired=5, pruned=3, deduplicated=2, total_deleted=10)
    assert r.total_deleted == 10

def test_memory_stats():
    s = MemoryStats(total_records=100,
        records_per_layer={MemoryLayer.WORKING: 50, MemoryLayer.EPISODIC: 30, MemoryLayer.SEMANTIC: 15, MemoryLayer.PERSONALIZED: 5},
        estimated_tokens_per_layer={MemoryLayer.WORKING: 5000, MemoryLayer.EPISODIC: 3000, MemoryLayer.SEMANTIC: 1500, MemoryLayer.PERSONALIZED: 500},
        oldest_record_age_seconds={MemoryLayer.WORKING: 3600.0, MemoryLayer.EPISODIC: 86400.0, MemoryLayer.SEMANTIC: None, MemoryLayer.PERSONALIZED: None},
        newest_record_age_seconds={MemoryLayer.WORKING: 10.0, MemoryLayer.EPISODIC: 300.0, MemoryLayer.SEMANTIC: None, MemoryLayer.PERSONALIZED: None})
    assert s.total_records == 100

def test_memory_config_json_roundtrip():
    c = MemoryConfig()
    json_str = c.model_dump_json()
    restored = MemoryConfig.model_validate_json(json_str)
    assert restored.deduplication_threshold == 0.95
