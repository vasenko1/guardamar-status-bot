import tempfile
import unittest
from pathlib import Path

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


def subnet(identifier=capacity.SUBNET_OCID, state="AVAILABLE", prohibit=False):
    return capacity.SubnetRecord(identifier, state, None, prohibit)


def record(
    identifier="instance-id",
    name=capacity.DISPLAY_NAME,
    state="RUNNING",
    tags=None,
):
    return capacity.InstanceRecord(identifier, name, state, tags or {})


def details(identifier="instance-id", state="RUNNING", **changes):
    values = {
        "identifier": identifier,
        "display_name": capacity.DISPLAY_NAME,
        "lifecycle_state": state,
        "shape": capacity.SHAPE,
        "ocpus": capacity.OCPUS,
        "memory_in_gbs": capacity.MEMORY_GBS,
        "image_id": capacity.IMAGE_OCID,
        "availability_domain": capacity.AVAILABILITY_DOMAIN,
        "freeform_tags": {},
    }
    values.update(changes)
    return capacity.InstanceDetails(**values)


class FakeError(Exception):
    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class FakeGateway:
    def __init__(self):
        self.instance_snapshots = [[]]
        self.instance_reads = [details()]
        self.launch_error = None
        self.launch_calls = []
        self.vnics = [
            capacity.VnicRecord("vnic-id", capacity.SUBNET_OCID, "203.0.113.7")
        ]

    def list_instances(self):
        if len(self.instance_snapshots) > 1:
            return self.instance_snapshots.pop(0)
        return self.instance_snapshots[0]

    def get_image(self):
        return image()

    def get_subnet(self):
        return subnet()

    def list_shapes(self):
        return [capacity.SHAPE]

    def get_resource_availability(self):
        return availability()

    def get_instance(self, _identifier):
        if len(self.instance_reads) > 1:
            return self.instance_reads.pop(0)
        return self.instance_reads[0]

    def get_primary_vnic(self, _identifier):
        if len(self.vnics) > 1:
            value = self.vnics.pop(0)
        else:
            value = self.vnics[0]
        if isinstance(value, Exception):
            raise value
        return value

    def launch_instance(self, token):
        self.launch_calls.append(token)
        if self.launch_error:
            raise self.launch_error
        return "instance-id"


