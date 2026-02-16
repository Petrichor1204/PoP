from database import get_recent_decisions
from app import validate_decision
import json


def test_validation_rules():
    # Case A: Missing Field
    bad_data_1 = {"item_title": "Inception"} # Missing everything else

    # Case B: Impossible Confidence
    bad_data_2 = {
        "item_title": "Inception",
        "verdict": "Yes",
        "confidence": 99, # Way too high
        "potential_mismatches": []
    }

    # Run them through your function and print the results
    print(f"Test A (Missing Fields) Result: {validate_decision(bad_data_1)}")
    print(f"Test B (Bad Confidence) Result: {validate_decision(bad_data_2)}")


if __name__ == '__main__':
    test_validation_rules()

