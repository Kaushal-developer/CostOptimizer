from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, model_validator


class CloudAccountCreate(BaseModel):
    provider: str = Field(pattern="^(aws|azure|gcp)$")
    account_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    is_remediation_enabled: bool = False

    # AWS - either role_arn OR access keys
    aws_role_arn: str | None = None
    aws_external_id: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str | None = "us-east-1"

    # Azure
    azure_subscription_id: str | None = None
    azure_tenant_id: str | None = None

    # GCP
    gcp_project_id: str | None = None
    gcp_credentials_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_provider_fields(self):
        if self.provider == "aws" and not self.aws_role_arn and not self.aws_access_key_id:
            raise ValueError("Either aws_role_arn or aws_access_key_id is required for AWS accounts")
        if self.provider == "aws" and self.aws_access_key_id and not self.aws_secret_access_key:
            raise ValueError("aws_secret_access_key is required when using access keys")
        if self.provider == "azure" and not (self.azure_subscription_id and self.azure_tenant_id):
            raise ValueError("azure_subscription_id and azure_tenant_id are required for Azure accounts")
        if self.provider == "gcp" and not self.gcp_project_id:
            raise ValueError("gcp_project_id is required for GCP accounts")
        return self


class CloudAccountUpdate(BaseModel):
    display_name: str | None = None
    is_remediation_enabled: bool | None = None
    aws_role_arn: str | None = None
    azure_subscription_id: str | None = None
    azure_tenant_id: str | None = None
    gcp_project_id: str | None = None
    gcp_credentials_json: dict[str, Any] | None = None


class CloudAccountResponse(BaseModel):
    id: int
    tenant_id: int
    provider: str
    account_id: str
    display_name: str
    status: str
    is_remediation_enabled: bool
    aws_role_arn: str | None = None
    aws_external_id: str | None = None
    aws_access_key_id: str | None = None
    aws_region: str | None = None
    azure_subscription_id: str | None = None
    azure_tenant_id: str | None = None
    gcp_project_id: str | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CloudAccountList(BaseModel):
    items: list[CloudAccountResponse]
    total: int
    page: int
    page_size: int
