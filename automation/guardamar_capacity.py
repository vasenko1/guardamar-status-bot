"""Fail-closed OCI capacity audit for the future guardamar-bot instance.

The committed GitHub workflow invokes only ``audit``.  The launch entry point
is deliberately build-disabled until a separate owner-approved change enables
it, so credentials alone cannot make this revision create an instance.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence


REGION = "eu-madrid-3"
AVAILABILITY_DOMAIN = "OhIQ:EU-MADRID-3-AD-1"
COMPARTMENT_OCID = (
    "ocid1.tenancy.oc1..aaaaaaaapdyqhnggirlwkrratalmp4hio25ol6rd2xgrav"
    "p3kazcv67dsqfa"
)
DISPLAY_NAME = "guardamar-bot"
SHAPE = "VM.Standard.A1.Flex"
OCPUS = 1.0
MEMORY_GBS = 6.0
IMAGE_OCID = (
    "ocid1.image.oc1.eu-madrid-3.aaaaaaaaurntbnbuaaicth3wbgs77lkqcb6giko"
    "55bl6tfkqjk472gvvl6yq"
)
SUBNET_OCID = (
    "ocid1.subnet.oc1.eu-madrid-3.aaaaaaaanuiwwug7n4gn4djssg4ztnamwtc56"
    "j2rwnjes5e6chko6hjif7oa"
)
SSH_PUBLIC_KEY = (
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCIEmd3EFLBTqOqZS2byGLG7rwl8m"
    "KH/u2KnIb4nk9XQ4lwqrtrePXtBpflecRVqSD0Rit7qVBFIG6NalPq6qtP0pfVrIp1"
    "vjG+t/r8yaHIc42VYuJI3VUydi4QVQTe6ZCTBV+t0+VBSmnaMriA4CfutP1NHV0G"
    "d1LTDMQe9lg34UOCRvUD0l428Y0tXGPRCDj1eiwCfd8/MqTNUgMZQ8sUt1Zx+Mfn"
    "n1KFafgmMlXCKAapjJS1VJ6N+law76wjsLiNTL9pycCDxa6m0fFO7uj8IDyNX7vp"
    "XB+BnNfOok06HexE17/cZXxY+qGB2bHJx1L/31KjH8uqMeyB2llhcpEd "
    "ssh-key-2026-09-07"
)

# These are cost-safety ceilings, not the larger trial service limits returned
# by OCI.  The Stack leaves boot size unset; OCI's current minimum/default is
# therefore conservatively budgeted as 50 GB.
FREE_A1_OCPU_LIMIT = 2.0
FREE_A1_MEMORY_GB_LIMIT = 12.0
FREE_STORAGE_GB_LIMIT = 200.0
EXPECTED_BOOT_VOLUME_GB = 50.0

# Owner approval must arrive in a later, separately reviewed change.  Leaving
# this false makes the launch command unreachable even if flags/env are forged.
LAUNCH_BUILD_ENABLED = False

AGENT_PLUGINS = (
    ("WebLogic Management Service", "DISABLED"),
    ("Vulnerability Scanning", "DISABLED"),
    ("Oracle Java Management Service", "DISABLED"),
    ("OS Management Hub Agent", "DISABLED"),
    ("Management Agent", "DISABLED"),
    ("Fleet Application Management Service", "DISABLED"),
    ("Custom Logs Monitoring", "ENABLED"),
    ("Compute Instance Run Command", "ENABLED"),
    ("Compute Instance Monitoring", "ENABLED"),
    ("Compute HPC RDMA Auto-Configuration", "DISABLED"),
    ("Compute HPC RDMA Authentication", "DISABLED"),
    ("Cloud Guard Workload Protection", "ENABLED"),
    ("Block Volume Management", "DISABLED"),
    ("Bastion", "DISABLED"),
)


class SafetyError(RuntimeError):
    """Raised when an audit cannot prove that a launch is safe."""


@dataclass(frozen=True)
class InstanceRecord:
    identifier: str
    display_name: str
    lifecycle_state: str


@dataclass(frozen=True)
class ImageRecord:
    identifier: str
    lifecycle_state: str
    operating_system: str
    display_name: str


@dataclass(frozen=True)
class ResourceAvailability:
    used: float
    available: float


@dataclass(frozen=True)
class AuditReport:
    region: str
    availability_domain: str
    target_instances: tuple[str, ...]
    a1_ocpus_used: float
    a1_memory_gb_used: float
    free_storage_gb_used: float
    image_name: str
    target_shape_available: bool
    launch_safe: bool
    blockers: tuple[str, ...]


def launch_manifest() -> dict[str, Any]:
    """Return the immutable launch intent recovered from the ORM Stack."""

    return {
        "availability_domain": AVAILABILITY_DOMAIN,
        "compartment_id": COMPARTMENT_OCID,
        "display_name": DISPLAY_NAME,
        "shape": SHAPE,
        "shape_config": {"ocpus": OCPUS, "memory_in_gbs": MEMORY_GBS},
        "source_details": {
            "source_type": "image",
            "image_id": IMAGE_OCID,
        },
        "create_vnic_details": {
            "assign_ipv6_ip": False,
            "assign_private_dns_record": True,
            "assign_public_ip": True,
            "subnet_id": SUBNET_OCID,
        },
        "metadata": {"ssh_authorized_keys": SSH_PUBLIC_KEY},
        "instance_options": {"are_legacy_imds_endpoints_disabled": True},
        "availability_config": {"recovery_action": "RESTORE_INSTANCE"},
        "is_pv_encryption_in_transit_enabled": True,
        "agent_config": {
            "is_management_disabled": False,
            "is_monitoring_disabled": False,
            "plugins_config": [
                {"name": name, "desired_state": state}
                for name, state in AGENT_PLUGINS
            ],
        },
    }


def evaluate_audit(
    instances: Sequence[InstanceRecord],
    image: ImageRecord,
    available_shapes: Sequence[str],
    resource_availability: Mapping[str, ResourceAvailability],
) -> AuditReport:
    """Evaluate all cost and duplicate gates without mutating OCI."""

    required = ("a1_ocpus", "a1_memory_gb", "free_storage_gb")
    missing = [name for name in required if name not in resource_availability]
    if missing:
        raise SafetyError("missing availability data: " + ", ".join(missing))

    target_instances = tuple(
        instance.identifier
        for instance in instances
        if instance.display_name == DISPLAY_NAME
        and instance.lifecycle_state.upper() != "TERMINATED"
    )
    cores = resource_availability["a1_ocpus"]
    memory = resource_availability["a1_memory_gb"]
    storage = resource_availability["free_storage_gb"]
    for name, value in resource_availability.items():
        if value.used < 0 or value.available < 0:
            raise SafetyError(f"invalid availability data for {name}")

    blockers: list[str] = []
    if target_instances:
        blockers.append("a non-terminated guardamar-bot instance already exists")
    if image.identifier != IMAGE_OCID or image.lifecycle_state != "AVAILABLE":
        blockers.append("the exact configured image is not available")
    if image.operating_system != "Oracle Linux":
        blockers.append("the configured image is not Oracle Linux")
    if SHAPE not in available_shapes:
        blockers.append("the configured A1 shape is unavailable for image and AD")
    if cores.used + OCPUS > FREE_A1_OCPU_LIMIT:
        blockers.append("the launch would exceed the 2 Always Free A1 OCPU cap")
    if memory.used + MEMORY_GBS > FREE_A1_MEMORY_GB_LIMIT:
        blockers.append("the launch would exceed the 12 GB Always Free A1 RAM cap")
    if storage.used + EXPECTED_BOOT_VOLUME_GB > FREE_STORAGE_GB_LIMIT:
        blockers.append("the launch would exceed the 200 GB Always Free storage cap")
    if cores.available < OCPUS:
        blockers.append("OCI reports insufficient A1 OCPU service availability")
    if memory.available < MEMORY_GBS:
        blockers.append("OCI reports insufficient A1 RAM service availability")
    if storage.available < EXPECTED_BOOT_VOLUME_GB:
        blockers.append("OCI reports insufficient free storage availability")

    return AuditReport(
        region=REGION,
        availability_domain=AVAILABILITY_DOMAIN,
        target_instances=target_instances,
        a1_ocpus_used=cores.used,
        a1_memory_gb_used=memory.used,
        free_storage_gb_used=storage.used,
        image_name=image.display_name,
        target_shape_available=SHAPE in available_shapes,
        launch_safe=not blockers,
        blockers=tuple(blockers),
    )


class OciGateway:
    """Small OCI adapter; import the off-device SDK only when invoked."""

    def __init__(self, env: Mapping[str, str]) -> None:
        try:
            tenancy = env["OCI_TENANCY_OCID"]
            user = env["OCI_USER_OCID"]
            fingerprint = env["OCI_FINGERPRINT"]
            private_key = env["OCI_PRIVATE_KEY"]
        except KeyError as exc:
            raise SafetyError(f"missing credential {exc.args[0]}") from exc

        import oci

        signer = oci.signer.Signer(
            tenancy=tenancy,
            user=user,
            fingerprint=fingerprint,
            private_key_file_location=None,
            private_key_content=private_key,
        )
        config = {
            "tenancy": tenancy,
            "user": user,
            "fingerprint": fingerprint,
            "key_file": "<private-key-is-kept-in-memory>",
            "region": REGION,
        }
        no_retry = oci.retry.NoneRetryStrategy()
        self._oci = oci
        self._compute = oci.core.ComputeClient(
            config, signer=signer, retry_strategy=no_retry
        )
        self._limits = oci.limits.LimitsClient(
            config, signer=signer, retry_strategy=no_retry
        )

    def list_instances(self) -> list[InstanceRecord]:
        response = self._oci.pagination.list_call_get_all_results(
            self._compute.list_instances,
            COMPARTMENT_OCID,
        )
        return [
            InstanceRecord(item.id, item.display_name or "", item.lifecycle_state)
            for item in response.data
        ]

    def get_image(self) -> ImageRecord:
        item = self._compute.get_image(IMAGE_OCID).data
        return ImageRecord(
            item.id,
            item.lifecycle_state,
            item.operating_system,
            item.display_name,
        )

    def list_shapes(self) -> list[str]:
        response = self._oci.pagination.list_call_get_all_results(
            self._compute.list_shapes,
            COMPARTMENT_OCID,
            availability_domain=AVAILABILITY_DOMAIN,
            image_id=IMAGE_OCID,
        )
        return [item.shape for item in response.data]

    def get_resource_availability(self) -> dict[str, ResourceAvailability]:
        names = {
            "a1_ocpus": ("compute", "standard-a1-core-regional-count"),
            "a1_memory_gb": (
                "compute",
                "standard-a1-memory-regional-count",
            ),
            "free_storage_gb": (
                "block-storage",
                "total-free-storage-gb-regional",
            ),
        }
        result = {}
        for key, (service, limit_name) in names.items():
            item = self._limits.get_resource_availability(
                service, limit_name, COMPARTMENT_OCID
            ).data
            if item.used is None or item.available is None:
                raise SafetyError(f"OCI omitted availability data for {key}")
            result[key] = ResourceAvailability(
                float(item.used), float(item.available)
            )
        return result

    def launch_instance(self, retry_token: str) -> str:
        """Submit one launch request; this is unreachable in this revision."""

        oci = self._oci
        manifest = launch_manifest()
        vnic = oci.core.models.CreateVnicDetails(
            **manifest.pop("create_vnic_details")
        )
        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
            **manifest.pop("shape_config")
        )
        source = oci.core.models.InstanceSourceViaImageDetails(
            **manifest.pop("source_details")
        )
        options = oci.core.models.InstanceOptions(
            **manifest.pop("instance_options")
        )
        availability = oci.core.models.LaunchInstanceAvailabilityConfigDetails(
            **manifest.pop("availability_config")
        )
        plugin_values = manifest["agent_config"].pop("plugins_config")
        plugins = [
            oci.core.models.InstanceAgentPluginConfigDetails(**plugin)
            for plugin in plugin_values
        ]
        agent = oci.core.models.LaunchInstanceAgentConfigDetails(
            plugins_config=plugins,
            **manifest.pop("agent_config"),
        )
        details = oci.core.models.LaunchInstanceDetails(
            create_vnic_details=vnic,
            shape_config=shape_config,
            source_details=source,
            instance_options=options,
            availability_config=availability,
            agent_config=agent,
            **manifest,
        )
        response = self._compute.launch_instance(
            details,
            opc_retry_token=retry_token,
            retry_strategy=oci.retry.NoneRetryStrategy(),
        )
        return response.data.id


def audit(gateway: Any) -> AuditReport:
    return evaluate_audit(
        gateway.list_instances(),
        gateway.get_image(),
        gateway.list_shapes(),
        gateway.get_resource_availability(),
    )


def _retry_token(env: Mapping[str, str]) -> str:
    run_id = env.get("GITHUB_RUN_ID", "local")
    run_attempt = env.get("GITHUB_RUN_ATTEMPT", "1")
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"guardamar-capacity:{run_id}:{run_attempt}",
        )
    )


def main(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    gateway_factory: Any = OciGateway,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("audit", help="perform read-only safety checks")
    launch_parser = subparsers.add_parser(
        "launch", help="owner-gated launch (disabled in this revision)"
    )
    launch_parser.add_argument("--allow-launch", action="store_true")
    args = parser.parse_args(argv)
    current_env = os.environ if env is None else env

    if args.command == "launch":
        if not LAUNCH_BUILD_ENABLED:
            raise SafetyError("launch is build-disabled pending owner approval")
        if not args.allow_launch:
            raise SafetyError("launch requires the explicit CLI gate")
        if current_env.get("GUARDAMAR_LAUNCH_SWITCH") != "OWNER_AUTHORIZED":
            raise SafetyError("launch requires the owner-authorized switch")

    gateway = gateway_factory(current_env)
    report = audit(gateway)
    print(json.dumps(asdict(report), sort_keys=True))

    if args.command == "audit":
        return 0
    if not report.launch_safe:
        raise SafetyError("launch preflight blocked: " + "; ".join(report.blockers))

    # Close the check/use window as far as OCI permits: re-read every gate just
    # before the single idempotent create request.
    final_report = audit(gateway)
    if not final_report.launch_safe:
        raise SafetyError(
            "final launch preflight blocked: " + "; ".join(final_report.blockers)
        )
    identifier = gateway.launch_instance(_retry_token(current_env))
    print(json.dumps({"launched_instance_id": identifier}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        raise SystemExit(2)
