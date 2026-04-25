"""
Day 143 — Adapter Registry 테스트

검증:
  A. _resolve_canonical_name (이름 정규화)
  B. list_adapter_names
  C. get_supported_modes
  D. get_adapter (4개 어댑터 + mode 처리)
  E. 모드 검증 (Claude는 deep_research 거부)
  F. 별칭 (perplexity = pplx = sonar)
  G. build_default_adapters (registry 통과)
  H. 잘못된 입력 방어
"""
from __future__ import annotations

import pytest

from src.research_v2.registry import (
    get_adapter,
    list_adapter_names,
    get_supported_modes,
    build_default_adapters,
    _resolve_canonical_name,
    MODE_WEB_SEARCH,
    MODE_DEEP_RESEARCH,
)


# ===========================================================================
# A. 이름 정규화
# ===========================================================================

class TestResolveCanonicalName:
    def test_canonical_name_unchanged(self):
        assert _resolve_canonical_name("perplexity") == "perplexity"
        assert _resolve_canonical_name("openai") == "openai"
        assert _resolve_canonical_name("gemini") == "gemini"
        assert _resolve_canonical_name("claude") == "claude"

    def test_uppercase_normalized(self):
        assert _resolve_canonical_name("PERPLEXITY") == "perplexity"
        assert _resolve_canonical_name("OpenAI") == "openai"

    def test_whitespace_stripped(self):
        assert _resolve_canonical_name("  perplexity  ") == "perplexity"
        assert _resolve_canonical_name("\topenai\n") == "openai"

    def test_aliases(self):
        assert _resolve_canonical_name("pplx") == "perplexity"
        assert _resolve_canonical_name("sonar") == "perplexity"
        assert _resolve_canonical_name("gpt") == "openai"
        assert _resolve_canonical_name("o4") == "openai"
        assert _resolve_canonical_name("google") == "gemini"
        assert _resolve_canonical_name("anthropic") == "claude"

    def test_aliases_case_insensitive(self):
        assert _resolve_canonical_name("PPLX") == "perplexity"
        assert _resolve_canonical_name("Anthropic") == "claude"

    def test_unknown_returns_none(self):
        assert _resolve_canonical_name("unknown") is None
        assert _resolve_canonical_name("xyz") is None

    def test_empty_returns_none(self):
        assert _resolve_canonical_name("") is None
        assert _resolve_canonical_name("   ") is None

    def test_non_string_returns_none(self):
        assert _resolve_canonical_name(None) is None
        assert _resolve_canonical_name(123) is None
        assert _resolve_canonical_name([]) is None


# ===========================================================================
# B. list_adapter_names
# ===========================================================================

class TestListAdapterNames:
    def test_returns_four_canonical_names(self):
        names = list_adapter_names()
        assert set(names) == {"perplexity", "openai", "gemini", "claude"}

    def test_returns_list_type(self):
        assert isinstance(list_adapter_names(), list)

    def test_aliases_not_included(self):
        names = list_adapter_names()
        # 별칭들은 포함되지 않아야
        assert "pplx" not in names
        assert "gpt" not in names
        assert "anthropic" not in names


# ===========================================================================
# C. get_supported_modes
# ===========================================================================

class TestGetSupportedModes:
    def test_perplexity_dual_mode(self):
        modes = get_supported_modes("perplexity")
        assert MODE_WEB_SEARCH in modes
        assert MODE_DEEP_RESEARCH in modes

    def test_openai_dual_mode(self):
        modes = get_supported_modes("openai")
        assert set(modes) == {MODE_WEB_SEARCH, MODE_DEEP_RESEARCH}

    def test_gemini_dual_mode(self):
        modes = get_supported_modes("gemini")
        assert set(modes) == {MODE_WEB_SEARCH, MODE_DEEP_RESEARCH}

    def test_claude_web_search_only(self):
        modes = get_supported_modes("claude")
        assert modes == [MODE_WEB_SEARCH]
        assert MODE_DEEP_RESEARCH not in modes

    def test_alias_works(self):
        assert get_supported_modes("pplx") == get_supported_modes("perplexity")
        assert get_supported_modes("anthropic") == get_supported_modes("claude")

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown adapter"):
            get_supported_modes("unknown")


# ===========================================================================
# D. get_adapter — 정상 케이스
# ===========================================================================

class TestGetAdapter:
    def test_perplexity_web_search(self):
        adapter = get_adapter("perplexity", mode="web_search")
        assert adapter.mode == "web_search"
        assert "perplexity" in adapter.name.lower()

    def test_perplexity_deep_research(self):
        adapter = get_adapter("perplexity", mode="deep_research")
        assert adapter.mode == "deep_research"

    def test_openai_web_search(self):
        adapter = get_adapter("openai", mode="web_search")
        assert adapter.mode == "web_search"

    def test_openai_deep_research(self):
        adapter = get_adapter("openai", mode="deep_research")
        assert adapter.mode == "deep_research"

    def test_gemini_web_search(self):
        adapter = get_adapter("gemini")  # 기본
        assert adapter.mode == "web_search"

    def test_gemini_deep_research(self):
        adapter = get_adapter("gemini", mode="deep_research")
        assert adapter.mode == "deep_research"

    def test_claude_web_search(self):
        adapter = get_adapter("claude")
        # Claude는 mode 속성 없음 (단일 모드)
        assert "claude" in adapter.name.lower()

    def test_default_mode_is_web_search(self):
        adapter = get_adapter("perplexity")
        assert adapter.mode == "web_search"


