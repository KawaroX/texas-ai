import sys
import os
from unittest.mock import MagicMock

# --- MOCKING REDIS BEFORE IMPORTS ---
# This prevents the actual Redis connection attempt which fails in this environment
mock_redis = MagicMock()
sys.modules["utils.redis_manager"] = MagicMock()
sys.modules["utils.redis_manager"].get_redis_client.return_value = mock_redis
# ------------------------------------

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.state_manager import state_manager
from core.biological_model import BiologicalState
from core.mood_model import MoodState

def print_test_case(name, bio_params, mood_params):
    print(f"\n=== Test Case: {name} ===")
    
    # Reset State
    state_manager.bio_state = BiologicalState(**bio_params)
    state_manager.mood_state = MoodState(**mood_params)
    
    # Generate Prompt
    prompt = state_manager.get_system_prompt_injection()
    print(prompt)

def main():
    # 1. Conflict Check: Menstrual Day 2 (Pain) + High Lust (90)
    # Expect: Physiological Override (Refuse)
    print_test_case(
        "Conflict: Menstrual Pain vs High Lust",
        {"cycle_day": 2, "lust": 90, "stamina": 50},
        {"pleasure": -6.0, "arousal": 2.0, "dominance": -2.0}
    )

    # 2. Lust Dominance: Menstrual Day 4 (Less Pain) + High Lust (90)
    # Expect: Resonance Field (Active but modified)
    print_test_case(
        "Lust Dominance in Menstrual",
        {"cycle_day": 4, "lust": 90, "stamina": 60},
        {"pleasure": 2.0, "arousal": 5.0, "dominance": 2.0}
    )

    # 3. Mind Break: Lust 100
    # Expect: Mind Break
    print_test_case(
        "Mind Break",
        {"cycle_day": 14, "lust": 98, "stamina": 30},
        {"pleasure": 8.0, "arousal": 8.0, "dominance": -5.0}
    )

    # 4. Flavor Check: Q1 (Conqueror)
    # High P, High A, High D
    print_test_case(
        "Flavor: Q1 Conqueror",
        {"cycle_day": 14, "lust": 60, "stamina": 80},
        {"pleasure": 6.0, "arousal": 6.0, "dominance": 6.0}
    )

    # 5. Flavor Check: Q5 (Tsundere)
    # Low P, High A, High D
    print_test_case(
        "Flavor: Q5 Tsundere",
        {"cycle_day": 20, "lust": 60, "stamina": 70},
        {"pleasure": -4.0, "arousal": 5.0, "dominance": 5.0}
    )
    
    # 6. Susceptibility Check (High Arousal)
    print_test_case(
        "Modifier: High Arousal",
        {"cycle_day": 14, "lust": 50, "stamina": 80},
        {"pleasure": 1.0, "arousal": 8.0, "dominance": 1.0}
    )
    
    # 7. Low Lust / Base State
    print_test_case(
        "Base State: Normal",
        {"cycle_day": 14, "lust": 20, "stamina": 90},
        {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0}
    )

if __name__ == "__main__":
    main()