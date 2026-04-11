"""CODEX/WARBRAIN Conversation API -- MVP Demo Script

Walks through all three evaluation outcomes:
1. Supported -- well-specified urban defense COA
2. Conditional -- same scenario with unknown preconditions and missing observations
3. Abstain (no coverage) -- sparse request with no retriever match
4. Abstain (no coverage) -- request outside doctrinal scope
5. Multi-turn -- sparse request -> clarification -> enriched evaluation
"""

import httpx
import json
import os

BASE = os.getenv("WARBRAIN_BASE_URL", "http://127.0.0.1:8000/v1")


def pp(label: str, data: dict):
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")
    print(json.dumps(data, indent=2))


def main():
    client = httpx.Client(timeout=30)

    # --- Health Check ---
    try:
        r = client.get(f"{BASE}/health")
        r.raise_for_status()
        health = r.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        print("DEMO STARTUP ERROR")
        print(f"Unable to reach a healthy API at {BASE}.")
        print(f"Details: {exc}")
        print("Start the API server and/or set WARBRAIN_BASE_URL, then retry.")
        return

    pp("Health Check", health)

    input("\n>>> Press Enter for Scenario 1: SUPPORTED >>>")

    # =========================================================================
    # SCENARIO 1: SUPPORTED -- Full COA with all preconditions met
    # =========================================================================
    print("\n\n" + "#"*80)
    print("# SCENARIO 1: SUPPORTED -- Full urban defense COA")
    print("#"*80)

    r = client.post(f"{BASE}/sessions", json={"metadata": {"demo": "scenario_1_supported"}})
    session = r.json()
    session_id = session["id"]
    pp("Session Created", session)

    artifact = {
        "artifact": {
            "artifact_type": "course_of_action",
            "objective": "Defend urban terrain against mechanized infantry advance",
            "context_envelope": {
                "echelon": "battalion",
                "phase": "defensive_operations",
                "mission_type": "area_defense",
                "domain": "land"
            },
            "situation": {
                "friendly_forces": {"composition": "infantry_battalion", "strength": "85_percent"},
                "enemy_forces": {"type": "mechanized_infantry", "estimated_size": "battalion", "approach": "north"},
                "terrain": {"type": "urban", "key_terrain": ["bridge_alpha", "hill_205"]},
                "time": {"phase": "H+0", "timeline": "12_hours"}
            },
            "observations": [
                "enemy_composition_confirmed",
                "engagement_area_identified",
                "obstacle_plan_coordinated",
                "target_reference_points_registered",
                "fire_support_available",
                "priority_of_fires_established"
            ],
            "proposed_actions": [
                {
                    "sequence": 1,
                    "action": "establish_engagement_area",
                    "parameters": {"location": "EA_alpha", "type": "armor_kill_zone"},
                    "intended_effects": ["canalize_enemy_armor", "enable_massed_fires"]
                },
                {
                    "sequence": 2,
                    "action": "position_direct_fire_weapons",
                    "parameters": {"assets": "javelin_teams", "orientation": "north"},
                    "intended_effects": ["achieve_interlocking_fires"]
                }
            ],
            "preconditions": [
                {"condition": "friendly_forces_in_position", "status": True},
                {"condition": "fire_support_available", "status": True},
                {"condition": "obstacle_plan_coordinated", "status": True}
            ],
            "constraints": [
                {"type": "roe", "value": "ROE alpha"},
                {"type": "boundary", "value": "no operations east of grid line 42"}
            ],
            "triggers": ["enemy_armor_approaching", "defensive_positions_established"]
        }
    }

    r = client.post(f"{BASE}/sessions/{session_id}/messages", json=artifact)
    pp("EVALUATION RESULT (Expected: SUPPORTED)", r.json())

    input("\n>>> Press Enter for Scenario 2: CONDITIONAL >>>")

    # =========================================================================
    # SCENARIO 2: CONDITIONAL -- Missing preconditions and observations
    # =========================================================================
    print("\n\n" + "#"*80)
    print("# SCENARIO 2: CONDITIONAL -- Unknown fire support, missing observations")
    print("#"*80)

    r = client.post(f"{BASE}/sessions", json={"metadata": {"demo": "scenario_2_conditional"}})
    session_id = r.json()["id"]

    artifact_conditional = {
        "artifact": {
            "artifact_type": "course_of_action",
            "objective": "Defend urban terrain against mechanized infantry advance",
            "context_envelope": {
                "echelon": "battalion",
                "phase": "defensive_operations",
                "mission_type": "area_defense",
                "domain": "land"
            },
            "situation": {
                "friendly_forces": {"composition": "infantry_battalion", "strength": "85_percent"},
                "enemy_forces": {"type": "mechanized_infantry", "estimated_size": "battalion", "approach": "north"},
                "terrain": {"type": "urban"}
            },
            "observations": ["engagement_area_identified"],
            "proposed_actions": [
                {
                    "sequence": 1,
                    "action": "establish_engagement_area",
                    "parameters": {"location": "EA_alpha", "type": "armor_kill_zone"},
                    "intended_effects": ["canalize_enemy_armor"]
                }
            ],
            "preconditions": [
                {"condition": "friendly_forces_in_position", "status": True},
                {"condition": "fire_support_available", "status": "unknown"}
            ],
            "constraints": [
                {"type": "roe", "value": "ROE alpha"}
            ],
            "triggers": ["enemy_armor_approaching", "defensive_positions_established"]
        }
    }

    r = client.post(f"{BASE}/sessions/{session_id}/messages", json=artifact_conditional)
    pp("EVALUATION RESULT (Expected: CONDITIONAL)", r.json())

    input("\n>>> Press Enter for Scenario 3: ABSTAIN (sparse) >>>")

    # =========================================================================
    # SCENARIO 3: ABSTAIN (no coverage) -- Very sparse request
    # =========================================================================
    print("\n\n" + "#"*80)
    print("# SCENARIO 3: ABSTAIN -- Sparse request, no situation details")
    print("#"*80)

    r = client.post(f"{BASE}/sessions", json={"metadata": {"demo": "scenario_3_abstain"}})
    session_id = r.json()["id"]

    artifact_sparse = {
        "artifact": {
            "artifact_type": "course_of_action",
            "objective": "Defend urban terrain against mechanized infantry advance"
        }
    }

    r = client.post(f"{BASE}/sessions/{session_id}/messages", json=artifact_sparse)
    pp("EVALUATION RESULT (Expected: ABSTAIN with no_doctrinal_coverage)", r.json())

    input("\n>>> Press Enter for Scenario 4: ABSTAIN (out of scope) >>>")

    # =========================================================================
    # SCENARIO 4: ABSTAIN (no coverage) -- Outside doctrinal scope
    # =========================================================================
    print("\n\n" + "#"*80)
    print("# SCENARIO 4: ABSTAIN -- No doctrinal coverage")
    print("#"*80)

    r = client.post(f"{BASE}/sessions", json={"metadata": {"demo": "scenario_4_no_coverage"}})
    session_id = r.json()["id"]

    artifact_no_coverage = {
        "artifact": {
            "artifact_type": "other",
            "objective": "Negotiate trade agreement with allied nation regarding semiconductor supply chain"
        }
    }

    r = client.post(f"{BASE}/sessions/{session_id}/messages", json=artifact_no_coverage)
    pp("EVALUATION RESULT (Expected: ABSTAIN with no_doctrinal_coverage)", r.json())

    input("\n>>> Press Enter for Scenario 5: MULTI-TURN >>>")

    # =========================================================================
    # SCENARIO 5: MULTI-TURN -- Sparse -> Clarification -> Enriched evaluation
    # =========================================================================
    print("\n\n" + "#"*80)
    print("# SCENARIO 5: MULTI-TURN -- Sparse request, clarify, then evaluate")
    print("#"*80)

    r = client.post(f"{BASE}/sessions", json={"metadata": {"demo": "scenario_5_multi_turn"}})
    session_id = r.json()["id"]
    pp("Session Created", r.json())

    # Turn 1: Sparse request
    sparse = {
        "artifact": {
            "artifact_type": "course_of_action",
            "objective": "Conduct movement to contact to develop the situation",
            "triggers": ["advance_to_contact_ordered"]
        }
    }

    r = client.post(f"{BASE}/sessions/{session_id}/messages", json=sparse)
    turn1 = r.json()
    pp("Turn 1: Sparse Request (Expected: ABSTAIN with questions)", turn1)

    input("\n>>> Press Enter to send clarification (Turn 2) >>>")

    # Turn 2: Clarification response
    clarification = {
        "clarification": {
            "clarification_responses": [
                {
                    "question_id": "q1",
                    "answer": {"composition": "infantry_company_reinforced", "strength": "92_percent"}
                },
                {
                    "question_id": "q2",
                    "answer": {"enemy_type": "unknown", "estimated_size": "platoon_to_company"}
                },
                {
                    "question_id": "q3",
                    "answer": {
                        "context_envelope": {
                            "echelon": "company",
                            "phase": "offensive_operations",
                            "mission_type": "movement_to_contact",
                            "domain": "land"
                        }
                    }
                }
            ]
        }
    }

    r = client.post(f"{BASE}/sessions/{session_id}/messages", json=clarification)
    pp("Turn 2: After Clarification (Expected: SUPPORTED or CONDITIONAL)", r.json())

    # Check session history
    r = client.get(f"{BASE}/sessions/{session_id}")
    pp("Session History", r.json())

    print("\n\n" + "="*80)
    print("  DEMO COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
