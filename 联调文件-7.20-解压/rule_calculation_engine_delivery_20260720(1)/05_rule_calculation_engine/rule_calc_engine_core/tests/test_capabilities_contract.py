from __future__ import annotations

import unittest

from app.platform_instruction import PUBLIC_PLATFORM_ACTIONS


class CapabilitiesContractTests(unittest.TestCase):
    def test_only_public_platform_actions_are_advertised(self) -> None:
        advertised = PUBLIC_PLATFORM_ACTIONS

        self.assertEqual(
            set(advertised),
            {"rule.evaluate", "rule.candidate_skill_apply", "rule.candidate_trial"},
        )
        self.assertNotIn("rule.calculate", advertised)


if __name__ == "__main__":
    unittest.main()
