import sys
import os
import random
from unittest.mock import MagicMock

# --- MOCKING REDIS BEFORE IMPORTS ---
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
    
    # Initialize state
    state_manager.bio_state = BiologicalState(**bio_params)
    state_manager.mood_state = MoodState(**mood_params)
    
    # Inject Mock Pain Levels for deterministic testing
    # Peak on Day 2
    state_manager.bio_state.menstrual_pain_levels = {
        1: 0.6, 2: 0.9, 3: 0.4, 4: 0.1, 5: 0.0
    }
    state_manager.bio_state.menstrual_days = 5
    
    # Generate Prompt
    prompt = state_manager.get_system_prompt_injection()
    print(prompt)

def main():
    # 1. Day 2: Peak Pain (0.9) - Should trigger Pain Block
    print_test_case(
        "Day 2 Peak Pain (Low Lust)",
        {"cycle_day": 2, "lust": 10},
        {"pleasure": -5.0, "arousal": 0.0, "dominance": 0.0}
    )

    # 2. Day 2: Peak Pain (0.9) but High Lust - Should trigger Conditional Lock
    print_test_case(
        "Day 2 Peak Pain (High Lust)",
        {"cycle_day": 2, "lust": 80},
        {"pleasure": -5.0, "arousal": 0.0, "dominance": 0.0}
    )
    
    # 3. Day 4: Mild Pain (0.1) - Should NOT trigger block
    print_test_case(
        "Day 4 Mild Pain",
        {"cycle_day": 4, "lust": 60},
        {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0}
    )

    # 4. Randomized Cycle Check
    print("\n=== Random Cycle Generation Check ===")
    bio = BiologicalState()
    print(f"Cycle 1: Length={bio.cycle_length}, Menstrual={bio.menstrual_days}, PainMap={bio.menstrual_pain_levels}")
    bio.advance_cycle()
    # Force advance to end
    bio.cycle_day = bio.cycle_length
    bio.advance_cycle()
    print(f"Cycle 2: Length={bio.cycle_length}, Menstrual={bio.menstrual_days}, PainMap={bio.menstrual_pain_levels}")

if __name__ == "__main__":
    main()
