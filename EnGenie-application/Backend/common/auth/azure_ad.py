"""
Azure AD Email Verification Module
Verifies if an email exists in the organization's Azure AD
"""
import logging
import os

import requests
from msal import ConfidentialClientApplication
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Azure AD Configuration
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"


# ============================================================
# PERFORMANCE: Requests Session with Retry Logic
# ============================================================
def _get_requests_session() -> requests.Session:
    """
    Create a requests session with automatic retry logic for transient failures.

    Retries on:
    - 500, 502, 503, 504 (server errors)
    - 429 (rate limiting)

    Returns:
        requests.Session: Configured session with retry logic
    """
    session = requests.Session()

    # Configure retry strategy
    retry_strategy = Retry(
        total=3,  # Maximum 3 retries
        backoff_factor=1,  # Wait 1s, 2s, 4s between retries
        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these HTTP codes
        allowed_methods=["GET", "POST"]  # Only retry safe methods
    )

    # Mount adapter with retry strategy
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


# ============================================================
# SECURITY: OData Injection Prevention
# ============================================================
import re


def _validate_email_format(email: str) -> bool:
    """
    Strict email validation to prevent OData injection attacks.

    Args:
        email: Email address to validate

    Returns:
        bool: True if email format is valid, False otherwise
    """
    if not email or len(email) > 254:  # RFC 5321 max email length
        return False

    # Strict regex: only allow valid email characters
    # Prevents injection of OData operators like: ' or 1 eq 1 or '
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_regex, email))


def _escape_odata_string(value: str) -> str:
    """
    Escape single quotes for OData filter strings (defense in depth).

    In OData, single quotes in string literals must be escaped by doubling them.
    Example: "O'Brien" becomes "O''Brien"

    Args:
        value: String value to escape

    Returns:
        str: Escaped string safe for OData filter
    """
    return value.replace("'", "''")


def _mask_email(email: str) -> str:
    """
    Mask email address for logging (PII protection).

    Example: john.doe@company.com -> j***e@company.com

    Args:
        email: Email address to mask

    Returns:
        str: Masked email address
    """
    if not email or '@' not in email:
        return '***'

    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = '*' * len(local)
    else:
        masked_local = local[0] + '*' * (len(local) - 2) + local[-1]

    return f"{masked_local}@{domain}"


# ============================================================
# MULTI-TENANT: Dynamic Domain Detection from Azure AD
# ============================================================

# Cache for verified domains (refresh every 24 hours)
_verified_domains_cache = {
    "domains": [],
    "last_updated": None
}


def get_verified_domains_from_tenant() -> list:
    """
    Get list of verified email domains from Azure AD tenant.

    This allows multi-tenant support - each Azure AD tenant has its own verified domains.
    Results are cached for 24 hours to minimize API calls.

    Returns:
        list: List of verified domain strings (e.g., ["ensarsolutions.com", "ensar.io"])

    Example:
        >>> domains = get_verified_domains_from_tenant()
        >>> print(domains)
        ['ensarsolutions.com', 'ensar.io']
    """
    from datetime import datetime, timedelta

    try:
        # Check cache (24-hour TTL)
        if _verified_domains_cache["last_updated"]:
            cache_age = datetime.now() - _verified_domains_cache["last_updated"]
            if cache_age < timedelta(hours=24) and _verified_domains_cache["domains"]:
                logger.info(f"Using cached verified domains: {_verified_domains_cache['domains']}")
                return _verified_domains_cache["domains"]

        # Get access token
        token = get_access_token()

        # Query organization details from Microsoft Graph
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        url = f"{GRAPH_API_ENDPOINT}/organization"

        session = _get_requests_session()
        response = session.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            organizations = data.get("value", [])

            if organizations:
                org = organizations[0]  # Get primary organization
                verified_domains = org.get("verifiedDomains", [])

                # Extract domain names (filter only verified, non-default domains)
                domain_list = [
                    domain["name"]
                    for domain in verified_domains
                    if domain.get("isVerified", False)
                ]

                # Update cache
                _verified_domains_cache["domains"] = domain_list
                _verified_domains_cache["last_updated"] = datetime.now()

                logger.info(f"✅ Fetched verified domains from Azure AD: {domain_list}")
                return domain_list
            else:
                logger.warning("No organization data found in Azure AD")
                return []
        else:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            logger.error(f"Failed to get organization domains (status {response.status_code}): {error_msg}")
            return []

    except Exception as e:
        logger.error(f"Error fetching verified domains: {str(e)}")
        # Return cached domains if available (graceful degradation)
        if _verified_domains_cache["domains"]:
            logger.warning(f"Using stale cache due to error: {_verified_domains_cache['domains']}")
            return _verified_domains_cache["domains"]
        return []


