"""Domain provisioning services."""


def check_domain_availability(domain: str) -> bool:
    """Return True if the domain appears to be available."""
    # TODO: integrate with registrar API.
    _ = domain
    return False


def provision_domain(domain_mapping_id: int) -> None:
    """Provision DNS records and an SSL certificate for a domain mapping."""
    # TODO: call DNS provider API and ACME client.
    _ = domain_mapping_id