# ===========================================================================
# E. 모드 검증
# ===========================================================================

class TestModeValidation:
    def test_claude_deep_research_rejected(self):
        """Claude는 DR 미지원 → 명시적 거부."""
        with pytest.raises(ValueError, match="does not support mode"):
            get_adapter("claude", mode="deep_research")

    def test_invalid_mode_for_perplexity(self):
        with pytest.raises(ValueError, match="does not support mode"):
            get_adapter("perplexity", mode="invalid_mode")

    def test_invalid_mode_for_openai(self):
        with pytest.raises(ValueError):
            get_adapter("openai", mode="random")


# ===========================================================================
# F. 별칭 사용
# ===========================================================================

class TestAliases:
    def test_pplx_alias(self):
        adapter = get_adapter("pplx", mode="web_search")
        assert adapter.mode == "web_search"

    def test_sonar_alias(self):
        adapter = get_adapter("sonar", mode="deep_research")
        assert adapter.mode == "deep_research"

    def test_gpt_alias(self):
        adapter = get_adapter("gpt", mode="web_search")
        assert adapter.mode == "web_search"

    def test_anthropic_alias(self):
        # Claude는 mode 없음
        adapter = get_adapter("anthropic")
        assert "claude" in adapter.name.lower()

    def test_anthropic_dr_rejected(self):
        """별칭이어도 모드 검증 그대로."""
        with pytest.raises(ValueError, match="does not support"):
            get_adapter("anthropic", mode="deep_research")

    def test_uppercase_alias(self):
        adapter = get_adapter("PPLX")
        assert adapter is not None


# ===========================================================================
# G. build_default_adapters
# ===========================================================================

class TestBuildDefaultAdapters:
    def test_returns_four_adapters(self):
        adapters = build_default_adapters()
        assert len(adapters) == 4

    def test_default_mode_is_web_search(self):
        adapters = build_default_adapters()
        # Perplexity/OpenAI/Gemini는 mode 속성, Claude는 없음
        modes = [getattr(a, "mode", None) for a in adapters[:3]]
        assert all(m == "web_search" for m in modes)

    def test_deep_research_mode_claude_falls_back(self):
        """Claude는 DR 미지원이라 자동으로 web_search 유지."""
        adapters = build_default_adapters(mode="deep_research")
        assert len(adapters) == 4

        # Perplexity/OpenAI/Gemini는 deep_research
        for a in adapters[:3]:
            assert getattr(a, "mode", None) == "deep_research"

        # Claude는 mode 속성 없음 (자동 fallback)
        claude = adapters[3]
        # mode 속성이 없거나 web_search여야
        assert not hasattr(claude, "mode") or getattr(claude, "mode", None) is None

    def test_all_have_name(self):
        adapters = build_default_adapters()
        for a in adapters:
            assert hasattr(a, "name")
            assert isinstance(a.name, str)
            assert a.name


# ===========================================================================
# H. 잘못된 입력 방어
# ===========================================================================

class TestInputDefense:
    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="unknown adapter"):
            get_adapter("nonexistent")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="unknown adapter"):
            get_adapter("")

    def test_whitespace_name_raises(self):
        with pytest.raises(ValueError, match="unknown adapter"):
            get_adapter("   ")

    def test_none_name_raises(self):
        with pytest.raises(ValueError):
            get_adapter(None)

    def test_error_message_lists_available(self):
        try:
            get_adapter("xyz")
            assert False, "should raise"
        except ValueError as e:
            msg = str(e)
            # 사용 가능한 어댑터 목록을 메시지에 포함
            assert "perplexity" in msg
            assert "openai" in msg

    def test_unsupported_mode_message(self):
        try:
            get_adapter("claude", mode="deep_research")
            assert False
        except ValueError as e:
            msg = str(e)
            assert "claude" in msg
            assert "deep_research" in msg
            assert "supported" in msg.lower()


# ===========================================================================
# I. parallel_runner와의 호환성 (기존 build_default_adapters 사용처)
# ===========================================================================

class TestBackwardCompatWithParallelRunner:
    def test_parallel_runner_imports_work(self):
        """parallel_runner.build_default_adapters 호출이 여전히 작동."""
        from src.research_v2.parallel_runner import build_default_adapters as old_path

        adapters = old_path(mode="web_search")
        assert len(adapters) == 4

    def test_parallel_runner_and_registry_equivalent(self):
        """parallel_runner와 registry의 build_default_adapters는 동일 동작."""
        from src.research_v2.parallel_runner import build_default_adapters as runner_build
        from src.research_v2.registry import build_default_adapters as registry_build

        from_runner = runner_build(mode="deep_research")
        from_registry = registry_build(mode="deep_research")

        assert len(from_runner) == len(from_registry) == 4
        # 같은 어댑터 클래스들이어야
        runner_names = [a.name for a in from_runner]
        registry_names = [a.name for a in from_registry]
        assert runner_names == registry_names
