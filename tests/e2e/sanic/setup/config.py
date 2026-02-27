from pydantic import Field
from pydantic_settings import BaseSettings


class SanicE2ESettings(BaseSettings):
    host: str = Field(default="localhost", alias="SANIC_E2E_HOST")
    port: int = Field(default=8240, alias="SANIC_E2E_PORT")
