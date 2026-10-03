"""Bounded OCI capacity automation for one exact Always Free target."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence


REGION = "eu-madrid-3"
AVAILABILITY_DOMAIN = "OhIQ:EU-MADRID-3-AD-1"
COMPARTMENT_OCID = (
    "ocid1.tenancy.oc1..aaaaaaaapdyqhnggirlwkrratalmp4hio25ol6rd2xgrav"
    "p3kazcv67dsqfa"
)
DISPLAY_NAME = "guardamar-bot"
A1_SHAPE = "VM.Standard.A1.Flex"
A1_OCPUS = 1.0
A1_MEMORY_GBS = 6.0
A1_IMAGE_OCID = (
    "ocid1.image.oc1.eu-madrid-3.aaaaaaaaurntbnbuaaicth3wbgs77lkqcb6giko"
    "55bl6tfkqjk472gvvl6yq"
)
E2_SHAPE = "VM.Standard.E2.1.Micro"
E2_IMAGE_OCID = (
    "ocid1.image.oc1.eu-madrid-3.aaaaaaaa2nsuyzwg7zpslg3xvd4xbt2jlrbs"
    "icyie7uipj2pbhrcryudgjga"
)

# Backward-compatible aliases for the original Stack-derived A1 target.
SHAPE = A1_SHAPE
OCPUS = A1_OCPUS
MEMORY_GBS = A1_MEMORY_GBS
IMAGE_OCID = A1_IMAGE_OCID
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

FREE_A1_OCPU_LIMIT = 2.0
FREE_A1_MEMORY_GB_LIMIT = 12.0
FREE_E2_MICRO_LIMIT = 2.0
FREE_STORAGE_GB_LIMIT = 200.0
BOOT_VOLUME_GB = 50
MANAGED_TAG = "guardamar-capacity-managed"
MANAGED_TAG_VALUE = "true"
TARGET_TAG = "guardamar-capacity-target"

# This revision is explicitly owner-authorized for the exact manifest below.
# The independent workflow switch and all live OCI gates must also be present.
LAUNCH_BUILD_ENABLED = True
LAUNCH_SWITCH_VALUE = "OWNER_AUTHORIZED_PHASE_2"

POLL_DELAYS_SECONDS = (0, 5, 10, 15, 20, 30, 45, 60, 60, 60)
AMBIGUOUS_DISCOVERY_DELAYS_SECONDS = (0, 5, 10, 20, 30)

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
    """Raised when the automation cannot prove a safe action."""


@dataclass(frozen=True)
class LaunchProfile:
    key: str
    shape: str
    image_ocid: str
    ocpus: Optional[float] = None
    memory_gbs: Optional[float] = None


A1_PROFILE = LaunchProfile(
    "a1", A1_SHAPE, A1_IMAGE_OCID, A1_OCPUS, A1_MEMORY_GBS
)
E2_PROFILE = LaunchProfile("e2", E2_SHAPE, E2_IMAGE_OCID)
PROFILES = {profile.key: profile for profile in (A1_PROFILE, E2_PROFILE)}


@dataclass(frozen=True)
class InstanceRecord:
    identifier: str
    display_name: str
    lifecycle_state: str
    freeform_tags: Mapping[str, str]


@dataclass(frozen=True)
class InstanceDetails:
    identifier: str
    display_name: str
    lifecycle_state: str
    shape: str
    ocpus: Optional[float]
    memory_in_gbs: Optional[float]
    image_id: str
    availability_domain: str
    freeform_tags: Mapping[str, str]


@dataclass(frozen=True)
class ImageRecord:
    identifier: str
    lifecycle_state: str
    operating_system: str
    display_name: str


@dataclass(frozen=True)
class SubnetRecord:
    identifier: str
    lifecycle_state: str
    availability_domain: Optional[str]
    prohibit_public_ip_on_vnic: bool


@dataclass(frozen=True)
class VnicRecord:
    identifier: str
    subnet_id: str
    public_ip: Optional[str]


@dataclass(frozen=True)
class ResourceAvailability:
    used: float
    available: float


@dataclass(frozen=True)
class AuditReport:
    profile: str
    region: str
    availability_domain: str
    target_instances: tuple[str, ...]
    target_states: tuple[str, ...]
    a1_ocpus_used: Optional[float]
    a1_memory_gb_used: Optional[float]
    e2_micro_used: Optional[float]
    free_storage_gb_used: float
    image_name: str
    target_shape_available: bool
    target_subnet_available: bool
    launch_safe: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class CapacityResult:
    outcome: str
    message: str
    disable_schedule: bool = False
    instance_id: Optional[str] = None
    public_ip: Optional[str] = None
    report: Optional[AuditReport] = None
    profile: Optional[str] = None

    @property
    def exit_code(self) -> int:
        return 0 if self.outcome in {
            "AUDIT",
            "CAPACITY_MISS",
            "RATE_LIMITED",
            "PENDING",
            "READY",
        } else 2


def launch_manifest(profile: LaunchProfile = A1_PROFILE) -> dict[str, Any]:
    """Return one exact immutable Always Free launch intent."""

    manifest = {
        "availability_domain": AVAILABILITY_DOMAIN,
        "compartment_id": COMPARTMENT_OCID,
        "display_name": DISPLAY_NAME,
        "shape": profile.shape,
        "source_details": {
            "source_type": "image",
            "image_id": profile.image_ocid,
            # Pin the default size so API drift cannot consume paid storage.
            "boot_volume_size_in_gbs": BOOT_VOLUME_GB,
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
        "freeform_tags": {
            MANAGED_TAG: MANAGED_TAG_VALUE,
            TARGET_TAG: DISPLAY_NAME,
        },
    }
    if profile.ocpus is not None and profile.memory_gbs is not None:
        manifest["shape_config"] = {
            "ocpus": profile.ocpus,
            "memory_in_gbs": profile.memory_gbs,
        }
    return manifest


def _is_target(instance: InstanceRecord) -> bool:
    return (
        instance.display_name == DISPLAY_NAME
        or instance.freeform_tags.get(MANAGED_TAG) == MANAGED_TAG_VALUE
        or instance.freeform_tags.get(TARGET_TAG) == DISPLAY_NAME
    ) and instance.lifecycle_state.upper() != "TERMINATED"


def evaluate_audit(
    instances: Sequence[InstanceRecord],
    image: ImageRecord,
    subnet: SubnetRecord,
    available_shapes: Sequence[str],
    resource_availability: Mapping[str, ResourceAvailability],
    profile: LaunchProfile = A1_PROFILE,
) -> AuditReport:
    """Evaluate duplicate, configuration, and strict Always Free cost gates."""

    required = ["free_storage_gb"]
    if profile.key == "a1":
        required.extend(("a1_ocpus", "a1_memory_gb"))
    elif profile.key == "e2":
        required.append("e2_micro_count")
    else:
        raise SafetyError(f"unsupported launch profile {profile.key}")

    missing = [name for name in required if name not in resource_availability]
    if missing:
        raise SafetyError("missing availability data: " + ", ".join(missing))

    targets = tuple(instance for instance in instances if _is_target(instance))
    storage = resource_availability["free_storage_gb"]
    for name, value in resource_availability.items():
        if value.used < 0 or value.available < 0:
            raise SafetyError(f"invalid availability data for {name}")

    subnet_ok = (
        subnet.identifier == SUBNET_OCID
        and subnet.lifecycle_state == "AVAILABLE"
        and not subnet.prohibit_public_ip_on_vnic
        and subnet.availability_domain in (None, AVAILABILITY_DOMAIN)
    )
    blockers: list[str] = []
    if targets:
        blockers.append("a non-terminated target instance already exists")
    if image.identifier != profile.image_ocid or image.lifecycle_state != "AVAILABLE":
        blockers.append("the exact configured image is not available")
    if image.operating_system != "Oracle Linux":
        blockers.append("the configured image is not Oracle Linux")
    if profile.shape not in available_shapes:
        blockers.append("the configured shape is unavailable for image and AD")
    if not subnet_ok:
        blockers.append("the exact subnet cannot safely provide the public VNIC")
    if storage.used + BOOT_VOLUME_GB > FREE_STORAGE_GB_LIMIT:
        blockers.append("the launch would exceed the 200 GB Always Free storage cap")
    if storage.available < BOOT_VOLUME_GB:
        blockers.append("OCI reports insufficient free storage availability")

    a1_cores = resource_availability.get("a1_ocpus")
    a1_memory = resource_availability.get("a1_memory_gb")
    e2_count = resource_availability.get("e2_micro_count")
    if profile.key == "a1":
        assert a1_cores is not None and a1_memory is not None
        if a1_cores.used + A1_OCPUS > FREE_A1_OCPU_LIMIT:
            blockers.append("the launch would exceed the 2 Always Free A1 OCPU cap")
        if a1_memory.used + A1_MEMORY_GBS > FREE_A1_MEMORY_GB_LIMIT:
            blockers.append("the launch would exceed the 12 GB Always Free A1 RAM cap")
        if a1_cores.available < A1_OCPUS:
            blockers.append("OCI reports insufficient A1 OCPU service availability")
        if a1_memory.available < A1_MEMORY_GBS:
            blockers.append("OCI reports insufficient A1 RAM service availability")
    else:
        assert e2_count is not None
        if e2_count.used + 1 > FREE_E2_MICRO_LIMIT:
            blockers.append("the launch would exceed the two Always Free E2 Micro cap")
        if e2_count.available < 1:
            blockers.append("OCI reports insufficient E2 Micro service availability")

    return AuditReport(
        profile=profile.key,
        region=REGION,
        availability_domain=AVAILABILITY_DOMAIN,
        target_instances=tuple(instance.identifier for instance in targets),
        target_states=tuple(instance.lifecycle_state for instance in targets),
        a1_ocpus_used=a1_cores.used if a1_cores is not None else None,
        a1_memory_gb_used=a1_memory.used if a1_memory is not None else None,
        e2_micro_used=e2_count.used if e2_count is not None else None,
        free_storage_gb_used=storage.used,
        image_name=image.display_name,
        target_shape_available=profile.shape in available_shapes,
        target_subnet_available=subnet_ok,
        launch_safe=not blockers,
        blockers=tuple(blockers),
    )


def _profile_for_instance(instance: InstanceDetails) -> Optional[LaunchProfile]:
    for profile in PROFILES.values():
        if instance.shape == profile.shape and instance.image_id == profile.image_ocid:
            return profile
    return None


def _instance_blockers(
    instance: InstanceDetails,
    profile: LaunchProfile = A1_PROFILE,
) -> list[str]:
    blockers = []
    if instance.display_name != DISPLAY_NAME:
        blockers.append("display name mismatch")
    if instance.shape != profile.shape:
        blockers.append("shape mismatch")
    if profile.ocpus is not None and instance.ocpus != profile.ocpus:
        blockers.append("OCPU mismatch")
    if profile.memory_gbs is not None and instance.memory_in_gbs != profile.memory_gbs:
        blockers.append("RAM mismatch")
    if instance.image_id != profile.image_ocid:
        blockers.append("image mismatch")
    if instance.availability_domain != AVAILABILITY_DOMAIN:
        blockers.append("availability domain mismatch")
    return blockers


def _ready_blockers(
    instance: InstanceDetails,
    vnic: VnicRecord,
    profile: LaunchProfile = A1_PROFILE,
) -> list[str]:
    blockers = _instance_blockers(instance, profile)
    if instance.lifecycle_state != "RUNNING":
        blockers.append("instance is not RUNNING")
    if vnic.subnet_id != SUBNET_OCID:
        blockers.append("subnet mismatch")
    if not vnic.public_ip:
        blockers.append("public IPv4 is missing")
    return blockers

class OciGateway:
    """Small OCI adapter with SDK automatic retries disabled."""

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
        self._network = oci.core.VirtualNetworkClient(
            config, signer=signer, retry_strategy=no_retry
        )
        self._limits = oci.limits.LimitsClient(
            config, signer=signer, retry_strategy=no_retry
        )

    def list_instances(self) -> list[InstanceRecord]:
        response = self._oci.pagination.list_call_get_all_results(
            self._compute.list_instances,
            COMPARTMENT_OCID,
            retry_strategy=self._oci.retry.NoneRetryStrategy(),
        )
        return [
            InstanceRecord(
                item.id,
                item.display_name or "",
                item.lifecycle_state,
                item.freeform_tags or {},
            )
            for item in response.data
        ]

    def get_instance(self, identifier: str) -> InstanceDetails:
        item = self._compute.get_instance(
            identifier,
            retry_strategy=self._oci.retry.NoneRetryStrategy(),
        ).data
        shape_config = item.shape_config
        ocpus = (
            float(shape_config.ocpus)
            if shape_config is not None and shape_config.ocpus is not None
            else None
        )
        memory_in_gbs = (
            float(shape_config.memory_in_gbs)
            if shape_config is not None and shape_config.memory_in_gbs is not None
            else None
        )
        return InstanceDetails(
            item.id,
            item.display_name or "",
            item.lifecycle_state,
            item.shape,
            ocpus,
            memory_in_gbs,
            item.image_id,
            item.availability_domain,
            item.freeform_tags or {},
        )

    def get_image(self, profile: LaunchProfile = A1_PROFILE) -> ImageRecord:
        item = self._compute.get_image(
            profile.image_ocid,
            retry_strategy=self._oci.retry.NoneRetryStrategy(),
        ).data
        return ImageRecord(
            item.id,
            item.lifecycle_state,
            item.operating_system,
            item.display_name,
        )

    def get_subnet(self) -> SubnetRecord:
        item = self._network.get_subnet(
            SUBNET_OCID,
            retry_strategy=self._oci.retry.NoneRetryStrategy(),
        ).data
        return SubnetRecord(
            item.id,
            item.lifecycle_state,
            item.availability_domain,
            bool(item.prohibit_public_ip_on_vnic),
        )

    def list_shapes(
        self, profile: LaunchProfile = A1_PROFILE
    ) -> list[str]:
        response = self._oci.pagination.list_call_get_all_results(
            self._compute.list_shapes,
            COMPARTMENT_OCID,
            availability_domain=AVAILABILITY_DOMAIN,
            image_id=profile.image_ocid,
            retry_strategy=self._oci.retry.NoneRetryStrategy(),
        )
        return [item.shape for item in response.data]

    def get_resource_availability(
        self, profile: LaunchProfile = A1_PROFILE
    ) -> dict[str, ResourceAvailability]:
        names: dict[str, tuple[str, str, Optional[str]]] = {
            "free_storage_gb": (
                "block-storage",
                "total-free-storage-gb-regional",
                None,
            ),
        }
        if profile.key == "a1":
            names.update({
                "a1_ocpus": (
                    "compute",
                    "standard-a1-core-regional-count",
                    None,
                ),
                "a1_memory_gb": (
                    "compute",
                    "standard-a1-memory-regional-count",
                    None,
                ),
            })
        elif profile.key == "e2":
            names["e2_micro_count"] = (
                "compute",
                "vm-standard-e2-1-micro-count",
                AVAILABILITY_DOMAIN,
            )
        else:
            raise SafetyError(f"unsupported launch profile {profile.key}")

        result = {}
        for key, (service, limit_name, availability_domain) in names.items():
            kwargs = {"retry_strategy": self._oci.retry.NoneRetryStrategy()}
            if availability_domain is not None:
                kwargs["availability_domain"] = availability_domain
            item = self._limits.get_resource_availability(
                service,
                limit_name,
                COMPARTMENT_OCID,
                **kwargs,
            ).data
            if item.used is None or item.available is None:
                raise SafetyError(f"OCI omitted availability data for {key}")
            result[key] = ResourceAvailability(
                float(item.used), float(item.available)
            )
        return result

    def get_primary_vnic(self, instance_id: str) -> VnicRecord:
        response = self._oci.pagination.list_call_get_all_results(
            self._compute.list_vnic_attachments,
            COMPARTMENT_OCID,
            instance_id=instance_id,
            retry_strategy=self._oci.retry.NoneRetryStrategy(),
        )
        attachments = [
            item
            for item in response.data
            if item.lifecycle_state == "ATTACHED" and item.nic_index == 0
        ]
        if len(attachments) != 1:
            raise SafetyError("expected exactly one attached primary VNIC")
        item = self._network.get_vnic(
            attachments[0].vnic_id,
            retry_strategy=self._oci.retry.NoneRetryStrategy(),
        ).data
        return VnicRecord(item.id, item.subnet_id, item.public_ip)

    def launch_instance(
        self,
        retry_token: str,
        profile: LaunchProfile = A1_PROFILE,
    ) -> str:
        """Submit exactly one SDK request with all automatic retries disabled."""

        oci = self._oci
        manifest = launch_manifest(profile)
        vnic = oci.core.models.CreateVnicDetails(
            **manifest.pop("create_vnic_details")
        )
        shape_config_values = manifest.pop("shape_config", None)
        shape_config = (
            oci.core.models.LaunchInstanceShapeConfigDetails(
                **shape_config_values
            )
            if shape_config_values is not None
            else None
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
        details_values = {
            "create_vnic_details": vnic,
            "source_details": source,
            "instance_options": options,
            "availability_config": availability,
            "agent_config": agent,
            **manifest,
        }
        if shape_config is not None:
            details_values["shape_config"] = shape_config
        details = oci.core.models.LaunchInstanceDetails(**details_values)
        response = self._compute.launch_instance(
            details,
            opc_retry_token=retry_token,
            retry_strategy=oci.retry.NoneRetryStrategy(),
        )
        return response.data.id


def audit(
    gateway: Any,
    profile: LaunchProfile = A1_PROFILE,
) -> AuditReport:
    return evaluate_audit(
        gateway.list_instances(),
        gateway.get_image(profile),
        gateway.get_subnet(),
        gateway.list_shapes(profile),
        gateway.get_resource_availability(profile),
        profile,
    )


def _select_profile(env: Mapping[str, str]) -> LaunchProfile:
    run_number = env.get("GITHUB_RUN_NUMBER")
    if not run_number:
        return A1_PROFILE
    try:
        value = int(run_number)
    except ValueError as exc:
        raise SafetyError("invalid GITHUB_RUN_NUMBER") from exc
    if value <= 0:
        raise SafetyError("invalid GITHUB_RUN_NUMBER")
    return E2_PROFILE if value % 2 == 0 else A1_PROFILE


def _resolve_profile(name: str, env: Mapping[str, str]) -> LaunchProfile:
    if name == "auto":
        return _select_profile(env)
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise SafetyError(f"unsupported launch profile {name}") from exc


def _retry_token(
    env: Mapping[str, str],
    profile: LaunchProfile = A1_PROFILE,
) -> str:
    # GITHUB_RUN_ID stays stable when a workflow run is re-run, making that
    # re-run reuse the original idempotency token. New runs get new IDs.
    run_id = env.get("GITHUB_RUN_ID", "local")
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"guardamar-capacity:{run_id}:{profile.key}",
        )
    )


def _error_kind(exc: BaseException) -> str:
    message = str(getattr(exc, "message", exc)).lower()
    status = getattr(exc, "status", None)
    code = str(getattr(exc, "code", "")).lower()
    if "out of host capacity" in message or "outofhostcapacity" in code:
        return "capacity"
    if status == 429 or code == "toomanyrequests":
        return "rate_limit"
    if isinstance(status, int) and 400 <= status < 500:
        return "fatal"
    if isinstance(exc, (SafetyError, KeyError, TypeError, ValueError)):
        return "fatal"
    if type(exc).__name__ == "InvalidConfig":
        return "fatal"
    return "ambiguous"


def _safe_error(exc: BaseException) -> str:
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    parts = [type(exc).__name__]
    if status is not None:
        parts.append(f"status={status}")
    if code:
        parts.append(f"code={code}")
    return " ".join(parts)


def _target_records(gateway: Any) -> list[InstanceRecord]:
    return [item for item in gateway.list_instances() if _is_target(item)]


def _observe_instance(
    gateway: Any,
    identifier: str,
    sleep: Callable[[float], None],
    profile: Optional[LaunchProfile] = None,
) -> CapacityResult:
    last_state = "UNKNOWN"
    expected_profile = profile
    for delay in POLL_DELAYS_SECONDS:
        if delay:
            sleep(delay)
        instance = gateway.get_instance(identifier)
        last_state = instance.lifecycle_state
        if expected_profile is None:
            expected_profile = _profile_for_instance(instance)
            if expected_profile is None:
                return CapacityResult(
                    "BLOCKED",
                    "existing target does not match an allowed launch profile",
                    disable_schedule=True,
                    instance_id=identifier,
                )
        blockers = _instance_blockers(instance, expected_profile)
        if blockers:
            return CapacityResult(
                "BLOCKED",
                "existing target configuration mismatch: " + ", ".join(blockers),
                disable_schedule=True,
                instance_id=identifier,
                profile=expected_profile.key,
            )
        if instance.lifecycle_state == "RUNNING":
            try:
                vnic = gateway.get_primary_vnic(identifier)
            except Exception as exc:
                if _error_kind(exc) == "fatal":
                    return CapacityResult(
                        "BLOCKED",
                        "READY verification failed: " + _safe_error(exc),
                        disable_schedule=True,
                        instance_id=identifier,
                        profile=expected_profile.key,
                    )
                continue
            blockers = _ready_blockers(instance, vnic, expected_profile)
            permanent_blockers = [
                blocker for blocker in blockers if blocker != "public IPv4 is missing"
            ]
            if permanent_blockers:
                return CapacityResult(
                    "BLOCKED",
                    "READY verification mismatch: "
                    + ", ".join(permanent_blockers),
                    disable_schedule=True,
                    instance_id=identifier,
                    public_ip=vnic.public_ip,
                    profile=expected_profile.key,
                )
            if vnic.public_ip:
                return CapacityResult(
                    "READY",
                    "exact target instance is RUNNING with a public IPv4",
                    disable_schedule=True,
                    instance_id=identifier,
                    public_ip=vnic.public_ip,
                    profile=expected_profile.key,
                )
        if instance.lifecycle_state in {
            "STOPPED",
            "STOPPING",
            "TERMINATING",
            "TERMINATED",
        }:
            return CapacityResult(
                "BLOCKED",
                f"target entered unexpected state {instance.lifecycle_state}",
                disable_schedule=True,
                instance_id=identifier,
                profile=expected_profile.key,
            )
    return CapacityResult(
        "PENDING",
        f"target remains in {last_state}; next run will verify it without launch",
        instance_id=identifier,
        profile=expected_profile.key if expected_profile is not None else None,
    )


def _discover_after_ambiguous(
    gateway: Any,
    sleep: Callable[[float], None],
    profile: LaunchProfile,
) -> Optional[CapacityResult]:
    for delay in AMBIGUOUS_DISCOVERY_DELAYS_SECONDS:
        if delay:
            sleep(delay)
        try:
            targets = _target_records(gateway)
        except Exception as exc:
            return CapacityResult(
                "AMBIGUOUS",
                "instance discovery failed after ambiguous launch response: "
                + _safe_error(exc),
                disable_schedule=True,
                profile=profile.key,
            )
        if len(targets) > 1:
            return CapacityResult(
                "BLOCKED",
                "multiple target instances appeared after an ambiguous response",
                disable_schedule=True,
                profile=profile.key,
            )
        if targets:
            return _observe_instance(
                gateway, targets[0].identifier, sleep, profile
            )
    return None


def run_launch(
    gateway: Any,
    env: Mapping[str, str],
    sleep: Callable[[float], None] = time.sleep,
    profile: Optional[LaunchProfile] = None,
) -> CapacityResult:
    """Run at most one logical and one physical LaunchInstance request."""

    selected_profile = profile or _select_profile(env)

    # An already accepted target is authoritative across both profiles.
    # Verify it before candidate-specific image/limit reads so a late queued
    # run cannot depend on permissions for the other profile.
    targets = _target_records(gateway)
    if len(targets) > 1:
        return CapacityResult(
            "BLOCKED",
            "multiple non-terminated target instances exist",
            disable_schedule=True,
            profile=selected_profile.key,
        )
    if targets:
        return _observe_instance(
            gateway, targets[0].identifier, sleep
        )

    report = audit(gateway, selected_profile)
    if not report.launch_safe:
        return CapacityResult(
            "BLOCKED",
            "launch preflight failed: " + "; ".join(report.blockers),
            disable_schedule=True,
            report=report,
            profile=selected_profile.key,
        )

    final_report = audit(gateway, selected_profile)
    if not final_report.launch_safe:
        return CapacityResult(
            "BLOCKED",
            "final launch preflight failed: " + "; ".join(final_report.blockers),
            disable_schedule=True,
            report=final_report,
            profile=selected_profile.key,
        )

    try:
        identifier = gateway.launch_instance(
            _retry_token(env, selected_profile),
            selected_profile,
        )
    except Exception as exc:
        kind = _error_kind(exc)
        if kind == "capacity":
            return CapacityResult(
                "CAPACITY_MISS",
                f"OCI reported Out of host capacity for {selected_profile.key}; "
                "no retry in this run",
                report=final_report,
                profile=selected_profile.key,
            )
        if kind == "rate_limit":
            return CapacityResult(
                "RATE_LIMITED",
                "OCI rate-limited the single request; no retry in this run",
                report=final_report,
                profile=selected_profile.key,
            )
        if kind == "fatal":
            return CapacityResult(
                "BLOCKED",
                "LaunchInstance rejected: " + _safe_error(exc),
                disable_schedule=True,
                report=final_report,
                profile=selected_profile.key,
            )
        discovered = _discover_after_ambiguous(
            gateway, sleep, selected_profile
        )
        if discovered is not None:
            return CapacityResult(
                **{**asdict(discovered), "report": final_report}
            )
        return CapacityResult(
            "AMBIGUOUS",
            "launch response was ambiguous and no target became visible; "
            "manual review required",
            disable_schedule=True,
            report=final_report,
            profile=selected_profile.key,
        )

    result = _observe_instance(
        gateway, identifier, sleep, selected_profile
    )
    return CapacityResult(**{**asdict(result), "report": final_report})


def _emit_result(result: CapacityResult, env: Mapping[str, str]) -> None:
    print(json.dumps(asdict(result), sort_keys=True))
    output_path = env.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"outcome={result.outcome}\n")
            output.write(
                "disable_schedule="
                + ("true" if result.disable_schedule else "false")
                + "\n"
            )
            if result.instance_id:
                output.write(f"instance_id={result.instance_id}\n")
            if result.public_ip:
                output.write(f"public_ip={result.public_ip}\n")
            if result.profile:
                output.write(f"profile={result.profile}\n")

    summary_path = env.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        short_id = result.instance_id[-12:] if result.instance_id else "—"
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write("## Guardamar capacity result\n\n")
            summary.write(f"- Outcome: **{result.outcome}**\n")
            summary.write(f"- Detail: {result.message}\n")
            if result.profile:
                summary.write(f"- Profile: `{result.profile}`\n")
            if result.outcome == "READY":
                summary.write(f"- Public IPv4: `{result.public_ip}`\n")
                summary.write(
                    f"- Region / AD: `{REGION}` / `{AVAILABILITY_DOMAIN}`\n"
                )
                profile = PROFILES.get(result.profile or "")
                if profile is not None:
                    if profile.ocpus is not None and profile.memory_gbs is not None:
                        summary.write(
                            f"- Shape: `{profile.shape}` "
                            f"({profile.ocpus:g} OCPU / {profile.memory_gbs:g} GB)\n"
                        )
                    else:
                        summary.write(f"- Shape: `{profile.shape}`\n")
                summary.write(f"- Instance OCID suffix: `…{short_id}`\n")
                summary.write(
                    "- Capacity search: complete; schedule disable requested\n"
                )


def main(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    gateway_factory: Any = OciGateway,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit_parser = subparsers.add_parser(
        "audit", help="perform read-only safety checks"
    )
    audit_parser.add_argument(
        "--profile",
        choices=tuple(PROFILES),
        default="a1",
    )
    launch_parser = subparsers.add_parser(
        "launch", help="run one bounded attempt"
    )
    launch_parser.add_argument("--allow-launch", action="store_true")
    launch_parser.add_argument(
        "--profile",
        choices=("auto", *tuple(PROFILES)),
        default="auto",
    )
    args = parser.parse_args(argv)
    current_env = os.environ if env is None else env

    if args.command == "launch":
        if not LAUNCH_BUILD_ENABLED:
            result = CapacityResult("BLOCKED", "launch is build-disabled", True)
            _emit_result(result, current_env)
            return result.exit_code
        if not args.allow_launch:
            result = CapacityResult("BLOCKED", "explicit CLI gate is missing", True)
            _emit_result(result, current_env)
            return result.exit_code
        if current_env.get("GUARDAMAR_LAUNCH_SWITCH") != LAUNCH_SWITCH_VALUE:
            result = CapacityResult("BLOCKED", "owner launch switch is missing", True)
            _emit_result(result, current_env)
            return result.exit_code

    try:
        selected_profile = _resolve_profile(args.profile, current_env)
        gateway = gateway_factory(current_env)
        if args.command == "audit":
            report = audit(gateway, selected_profile)
            result = CapacityResult(
                "AUDIT",
                "read-only audit completed",
                report=report,
                profile=selected_profile.key,
            )
        else:
            result = run_launch(
                gateway,
                current_env,
                sleep,
                selected_profile,
            )
    except Exception as exc:
        kind = _error_kind(exc)
        result = CapacityResult(
            "BLOCKED" if kind == "fatal" else "AUDIT_UNAVAILABLE",
            "preflight unavailable: " + _safe_error(exc),
            disable_schedule=kind == "fatal",
        )
    _emit_result(result, current_env)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
