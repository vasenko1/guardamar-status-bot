# OCI E2 Micro capacity expansion review — 2026-10-03

## Question

Can the existing Madrid 3 Always Free capacity hunter add a second free
compute path without weakening the one-request and zero-cost safety model?

## Official findings

Oracle's Always Free documentation still lists up to two
`VM.Standard.E2.1.Micro` AMD VMs and A1 resources equivalent to 2 OCPUs /
12 GB RAM for Always Free tenancies. E2 Micro has 1 GB RAM and a small
burstable CPU allocation. In multi-AD regions Oracle restricts E2 Micro to one
availability domain. Always Free compute boot volumes share 200 GB of block
storage.

Sources:
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm

OCI service limits document
`standard-e2-micro-core-count` for the E2 Micro series, scoped to an
availability domain, with a default/free-compatible limit value of 2. This is
the service-limit name required by `LimitsClient.get_resource_availability`.
The similarly named `vm-standard-e2-1-micro-count` belongs to Compute quota
syntax and must not be substituted into the Limits API.

Sources:
- https://docs.oracle.com/en-us/iaas/Content/General/service-limits/default.htm
- https://docs.oracle.com/en-us/iaas/Content/Quotas/Concepts/resourcequotas_topic-Compute_Quotas.htm

Oracle publishes `Oracle-Linux-9.8-2026.08.14-0` for x86_64. Its official
`eu-madrid-3` image OCID is:

`ocid1.image.oc1.eu-madrid-3.aaaaaaaa2nsuyzwg7zpslg3xvd4xbt2jlrbsicyie7uipj2pbhrcryudgjga`

This matches the release date/version of the currently pinned A1 aarch64 image
while using the architecture required by E2.

Source:
- https://docs.oracle.com/en-us/iaas/images/oracle-linux-9x/oracle-linux-9-8-2026-08-14-0.htm

## Design review

Rejected: a second workflow or two `LaunchInstance` calls in one run. Both
increase race surface and request volume without improving safety.

Accepted: one shared target and one workflow. Automatic runs alternate A1/E2
by immutable GitHub run number and still submit no more than one create
request. Any existing target is discovered before profile-specific reads and
is then verified against either allowed exact profile.

E2 cannot reuse A1 `shape_config`; it is a fixed shape. It does reuse the
same subnet, public-IP requirement, 50 GB boot-volume cap, tags, SSH key,
retry suppression, two-preflight rule for an empty tenancy, ambiguous-response
discovery, and shared 200 GB storage gate.

## IAM delta

The current production identity can read only the A1 ARM image. Before E2 can
be activated, add exactly this second image-read statement:

`Allow group Default/guardamar-capacity-automation to read instance-images in tenancy where all {request.region = 'eu-madrid-3', target.image.id = 'ocid1.image.oc1.eu-madrid-3.aaaaaaaa2nsuyzwg7zpslg3xvd4xbt2jlrbsicyie7uipj2pbhrcryudgjga'}`

No broader Compute, image, network, storage, delete, update, power or IAM
permissions are needed.
