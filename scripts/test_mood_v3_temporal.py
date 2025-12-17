import sys
import os
import time
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

def print_test_case(name, bio_params, mood_params, hours_since_release=None):
    print(f"\n=== Test Case: {name} ===")
    
    # Calculate timestamp from hours
    last_release = 0.0
    if hours_since_release is not None:
        last_release = time.time() - (hours_since_release * 3600)
    
    bio_params["last_release_time"] = last_release
    
    # Reset State
    state_manager.bio_state = BiologicalState(**bio_params)
    state_manager.mood_state = MoodState(**mood_params)
    
    # Generate Prompt
    prompt = state_manager.get_system_prompt_injection()
    print(prompt)

def main():
    # 1. Refractory Period (Just released 10 mins ago)
    # Expect: Refractory Lock
    print_test_case(
        "Refractory Period",
        {"cycle_day": 14, "lust": 10, "stamina": 50}, # Lust low after sex
        {"pleasure": 8.0, "arousal": -5.0, "dominance": -2.0},
        hours_since_release=0.15 # 9 mins
    )

    # 2. Afterglow (1 hour ago) - Q2 Clingy Pet
    # Expect: Afterglow description + Emotional Care
    print_test_case(
        "Afterglow (Clingy)",
        {"cycle_day": 14, "lust": 20, "stamina": 60},
        {"pleasure": 8.0, "arousal": -4.0, "dominance": -6.0}, # Happy but submissive
        hours_since_release=1.0
    )

    # 3. Starved (10 days ago) - Q5 Tsundere
    # Expect: Starved description + High Urgency
    print_test_case(
        "Starved (Tsundere)",
        {"cycle_day": 14, "lust": 80, "stamina": 80},
        {"pleasure": -3.0, "arousal": 6.0, "dominance": 6.0}, # Annoyed
        hours_since_release=240.0 # 10 days
    )
    
    # 4. Normal (2 days ago) - Neutral/Vanilla
    # Expect: Vanilla flavor
    print_test_case(
        "Normal (Vanilla)",
        {"cycle_day": 14, "lust": 60, "stamina": 80},
        {"pleasure": 1.0, "arousal": -1.0, "dominance": 0.0}, # All Mid
        hours_since_release=48.0
    )

if __name__ == "__main__":
    main()
