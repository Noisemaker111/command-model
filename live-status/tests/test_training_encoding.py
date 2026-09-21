import unittest

from training.train import encode


class FakeTokenizer:
    eos_token_id = 999

    def __call__(self, text, add_special_tokens):
        class Encoded:
            pass
        encoded = Encoded()
        encoded.input_ids = [7] if text.startswith(" ") else list(range(len(text)))
        return encoded


class TrainingEncodingTests(unittest.TestCase):
    def test_long_prompt_keeps_head_and_tail(self):
        tok = FakeTokenizer()
        ids, labels = encode(tok, "echo " + "x" * 5000, "Done.", False, 128, structured=True)
        prompt = ids[:-2]
        self.assertEqual(len(ids), 128)
        self.assertEqual(prompt[0], 0)
        self.assertGreater(prompt[-1], 1000)
        self.assertEqual(labels[:len(prompt)], [-100] * len(prompt))


if __name__ == "__main__":
    unittest.main()
