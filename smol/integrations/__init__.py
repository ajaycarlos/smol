"""smol integrations — file-manager right-click scripts, autostart files."""

from smol.integrations.autostart import (
    AutostartIntegrator,
    AutostartResult,
    AutostartStatus,
    get_autostart_dir,
)
from smol.integrations.manager import (
    INTEGRATION_SIZES,
    DolphinIntegrator,
    IntegrationResult,
    IntegrationStatus,
    Integrator,
    NautilusIntegrator,
    NemoIntegrator,
    ThunarIntegrator,
    get_integrator,
)

__all__ = [
    "INTEGRATION_SIZES",
    "AutostartIntegrator",
    "AutostartResult",
    "AutostartStatus",
    "DolphinIntegrator",
    "IntegrationResult",
    "IntegrationStatus",
    "Integrator",
    "NautilusIntegrator",
    "NemoIntegrator",
    "ThunarIntegrator",
    "get_autostart_dir",
    "get_integrator",
]
