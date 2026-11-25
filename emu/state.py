"""Shared runtime state for the console."""
import os

HOME = os.path.expanduser("~")
EMU_DIR = os.path.join(HOME, ".aws", "emulator")
IMAGE = "aws-emulator"
RPM_BASE = "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest"


class State:
    port = 9297            # emulator HTTPS port
    proxy_port = 9390      # logging proxy (plain HTTP) port
    auth = True
    telemetry = False
    idle_timeout = 0       # seconds, 0 = none
    memory = "2g"
    mode = "sdk"           # sdk | proxy | both  (capture mode)

    @property
    def container(self):
        return f"aws-emulator-{self.port}"


STATE = State()
