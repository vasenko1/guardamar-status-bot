import os
import unittest
from pathlib import Path
from unittest.mock import patch

from automation import guardamar_capacity as capacity


def availability(cores=0, memory=0, storage=0):
    return {
        "a1_ocpus": capacity.ResourceAvailability(cores, 16 - cores),
        "a1_memory_gb": capacity.ResourceAvailability(memory, 96 - memory),
        "free_storage_gb": capacity.ResourceAvailability(
            storage, 200 - storage
        ),
    }


def image(identifier=capacity.IMAGE_OCID, state="AVAILABLE", os_name="Oracle Linux"):
    return capacity.ImageRecord(identifier, state, os_name, "Oracle-Linux-9.8")


class CapacityAuditTests(unittest.TestCase):
    def test_empty_tenancy_closes_all_launch_preflight_gates(self):
        report = capacity.evaluate_audit(
            [], image(), [capacity.SHAPE], availability()
        )

        self.assertTrue(report.launch_safe)
        self.assertEqual(report.target_instances, ())
        self.assertEqual(report.free_storage_gb_used, 0)

    def test_blocks_every_nonterminated_target_state(self):
        states = (
            "MOVING",
            "PROVISIONING",
            "RUNNING",
            "STARTING",
            "STOPPED",
            "STOPPING",
            "TERMINATING",
            "UNKNOWN_FUTURE_STATE",
        )
        for state in states:
            with self.subTest(state=state):
                report = capacity.evaluate_audit(
                    [capacity.InstanceRecord("instance-id", "guardamar-bot", state)],
                    image(),
                    [capacity.SHAPE],
                    availability(),
                )
                self.assertFalse(report.launch_safe)
                self.assertEqual(report.target_instances, ("instance-id",))

    def test_terminated_target_does_not_block(self):
        report = capacity.evaluate_audit(
            [capacity.InstanceRecord("old", "guardamar-bot", "TERMINATED")],
            image(),
            [capacity.SHAPE],
            availability(),
        )
        self.assertTrue(report.launch_safe)

    def test_strict_free_tier_boundaries_allow_exact_fit(self):
        report = capacity.evaluate_audit(
            [], image(), [capacity.SHAPE], availability(1, 6, 150)
        )
        self.assertTrue(report.launch_safe)

    def test_strict_free_tier_boundaries_fail_closed(self):
        cases = ((1.1, 6, 0), (1, 6.1, 0), (0, 0, 151))
        for values in cases:
            with self.subTest(values=values):
                report = capacity.evaluate_audit(
                    [], image(), [capacity.SHAPE], availability(*values)
                )
                self.assertFalse(report.launch_safe)

    def test_image_and_shape_are_exact(self):
        wrong_image = capacity.evaluate_audit(
            [], image("wrong"), [capacity.SHAPE], availability()
        )
        wrong_os = capacity.evaluate_audit(
            [], image(os_name="Ubuntu"), [capacity.SHAPE], availability()
        )
        wrong_shape = capacity.evaluate_audit(
            [], image(), ["VM.Standard.E5.Flex"], availability()
        )
        self.assertFalse(wrong_image.launch_safe)
        self.assertFalse(wrong_os.launch_safe)
        self.assertFalse(wrong_shape.launch_safe)

    def test_missing_or_invalid_availability_fails_closed(self):
        with self.assertRaises(capacity.SafetyError):
            capacity.evaluate_audit([], image(), [capacity.SHAPE], {})
        values = availability()
        values["a1_ocpus"] = capacity.ResourceAvailability(-1, 1)
        with self.assertRaises(capacity.SafetyError):
            capacity.evaluate_audit([], image(), [capacity.SHAPE], values)

    def test_manifest_matches_stack_and_keeps_boot_volume_implicit(self):
        manifest = capacity.launch_manifest()
        self.assertEqual(manifest["availability_domain"], capacity.AVAILABILITY_DOMAIN)
        self.assertEqual(manifest["compartment_id"], capacity.COMPARTMENT_OCID)
        self.assertEqual(manifest["display_name"], "guardamar-bot")
        self.assertEqual(manifest["shape"], "VM.Standard.A1.Flex")
        self.assertEqual(
            manifest["shape_config"], {"ocpus": 1.0, "memory_in_gbs": 6.0}
        )
        self.assertEqual(manifest["source_details"]["image_id"], capacity.IMAGE_OCID)
        self.assertNotIn("boot_volume_size_in_gbs", manifest["source_details"])
        self.assertEqual(
            manifest["create_vnic_details"]["subnet_id"], capacity.SUBNET_OCID
        )
        self.assertTrue(manifest["create_vnic_details"]["assign_public_ip"])
        self.assertFalse(manifest["create_vnic_details"]["assign_ipv6_ip"])
        self.assertTrue(manifest["is_pv_encryption_in_transit_enabled"])
        self.assertTrue(
            manifest["instance_options"]["are_legacy_imds_endpoints_disabled"]
        )

    def test_launch_is_unreachable_even_with_cli_and_environment_gates(self):
        factory_called = False

        def factory(_env):
            nonlocal factory_called
            factory_called = True
            raise AssertionError("credentials must not be loaded")

        with self.assertRaisesRegex(capacity.SafetyError, "build-disabled"):
            capacity.main(
                ["launch", "--allow-launch"],
                {"GUARDAMAR_LAUNCH_SWITCH": "OWNER_AUTHORIZED"},
                factory,
            )
        self.assertFalse(factory_called)

    def test_workflow_is_read_only_and_not_exposed_to_pull_requests(self):
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "guardamar-capacity.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("python -m automation.guardamar_capacity audit", workflow)
        self.assertNotIn("automation.guardamar_capacity launch", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("GUARDAMAR_LAUNCH_SWITCH", workflow)

    def test_retry_token_is_stable_for_one_workflow_attempt(self):
        env = {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
        self.assertEqual(capacity._retry_token(env), capacity._retry_token(env))
        self.assertNotEqual(
            capacity._retry_token(env),
            capacity._retry_token({**env, "GITHUB_RUN_ATTEMPT": "3"}),
        )


if __name__ == "__main__":
    unittest.main()
