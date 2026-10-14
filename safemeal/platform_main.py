"""仅食谱、身份与行为的后端入口：uvicorn safemeal.platform_main:app。"""

import os
from safemeal.bootstrap.composition.platform_application import (
    create_platform_application,
)
from safemeal.config.platform import PlatformSettings

application = create_platform_application(
    PlatformSettings(_env_file=os.environ.get("SAFEMEAL_ENV_FILE", ".env.platform"))  # type: ignore[call-arg]
)
app = application
