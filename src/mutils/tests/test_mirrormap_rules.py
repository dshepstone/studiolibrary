import unittest

from mutils import mirrormap


class TestMirrorMapRules(unittest.TestCase):

    def test_token_swap_namespaced(self):
        self.assertEqual(
            mirrormap._safe_swap_token("ProRigs:ac_rt_index3", "rt", "lf"),
            "ProRigs:ac_lf_index3"
        )

    def test_token_swap_deep_name(self):
        self.assertEqual(
            mirrormap._safe_swap_token("ac_lf_armFK", "lf", "rt"),
            "ac_rt_armFK"
        )

    def test_token_false_positive(self):
        self.assertIsNone(mirrormap._safe_swap_token("shirt", "rt", "lf"))
        self.assertIsNone(mirrormap._safe_swap_token("upperteeth", "rt", "lf"))

    def test_manual_pair_priority(self):
        mirror_map = mirrormap.MirrorMap("rig")
        mirror_map.manual_pairs["ac_rt_thumb"] = "ac_lf_thumb1"
        resolver = mirrormap.PartnerResolver(mirror_map)
        self.assertEqual(resolver.resolve_partner_name("ac_rt_thumb"), "ac_lf_thumb1")


if __name__ == "__main__":
    unittest.main()