def is_email_domain_allowed(email: str) -> dict:
    """
    Check if email domain is allowed based on Azure AD tenant's verified domains.

    Dynamically adapts to your organization's domains - no hardcoding needed!

    Args:
        email: Email address to check

    Returns:
        dict: {
            "allowed": bool,
            "email": str,
            "domain": str,
            "verified_domains": list,
            "error": str or None
        }
    """
    try:
        if not email or '@' not in email:
            return {
                "allowed": False,
                "email": email,
                "domain": None,
                "verified_domains": [],
                "error": "Invalid email format"
            }

        email_domain = email.split('@')[1].lower()
        verified_domains = get_verified_domains_from_tenant()

        if not verified_domains:
            # Fallback: If Azure AD query fails, use environment variable
            fallback_domain = os.getenv("ALLOWED_EMAIL_DOMAIN", "ensarsolutions.com")
            logger.warning(f"No verified domains from Azure AD, using fallback: {fallback_domain}")
            verified_domains = [fallback_domain]

        # Check if email domain matches any verified domain
        is_allowed = email_domain in [d.lower() for d in verified_domains]

        if is_allowed:
            logger.info(f"✅ Email domain allowed: {email_domain} (matches verified domains)")
        else:
            logger.warning(f"❌ Email domain rejected: {email_domain} (not in {verified_domains})")

        return {
            "allowed": is_allowed,
            "email": email,
            "domain": email_domain,
            "verified_domains": verified_domains,
            "error": None if is_allowed else f"Only {', '.join(verified_domains)} emails are allowed"
        }

    except Exception as e:
        logger.error(f"Error checking email domain: {str(e)}")
        return {
            "allowed": False,
            "email": email,
            "domain": None,
            "verified_domains": [],
            "error": f"System error: {str(e)}"
        }


def get_organization_name_from_tenant() -> str:
    """
    Get organization display name from Azure AD tenant.

    Returns:
        str: Organization name (e.g., "Ensar Solutions")
    """
    try:
        # Get access token
        token = get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        url = f"{GRAPH_API_ENDPOINT}/organization"

        session = _get_requests_session()
        response = session.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            organizations = data.get("value", [])

            if organizations:
                org = organizations[0]
                org_name = org.get("displayName", "")
                logger.info(f"✅ Organization name from Azure AD: {org_name}")
                return org_name
            else:
                logger.warning("No organization data found")
                return os.getenv("DEFAULT_COMPANY_NAME", "Organization")
        else:
            logger.error(f"Failed to get organization name (status {response.status_code})")
            return os.getenv("DEFAULT_COMPANY_NAME", "Organization")

    except Exception as e:
        logger.error(f"Error fetching organization name: {str(e)}")
        # Fallback to environment variable
        return os.getenv("DEFAULT_COMPANY_NAME", "Organization")