class CapacityAuditTests(unittest.TestCase):
    def test_empty_tenancy_closes_all_launch_preflight_gates(self):
        report = capacity.evaluate_audit(
            [], image(), subnet(), [capacity.SHAPE], availability()
        )

        self.assertTrue(report.launch_safe)
        self.assertTrue(report.target_subnet_available)
        self.assertEqual(report.target_instances, ())

    def test_name_or_managed_tag_blocks_every_nonterminated_state(self):
        cases = (
            record(state="PROVISIONING"),
            record(name="renamed", tags={capacity.MANAGED_TAG: "true"}),
            record(name="renamed", tags={capacity.TARGET_TAG: capacity.DISPLAY_NAME}),
            record(state="UNKNOWN_FUTURE_STATE"),
        )
        for instance in cases:
            with self.subTest(instance=instance):
                report = capacity.evaluate_audit(
                    [instance], image(), subnet(), [capacity.SHAPE], availability()
                )
                self.assertFalse(report.launch_safe)

    def test_terminated_target_does_not_block(self):
        report = capacity.evaluate_audit(
            [record(state="TERMINATED")],
            image(),
            subnet(),
            [capacity.SHAPE],
            availability(),
        )
        self.assertTrue(report.launch_safe)

    def test_subnet_must_be_exact_available_and_allow_public_ip(self):
        cases = (
            subnet(identifier="wrong"),
            subnet(state="TERMINATED"),
            subnet(prohibit=True),
            capacity.SubnetRecord(
                capacity.SUBNET_OCID, "AVAILABLE", "another-ad", False
            ),
        )
        for value in cases:
            with self.subTest(subnet=value):
                report = capacity.evaluate_audit(
                    [], image(), value, [capacity.SHAPE], availability()
                )
                self.assertFalse(report.launch_safe)

    def test_strict_free_tier_boundaries_allow_only_exact_fit(self):
        exact = capacity.evaluate_audit(
            [], image(), subnet(), [capacity.SHAPE], availability(1, 6, 150)
        )
        self.assertTrue(exact.launch_safe)
        for values in ((1.1, 6, 0), (1, 6.1, 0), (0, 0, 151)):
            with self.subTest(values=values):
                report = capacity.evaluate_audit(
                    [], image(), subnet(), [capacity.SHAPE], availability(*values)
                )
                self.assertFalse(report.launch_safe)

    def test_image_and_shape_are_exact(self):
        wrong_image = capacity.evaluate_audit(
            [], image("wrong"), subnet(), [capacity.SHAPE], availability()
        )
        wrong_os = capacity.evaluate_audit(
            [], image(os_name="Ubuntu"), subnet(), [capacity.SHAPE], availability()
        )
        wrong_shape = capacity.evaluate_audit(
            [], image(), subnet(), ["VM.Standard.E5.Flex"], availability()
        )
        self.assertFalse(wrong_image.launch_safe)
        self.assertFalse(wrong_os.launch_safe)
        self.assertFalse(wrong_shape.launch_safe)

    def test_manifest_pins_every_cost_and_launch_parameter(self):
        manifest = capacity.launch_manifest()
        self.assertEqual(manifest["availability_domain"], capacity.AVAILABILITY_DOMAIN)
        self.assertEqual(manifest["compartment_id"], capacity.COMPARTMENT_OCID)
        self.assertEqual(manifest["display_name"], "guardamar-bot")
        self.assertEqual(manifest["shape"], "VM.Standard.A1.Flex")
        self.assertEqual(
            manifest["shape_config"], {"ocpus": 1.0, "memory_in_gbs": 6.0}
        )
        self.assertEqual(manifest["source_details"]["image_id"], capacity.IMAGE_OCID)
        self.assertEqual(manifest["source_details"]["boot_volume_size_in_gbs"], 50)
        self.assertEqual(
            manifest["create_vnic_details"]["subnet_id"], capacity.SUBNET_OCID
        )
        self.assertTrue(manifest["create_vnic_details"]["assign_public_ip"])
        self.assertFalse(manifest["create_vnic_details"]["assign_ipv6_ip"])
        self.assertEqual(manifest["freeform_tags"][capacity.MANAGED_TAG], "true")

    def test_launch_still_requires_cli_and_workflow_switch(self):
        factory_called = False

        def factory(_env):
            nonlocal factory_called
            factory_called = True
            return FakeGateway()

        self.assertEqual(capacity.main(["launch"], {}, factory, lambda _: None), 2)
        self.assertEqual(
            capacity.main(
                ["launch", "--allow-launch"], {}, factory, lambda _: None
            ),
            2,
        )
        self.assertFalse(factory_called)

    def test_existing_running_target_is_verified_with_zero_launch_calls(self):
        gateway = FakeGateway()
        gateway.instance_snapshots = [[record()]]

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "READY")
        self.assertEqual(result.public_ip, "203.0.113.7")
        self.assertTrue(result.disable_schedule)
        self.assertEqual(gateway.launch_calls, [])

    def test_existing_mismatched_target_blocks_with_zero_launch_calls(self):
        gateway = FakeGateway()
        gateway.instance_snapshots = [[record()]]
        gateway.instance_reads = [details(shape="VM.Standard.E5.Flex")]

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.disable_schedule)
        self.assertEqual(gateway.launch_calls, [])

    def test_capacity_miss_makes_exactly_one_request_and_no_retry(self):
        gateway = FakeGateway()
        gateway.launch_error = FakeError(
            "Out of host capacity.", status=500, code="InternalError"
        )

        result = capacity.run_launch(
            gateway, {"GITHUB_RUN_ID": "123"}, lambda _: None
        )

        self.assertEqual(result.outcome, "CAPACITY_MISS")
        self.assertFalse(result.disable_schedule)
        self.assertEqual(len(gateway.launch_calls), 1)

    def test_rate_limit_makes_exactly_one_request_and_no_retry(self):
        gateway = FakeGateway()
        gateway.launch_error = FakeError(
            "slow down", status=429, code="TooManyRequests"
        )

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "RATE_LIMITED")
        self.assertEqual(len(gateway.launch_calls), 1)

    def test_fatal_launch_rejection_disables_schedule(self):
        gateway = FakeGateway()
        gateway.launch_error = FakeError("forbidden", status=403, code="NotAuthorized")

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.disable_schedule)
        self.assertEqual(len(gateway.launch_calls), 1)

    def test_ambiguous_response_discovers_instance_before_any_repeat(self):
        gateway = FakeGateway()
        gateway.launch_error = TimeoutError("response lost")
        gateway.instance_snapshots = [[], [], [], [record(state="PROVISIONING")]]
        gateway.instance_reads = [
            details(state="PROVISIONING"),
            details(state="RUNNING"),
        ]

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "READY")
        self.assertEqual(len(gateway.launch_calls), 1)

    def test_unresolved_ambiguous_response_never_retries_and_disables(self):
        gateway = FakeGateway()
        gateway.launch_error = TimeoutError("response lost")

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "AMBIGUOUS")
        self.assertTrue(result.disable_schedule)
        self.assertEqual(len(gateway.launch_calls), 1)

    def test_accepted_launch_waits_for_running_and_verifies_public_ip(self):
        gateway = FakeGateway()
        gateway.instance_reads = [
            details(state="PROVISIONING"),
            details(state="STARTING"),
            details(state="RUNNING"),
        ]

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "READY")
        self.assertEqual(result.instance_id, "instance-id")
        self.assertEqual(result.public_ip, "203.0.113.7")
        self.assertEqual(len(gateway.launch_calls), 1)

    def test_running_instance_waits_for_public_ip_without_another_launch(self):
        gateway = FakeGateway()
        gateway.instance_snapshots = [[record()]]
        gateway.vnics = [
            capacity.VnicRecord("vnic-id", capacity.SUBNET_OCID, None),
            capacity.VnicRecord("vnic-id", capacity.SUBNET_OCID, "203.0.113.7"),
        ]

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "READY")
        self.assertEqual(gateway.launch_calls, [])

    def test_failed_discovery_after_ambiguous_response_disables_schedule(self):
        gateway = FakeGateway()
        gateway.launch_error = TimeoutError("response lost")
        gateway.instance_snapshots = [[], [], TimeoutError("list failed")]
        original_list = gateway.list_instances

        def list_instances():
            value = original_list()
            if isinstance(value, Exception):
                raise value
            return value

        gateway.list_instances = list_instances

        result = capacity.run_launch(gateway, {}, lambda _: None)

        self.assertEqual(result.outcome, "AMBIGUOUS")
        self.assertTrue(result.disable_schedule)
        self.assertEqual(len(gateway.launch_calls), 1)

    def test_retry_token_is_stable_across_reruns_of_same_workflow(self):
        first = {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        rerun = {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
        self.assertEqual(capacity._retry_token(first), capacity._retry_token(rerun))
        self.assertNotEqual(
            capacity._retry_token(first),
            capacity._retry_token({"GITHUB_RUN_ID": "124"}),
        )

    def test_result_writes_safe_github_outputs_and_ready_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            summary = Path(directory) / "summary"
            result = capacity.CapacityResult(
                "READY", "verified", True, "ocid1.instance.example", "203.0.113.7"
            )
            capacity._emit_result(
                result,
                {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)},
            )
            self.assertIn("outcome=READY", output.read_text())
            self.assertIn("disable_schedule=true", output.read_text())
            self.assertIn("VM.Standard.A1.Flex", summary.read_text())
            self.assertNotIn(capacity.SSH_PUBLIC_KEY, summary.read_text())

    def test_workflow_has_one_launch_path_and_a_safe_manual_audit(self):
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "guardamar-capacity.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(workflow.count("automation.guardamar_capacity launch"), 1)
        self.assertEqual(workflow.count("automation.guardamar_capacity audit"), 1)
        self.assertIn('cron: "7,22,37,52 * * * *"', workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("GUARDAMAR_LAUNCH_SWITCH", workflow)
        self.assertNotIn("pull_request:", workflow)


if __name__ == "__main__":
    unittest.main()
