"""
Azure Blob Storage service — two storage modes:

AUTOMATIC (existing flow):
  kalpataru/automatic/{YYYY-MM-DD}/{direction}/{N}/filename

MANUAL (new flow):
  kalpataru/manual/{YYYY-MM-DD}/{HH-MM-SS}/filename
"""
import logging
import uuid
from datetime import datetime
from typing import List, Tuple

from azure.storage.blob import BlobServiceClient
import config

logger = logging.getLogger(__name__)

# Singleton BlobServiceClient — created once at import time
_blob_service_client: BlobServiceClient = BlobServiceClient.from_connection_string(
    config.AZURE_STORAGE_CONNECTION_STRING
)
_container_client = _blob_service_client.get_container_client(
    config.AZURE_BLOB_CONTAINER_NAME
)


def _ensure_container_exists():
    """Create the container if it doesn't already exist (public blob access)."""
    try:
        _container_client.create_container(public_access="blob")
        logger.info(f"Container '{config.AZURE_BLOB_CONTAINER_NAME}' created with public access.")
    except Exception as e:
        # If public access is not permitted by Azure Storage policy, create private container
        if "PublicAccessNotPermitted" in str(e):
            try:
                _container_client.create_container()
                logger.warning(
                    f"⚠️ Container '{config.AZURE_BLOB_CONTAINER_NAME}' created as PRIVATE because "
                    "public access is disabled on the storage account. "
                    "To view images on the web dashboard, go to the Storage Account 'Configuration' "
                    "page in the Azure Portal and set 'Allow Blob public access' to Enabled."
                )
            except Exception:
                pass  # Container already exists
        else:
            pass  # Container already exists or other error handled silently



_ensure_container_exists()


def _public_url(blob_path: str) -> str:
    """Return the public HTTPS URL for a blob path."""
    account_url = _blob_service_client.url.rstrip("/")
    container = config.AZURE_BLOB_CONTAINER_NAME
    return f"{account_url}/{container}/{blob_path}"


def _upload_blob(blob_path: str, file_bytes: bytes) -> str:
    """Upload bytes to blob_path and return the public URL."""
    blob_client = _container_client.get_blob_client(blob_path)
    blob_client.upload_blob(file_bytes, overwrite=True)
    url = _public_url(blob_path)
    logger.info(f"Uploaded blob: {blob_path}")
    return url


class StorageService:
    """
    Azure Blob Storage service with two modes:

    AUTOMATIC mode — same day/direction/N hierarchy, under automatic/ prefix:
        kalpataru/automatic/2026-07-15/inward/1/challan_xxx.jpg

    MANUAL mode — date/time folder, under manual/ prefix:
        kalpataru/manual/2026-07-15/14-25-33/invoice.jpg
    """

    # ─────────────────────────────────────────────────────────────────────────
    # AUTOMATIC mode
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _new_auto_subfolder_name() -> str:
        """
        Collision-free subfolder name — was previously "list existing blobs,
        take max + 1", which raced under concurrent uploads: two requests
        listing at the same moment could compute the same next number and
        land in the same subfolder, overwriting each other's images.
        Time + a random suffix needs no coordination and can't collide.
        """
        return f"{datetime.now().strftime('%H-%M-%S')}-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _get_auto_direction_prefix(direction: str) -> str:
        """Return blob prefix for automatic/{date}/{direction}/"""
        today = datetime.now().strftime("%Y-%m-%d")
        direction = direction.strip().lower()
        if direction not in ("inward", "outward", "returnable"):
            direction = "inward"
        return f"automatic/{today}/{direction}/"

    @classmethod
    def save_files(
        cls,
        files: List[Tuple[str, bytes]],
        direction: str,
    ) -> Tuple[str, List[str]]:
        """
        Upload automatic-mode files to:
            automatic/{date}/{direction}/{HH-MM-SS}-{random}/filename

        Returns:
            (blob_prefix, list_of_public_urls)
        """
        direction_prefix = cls._get_auto_direction_prefix(direction)
        subfolder_prefix = f"{direction_prefix}{cls._new_auto_subfolder_name()}/"

        saved_urls: List[str] = []
        for original_filename, file_bytes in files:
            if not file_bytes:
                continue
            blob_path = f"{subfolder_prefix}{original_filename}"
            url = _upload_blob(blob_path, file_bytes)
            saved_urls.append(url)

        return subfolder_prefix, saved_urls

    # ─────────────────────────────────────────────────────────────────────────
    # MANUAL mode
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def save_manual_file(
        cls,
        filename: str,
        file_bytes: bytes,
    ) -> Tuple[str, str]:
        """
        Upload a manual-entry invoice image to:
            manual/{YYYY-MM-DD}/{HH-MM-SS}/filename

        Returns:
            (blob_prefix, public_url)
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S")
        blob_prefix = f"manual/{date_str}/{time_str}/"
        blob_path = f"{blob_prefix}{filename}"

        url = _upload_blob(blob_path, file_bytes)
        return blob_prefix, url

    # ─────────────────────────────────────────────────────────────────────────
    # Delete helpers
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def delete_files_by_prefix(cls, folder_prefix: str) -> List[str]:
        """Delete all blobs under a given prefix. Returns list of deleted blob names."""
        if not folder_prefix:
            return []
        deleted = []
        blobs = list(_container_client.list_blobs(name_starts_with=folder_prefix))
        for blob in blobs:
            _container_client.delete_blob(blob.name)
            deleted.append(blob.name)
            logger.info(f"Deleted blob: {blob.name}")
        return deleted

    @classmethod
    def delete_blob_by_url(cls, url: str) -> bool:
        """Delete a single blob given its public URL."""
        if not url:
            return False
        try:
            container = config.AZURE_BLOB_CONTAINER_NAME
            marker = f"/{container}/"
            idx = url.find(marker)
            if idx == -1:
                return False
            blob_path = url[idx + len(marker):]
            _container_client.delete_blob(blob_path)
            logger.info(f"Deleted blob by URL: {blob_path}")
            return True
        except Exception as e:
            logger.warning(f"Could not delete blob from URL {url}: {e}")
            return False

    @staticmethod
    def sign_url(url: str | None) -> str | None:
        """Dynamically append a temporary SAS token to a private Azure Blob URL."""
        if not url:
            return url
        if "blob.core.windows.net" not in url:
            return url
        if "?" in url:
            return url

        try:
            parts = url.split("blob.core.windows.net/", 1)
            if len(parts) < 2:
                return url
            path_part = parts[1]
            sub_parts = path_part.split("/", 1)
            if len(sub_parts) < 2:
                return url
            container = sub_parts[0]
            blob_path = sub_parts[1]

            from azure.storage.blob import generate_blob_sas, BlobSasPermissions
            from datetime import datetime, timedelta, timezone

            credential = _blob_service_client.credential
            sas_token = generate_blob_sas(
                account_name=credential.account_name,
                container_name=container,
                blob_name=blob_path,
                account_key=credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(days=7)
            )
            return f"{url}?{sas_token}"
        except Exception as e:
            logger.warning(f"Failed to sign URL '{url}': {e}")
            return url

