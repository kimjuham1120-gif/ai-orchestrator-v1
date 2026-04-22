"""
Day 118 — Phase 6 · 트랙 전환 결정 테스트.

검증 포인트:
1. BridgeDecision 구조 + is_valid 프로퍼티
2. document_done 경로
3. cancel 경로
4. app_dev 경로
   - 정상 변환 (target_doc → deliverable_spec)
   - target_doc 누락 → 실패
   - target_doc 빈 document → 실패
   - deliverable_spec 스키마 검증
5. 잘못된 user_decision 처리
6. 공백/대소문자 정규화
7. convert_target_doc_to_spec 단위 테스트
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 공용 샘플
# ---------------------------------------------------------------------------

def _sample_target_doc():
    return {
        "document": "# 재고관리 시스템 초안\n\n## 핵심 기능\n- 입고/출고\n- 재고 조회",
        "created_at": "2026-04-21T09:40:00+00:00",
    }


# ===========================================================================
# 1. BridgeDecision 구조
# ===========================================================================

class TestBridgeDecisionStructure:
    def test_to_dict_has_all_keys(self):
        from src.phases.phase_6_bridge import BridgeDecision
        d = BridgeDecision(decision="document_done")
        result = d.to_dict()
        for key in ["decision", "next_phase", "deliverable_spec", "reason", "error"]:
            assert key in result

    def test_is_valid_true_for_known_decision(self):
        from src.phases.phase_6_bridge import BridgeDecision
        d = BridgeDecision(decision="document_done", reason="OK")
        assert d.is_valid is True

    def test_is_valid_false_for_invalid_decision(self):
        from src.phases.phase_6_bridge import BridgeDecision
        d = BridgeDecision(decision="invalid")
        assert d.is_valid is False

    def test_is_valid_false_when_error_present(self):
        from src.phases.phase_6_bridge import BridgeDecision
        d = BridgeDecision(decision="app_dev", error="something wrong")
        assert d.is_valid is False


# ===========================================================================
# 2. document_done 경로
# ===========================================================================

class TestDocumentDone:
    def test_document_done_returns_end(self):
        from src.phases.phase_6_bridge import decide_track, DECISION_DOCUMENT_DONE
        d = decide_track("document_done")
        assert d.decision == DECISION_DOCUMENT_DONE
        assert d.next_phase is None
        assert d.error is None
        assert d.is_valid is True

    def test_document_done_has_reason(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("document_done")
        assert d.reason != ""
        assert "문서" in d.reason or "종료" in d.reason


# ===========================================================================
# 3. cancel 경로
# ===========================================================================

class TestCancel:
    def test_cancel_returns_end(self):
        from src.phases.phase_6_bridge import decide_track, DECISION_CANCEL
        d = decide_track("cancel")
        assert d.decision == DECISION_CANCEL
        assert d.next_phase is None
        assert d.deliverable_spec is None
        assert d.is_valid is True

    def test_cancel_has_reason(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("cancel")
        assert "취소" in d.reason


# ===========================================================================
# 4. app_dev 경로
# ===========================================================================

class TestAppDev:
    def test_app_dev_with_valid_target_doc(self):
        from src.phases.phase_6_bridge import (
            decide_track, DECISION_APP_DEV, NEXT_PHASE_7
        )
        d = decide_track(
            "app_dev",
            raw_input="재고관리 시스템 만들어줘",
            target_doc=_sample_target_doc(),
        )
        assert d.decision == DECISION_APP_DEV
        assert d.next_phase == NEXT_PHASE_7
        assert d.deliverable_spec is not None
        assert d.error is None
        assert d.is_valid is True

    def test_app_dev_without_target_doc_fails(self):
        from src.phases.phase_6_bridge import decide_track, DECISION_APP_DEV
        d = decide_track("app_dev", raw_input="요청")
        assert d.decision == DECISION_APP_DEV  # 사용자 결정은 받았음
        assert d.next_phase is None              # 하지만 전환 불가
        assert d.deliverable_spec is None
        assert d.error is not None
        assert "target_doc" in d.error
        assert d.is_valid is False

    def test_app_dev_with_none_target_doc_fails(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("app_dev", raw_input="요청", target_doc=None)
        assert d.error is not None

    def test_app_dev_with_empty_document_fails(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track(
            "app_dev",
            raw_input="요청",
            target_doc={"document": "", "created_at": "x"},
        )
        assert d.error is not None
        assert "비어있" in d.error or "변환 실패" in d.error

    def test_app_dev_with_whitespace_only_document_fails(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track(
            "app_dev",
            raw_input="요청",
            target_doc={"document": "   \n\t  "},
        )
        assert d.error is not None

    def test_app_dev_target_doc_not_dict_fails(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track(
            "app_dev",
            raw_input="요청",
            target_doc="this is a string not a dict",
        )
        assert d.error is not None


# ===========================================================================
# 5. deliverable_spec 스키마 검증
# ===========================================================================

class TestDeliverableSpecSchema:
    def test_spec_has_required_keys(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track(
            "app_dev",
            raw_input="재고관리 시스템 만들어줘",
            target_doc=_sample_target_doc(),
        )
        spec = d.deliverable_spec
        # v3 deliverable_spec 스키마 호환
        for key in ["goal", "description", "target_files", "constraints", "source"]:
            assert key in spec, f"필수 키 누락: {key}"

    def test_spec_goal_is_raw_input(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track(
            "app_dev",
            raw_input="재고관리 시스템 만들어줘",
            target_doc=_sample_target_doc(),
        )
        assert "재고관리" in d.deliverable_spec["goal"]

    def test_spec_description_is_target_doc_content(self):
        from src.phases.phase_6_bridge import decide_track
        target = _sample_target_doc()
        d = decide_track("app_dev", raw_input="요청", target_doc=target)
        assert target["document"].strip() in d.deliverable_spec["description"]

    def test_spec_target_files_empty_list(self):
        """target_files는 Phase 7 planner가 채움 — 여기서는 빈 list"""
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("app_dev", raw_input="요청", target_doc=_sample_target_doc())
        assert d.deliverable_spec["target_files"] == []
        assert isinstance(d.deliverable_spec["target_files"], list)

    def test_spec_source_is_phase_3(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("app_dev", raw_input="요청", target_doc=_sample_target_doc())
        assert d.deliverable_spec["source"] == "phase_3_target_doc"

    def test_spec_constraints_non_empty(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("app_dev", raw_input="요청", target_doc=_sample_target_doc())
        assert len(d.deliverable_spec["constraints"]) > 0

    def test_spec_created_from_preserves_context(self):
        from src.phases.phase_6_bridge import decide_track
        target = _sample_target_doc()
        d = decide_track("app_dev", raw_input="원본 요청", target_doc=target)
        created_from = d.deliverable_spec.get("created_from", {})
        assert created_from.get("raw_input") == "원본 요청"
        assert created_from.get("target_doc_created_at") == target["created_at"]


# ===========================================================================
# 6. 잘못된 user_decision
# ===========================================================================

class TestInvalidDecision:
    @pytest.mark.parametrize("bad_input", [
        "unknown",
        "yes",
        "no",
        "continue",
        "exit",
    ])
    def test_unknown_strings_rejected(self, bad_input):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track(bad_input)
        assert d.error is not None
        assert d.is_valid is False
        assert d.decision == "invalid"

    def test_empty_string_rejected(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("")
        assert d.error is not None
        assert d.is_valid is False

    def test_none_rejected(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track(None)
        assert d.error is not None

    def test_numeric_rejected(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track(123)
        assert d.error is not None


# ===========================================================================
# 7. 입력 정규화 (공백/대소문자)
# ===========================================================================

class TestInputNormalization:
    def test_uppercase_accepted(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("APP_DEV", raw_input="요청", target_doc=_sample_target_doc())
        assert d.is_valid is True

    def test_mixed_case_accepted(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("App_Dev", raw_input="요청", target_doc=_sample_target_doc())
        assert d.is_valid is True

    def test_leading_trailing_whitespace_stripped(self):
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("  document_done  ")
        assert d.is_valid is True

    def test_inner_whitespace_rejected(self):
        """'app dev' (공백 있음)은 거절 (key는 언더스코어)"""
        from src.phases.phase_6_bridge import decide_track
        d = decide_track("app dev", raw_input="x", target_doc=_sample_target_doc())
        assert d.error is not None


# ===========================================================================
# 8. convert_target_doc_to_spec 단위 테스트
# ===========================================================================

class TestConvertTargetDocToSpec:
    def test_basic_conversion(self):
        from src.phases.phase_6_bridge import convert_target_doc_to_spec
        target = _sample_target_doc()
        spec = convert_target_doc_to_spec(target, "재고관리 앱")
        assert spec["goal"] == "재고관리 앱"
        assert "재고관리" in spec["description"]

    def test_empty_target_doc_raises(self):
        from src.phases.phase_6_bridge import convert_target_doc_to_spec
        with pytest.raises(ValueError):
            convert_target_doc_to_spec(None, "요청")

    def test_empty_document_raises(self):
        from src.phases.phase_6_bridge import convert_target_doc_to_spec
        with pytest.raises(ValueError):
            convert_target_doc_to_spec({"document": ""}, "요청")

    def test_missing_document_key_raises(self):
        from src.phases.phase_6_bridge import convert_target_doc_to_spec
        with pytest.raises(ValueError):
            convert_target_doc_to_spec({"other_key": "x"}, "요청")

    def test_empty_raw_input_handled(self):
        from src.phases.phase_6_bridge import convert_target_doc_to_spec
        spec = convert_target_doc_to_spec(_sample_target_doc(), "")
        # 원본 요청 없어도 변환은 가능 (goal에 placeholder)
        assert spec["goal"] != ""


# ===========================================================================
# 9. 스모크 테스트
# ===========================================================================

class TestSmoke:
    def test_all_paths_return_bridge_decision(self):
        from src.phases.phase_6_bridge import decide_track, BridgeDecision

        cases = [
            ("document_done", "", None),
            ("cancel", "", None),
            ("app_dev", "요청", _sample_target_doc()),
            ("app_dev", "요청", None),  # 실패 케이스
            ("unknown", "", None),
            ("", "", None),
        ]
        for decision, raw, target in cases:
            d = decide_track(decision, raw_input=raw, target_doc=target)
            assert isinstance(d, BridgeDecision)
            assert d.decision in {"document_done", "app_dev", "cancel", "invalid"}
