"""Public compatibility surface for the canonical Knowledge Asset contracts.

The domain modules are the single model sources; this module preserves the
legacy import path used by the BFF, repository, generated-schema exporter, and
contract tests.
"""

from .contract_base import *
from .contract_data import *
from .contract_views import *
from .contract_commands import *
from .contract_runtime import *
from .connector_contracts import *
