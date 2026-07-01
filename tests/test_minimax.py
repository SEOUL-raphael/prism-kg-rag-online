import unittest

from govrag.minimax import stream_events_from_chunk


class MiniMaxStreamTests(unittest.TestCase):
    def test_stream_events_extract_reasoning_and_answer(self):
        chunk = {
            "choices": [
                {
                    "delta": {
                        "reasoning_content": "근거를 확인합니다.",
                        "content": "답변 일부",
                    }
                }
            ]
        }
        events = list(stream_events_from_chunk(chunk))
        self.assertEqual(events[0]["type"], "reasoning_delta")
        self.assertEqual(events[1]["type"], "answer_delta")

    def test_stream_events_extract_usage_chunk(self):
        events = list(stream_events_from_chunk({"choices": [], "usage": {"total_tokens": 3}}))
        self.assertEqual(events[0]["type"], "usage")


if __name__ == "__main__":
    unittest.main()