def get_access_token() -> str:
    """
    Get access token using service principal (app-only authentication)

    Returns:
        str: Access token for Microsoft Graph API

    Raises:
        Exception: If authentication fails
    """
    try:
        app = ConfidentialClientApplication(
            CLIENT_ID,
            authority=AUTHORITY,
            client_credential=CLIENT_SECRET,
        )

        # Request token for Microsoft Graph
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

        if "access_token" in result:
            logger.info("Successfully acquired access token")
            return result["access_token"]
        else:
            error = result.get("error_description", result.get("error", "Unknown error"))
            logger.error(f"Failed to get access token: {error}")
            raise Exception(f"Authentication failed: {error}")

    except Exception as e:
        logger.error(f"Error getting access token: {str(e)}")
        raise


def check_email_exists_in_organization(email: str) -> dict:
    """
    Check if email exists in Azure AD organization

    Args:
        email: Email address to verify

    Returns:
        dict: {
            "exists": bool,
            "user_data": dict or None,
            "error": str or None
        }
    """
    try:
        # SECURITY LAYER 1: Validate email format (prevents OData injection)
        if not _validate_email_format(email):
            logger.warning(f"[SECURITY] Invalid email format rejected: {_mask_email(email)}")
            return {
                "exists": False,
                "user_data": None,
                "error": "Invalid email format"
            }

        logger.info(f"Checking if email exists in Azure AD: {_mask_email(email)}")

        # Get access token
        token = get_access_token()

        # Query Microsoft Graph API to find user by email
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # SECURITY LAYER 2: Escape single quotes for OData (defense in depth)
        safe_email = _escape_odata_string(email)

        # Search for user by userPrincipalName or mail
        url = f"{GRAPH_API_ENDPOINT}/users"
        params = {
            "$filter": f"userPrincipalName eq '{safe_email}' or mail eq '{safe_email}'",
            "$select": "id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation"
        }

        # SECURITY LAYER 3: Use session with retry logic + timeout
        session = _get_requests_session()
        response = session.get(url, headers=headers, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            users = data.get("value", [])

            if users:
                # User exists in organization
                user = users[0]
                logger.info(f"User found in Azure AD: {user.get('displayName')}")

                return {
                    "exists": True,
                    "user_data": {
                        "user_id": user.get("id"),
                        "email": user.get("mail") or user.get("userPrincipalName"),
                        "name": user.get("displayName"),
                        "job_title": user.get("jobTitle"),
                        "department": user.get("department"),
                        "office": user.get("officeLocation"),
                    },
                    "error": None
                }
            else:
                # User does not exist
                logger.warning(f"Email not found in Azure AD: {_mask_email(email)}")
                return {
                    "exists": False,
                    "user_data": None,
                    "error": "Email not found in organization directory"
                }
        else:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            logger.error(f"Graph API error (status {response.status_code}): {error_msg}")

            return {
                "exists": False,
                "user_data": None,
                "error": f"Verification failed: {error_msg}"
            }

    except Exception as e:
        logger.error(f"Error verifying email: {str(e)}")
        return {
            "exists": False,
            "user_data": None,
            "error": f"System error: {str(e)}"
        }


def get_user_by_email(email: str) -> dict | None:
    """
    Get detailed user information from Azure AD

    Args:
        email: User's email address

    Returns:
        dict: User information or None if not found
    """
    result = check_email_exists_in_organization(email)
    return result.get("user_data") if result.get("exists") else None


def validate_azure_ad_configuration() -> dict:
    """
    Validate that Azure AD is configured correctly

    Returns:
        dict: Validation result with status and details
    """
    try:
        if not TENANT_ID:
            return {"valid": False, "error": "AZURE_TENANT_ID not set"}

        if not CLIENT_ID:
            return {"valid": False, "error": "AZURE_CLIENT_ID not set"}

        if not CLIENT_SECRET:
            return {"valid": False, "error": "AZURE_CLIENT_SECRET not set"}

        # Try to get access token
        token = get_access_token()

        if token:
            return {
                "valid": True,
                "message": "Azure AD configuration is valid",
                "tenant_id": TENANT_ID,
                "client_id": CLIENT_ID,
            }
        else:
            return {"valid": False, "error": "Failed to acquire access token"}

    except Exception as e:
        return {"valid": False, "error": str(e)}
