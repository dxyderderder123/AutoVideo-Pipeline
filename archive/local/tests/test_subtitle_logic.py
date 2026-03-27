
import logging
import sys
from pathlib import Path

# Mock logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_subtitle_fix")

# Import the function to test
# We need to import from src_english.step6_translate
# To do this, we need to add the parent directory to sys.path
sys.path.append(str(Path("v:/Default/Desktop/Self-media/src_english")))

from step6_translate import clean_subtitles, smart_split_text

def test_clean_subtitles():
    print("\n=== Testing clean_subtitles ===")
    
    # Test Case 1: "Dr." split
    input_1 = [
        {"id": "1", "start": "00:00:01,000", "end": "00:00:02,000", "text": "Welcome Dr."},
        {"id": "2", "start": "00:00:02,000", "end": "00:00:04,000", "text": "Mozaffarian to the show."}
    ]
    expected_text_1 = "Welcome Dr. Mozaffarian to the show."
    
    result_1 = clean_subtitles(input_1)
    print(f"Test 1 (Dr. split):")
    print(f"Input: {[s['text'] for s in input_1]}")
    print(f"Output: {[s['text'] for s in result_1]}")
    
    assert len(result_1) == 1
    assert result_1[0]['text'] == expected_text_1
    assert result_1[0]['end'] == "00:00:04,000"
    print("PASS")

    # Test Case 2: Speaker label "David:"
    input_2 = [
        {"id": "1", "start": "00:00:01,000", "end": "00:00:02,000", "text": "David:"},
        {"id": "2", "start": "00:00:02,000", "end": "00:00:04,000", "text": "I agree with that."}
    ]
    expected_text_2 = "David: I agree with that."
    
    result_2 = clean_subtitles(input_2)
    print(f"\nTest 2 (Speaker label):")
    print(f"Input: {[s['text'] for s in input_2]}")
    print(f"Output: {[s['text'] for s in result_2]}")
    
    assert len(result_2) == 1
    assert result_2[0]['text'] == expected_text_2
    print("PASS")

    # Test Case 3: Multiple merges (Dr. A and Mr. B)
    input_3 = [
        {"id": "1", "start": "00:00:01,000", "end": "00:00:02,000", "text": "Hello Dr."},
        {"id": "2", "start": "00:00:02,000", "end": "00:00:03,000", "text": "Smith and Mr."},
        {"id": "3", "start": "00:00:03,000", "end": "00:00:05,000", "text": "Jones."}
    ]
    expected_text_3 = "Hello Dr. Smith and Mr. Jones."
    
    result_3 = clean_subtitles(input_3)
    print(f"\nTest 3 (Chained merges):")
    print(f"Input: {[s['text'] for s in input_3]}")
    print(f"Output: {[s['text'] for s in result_3]}")
    
    assert len(result_3) == 1
    assert result_3[0]['text'] == expected_text_3
    print("PASS")

def test_smart_split():
    print("\n=== Testing smart_split_text ===")
    
    # Test Case 1: Simple split at punctuation
    text_1 = "这是一个测试句子，它应该在这里断开。"
    max_chars = 10
    # Expected: "这是一个测试句子，", "它应该在这里断开。"
    
    result_1 = smart_split_text(text_1, max_chars)
    print(f"Test 1 (Punctuation):")
    print(f"Input: {text_1}")
    print(f"Output: {result_1}")
    
    assert len(result_1) == 2
    assert result_1[0] == "这是一个测试句子，"
    print("PASS")

    # Test Case 2: No punctuation, balanced split
    text_2 = "这是一个没有标点的长句子测试平衡性"
    max_chars = 10
    # Length 16. Should split roughly 8/8.
    
    result_2 = smart_split_text(text_2, max_chars)
    print(f"\nTest 2 (Balance):")
    print(f"Input: {text_2}")
    print(f"Output: {result_2}")
    
    assert len(result_2) == 2
    # Ensure it didn't just chop at 10 (leaving 6)
    assert len(result_2[0]) < 10
    assert len(result_2[1]) < 10
    print("PASS")

if __name__ == "__main__":
    try:
        test_clean_subtitles()
        test_smart_split()
        print("\nALL TESTS PASSED!")
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
    except Exception as e:
        print(f"\nERROR: {e}")
