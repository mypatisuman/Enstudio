"""
Health Monitoring Service
Monitors application health at configurable intervals and sends email notifications
when the system goes down or comes back up.

Supports dual monitoring:
- System health (/health) every 30 seconds
- Agent health (/health/agents) every 10 seconds
"""

import logging
import threading
import time

import requests

from common.services.email_service import send_downtime_notification, send_restoration_notification

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Background service that monitors application health and sends email notifications
    """

    def __init__(self, health_url: str, check_interval: int = 60):
        """
        Initialize health monitor

        Args:
            health_url: URL of the health check endpoint
            check_interval: Seconds between health checks (default: 60)
            fastapi_app: FastAPI application instance (required for database access)
        """
        self.health_url = health_url
        self.check_interval = check_interval
        self.fastapi_app = None  # Store FastAPI app for database context
        self.is_running = False
        self.monitor_thread: threading.Thread | None = None
        self.last_status = "healthy"  # Assume healthy on startup to prevent false alerts
        self.downtime_notified = False  # Track if downtime email was sent
        self.restoration_notified = False  # Track if restoration email was sent
        self.consecutive_failures = 0  # Track consecutive failures before alerting
        self.consecutive_timeouts = 0   # Track timeouts separately — busy ≠ down
        self.failure_threshold = 3      # Require 3 hard failures (connection errors) before alerting
        self.timeout_threshold = 3      # Require 3 consecutive timeouts before treating as down
        self.system_officially_down = False  # Track if system is officially down (after threshold failures)

    def start(self):
        """
        Start the health monitoring service in a background thread
        """
        if self.is_running:
            logger.warning("Health monitor is already running")
            return

        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info(f"Health monitor started - checking {self.health_url} every {self.check_interval} seconds")

    def stop(self):
        """
        Stop the health monitoring service
        """
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10)
        logger.info("Health monitor stopped")

    def _monitor_loop(self):
        """
        Main monitoring loop - runs in background thread
        """
        # Initial delay to allow server and dependencies to fully start
        # This prevents false "SYSTEM DOWN" alerts on startup
        initial_delay = 5  # seconds
        logger.info(f"Health monitor waiting {initial_delay}s for server startup before first check...")
        time.sleep(initial_delay)

        while self.is_running:
            try:
                self._check_health()
            except Exception as e:
                logger.error(f"Error in health monitor loop: {str(e)}")

            # Wait before next check
            time.sleep(self.check_interval)

    def _check_health(self):
        """
        Check application health and send notifications if status changes
        """
        try:
            # Make health check request with optimized timeout
            # The /health endpoint runs 5 component checks IN PARALLEL:
            # 1. DATABASE - MongoDB, Redis, MySQL, Azure Blob (1-2s, timeout: 10s)
            # 2. CHAT - Chat agent (2-3s, timeout: 15s)
            # 3. SEARCH - Search agent + 4 agents (3-4s, timeout: 15s)
            # 4. SOLUTION - Solution agent + deep instrument agent (2-3s, timeout: 15s)
            # 5. SYSTEM RESOURCES - CPU, Memory, Disk (0.1s, timeout: 10s)
            #
            # TIME ESTIMATION (PARALLEL EXECUTION):
            # - Best case: ~3 seconds (all healthy, fast network)
            # - Average case: ~4 seconds (normal conditions)
            # - Worst case: ~15 seconds (slowest component timeout)
            #
            # 30s timeout provides 15s safety margin (2x worst case)
            logger.info(f"🔍 Health check running: {self.health_url}")
            response = requests.get(self.health_url, timeout=30)
            logger.info(f"📊 Health check result: HTTP {response.status_code}")

            if response.status_code == 200:
                # System is healthy
                self._handle_healthy_status()
            else:
                # System returned error status code
                self._handle_unhealthy_status(f"HTTP {response.status_code}", is_timeout=False)

        except requests.exceptions.Timeout:
            logger.info("📊 Health check result: TIMEOUT")
            # A timeout means the server is alive but busy (e.g. processing a large LLM
            # request). Use a higher threshold before declaring the system down to avoid
            # false-positive alerts during heavy load.
            self._handle_unhealthy_status("Health check timeout", is_timeout=True)
        except requests.exceptions.ConnectionError:
            logger.info("📊 Health check result: CONNECTION FAILED")
            # A connection error means the server process is not accepting connections —
            # treat this as a hard failure with the normal (lower) threshold.
            self._handle_unhealthy_status("Connection failed", is_timeout=False)
        except Exception as e:
            logger.info(f"📊 Health check result: ERROR - {str(e)}")
            self._handle_unhealthy_status(f"Error: {str(e)}", is_timeout=False)

    def _handle_healthy_status(self):
        """
        Handle when system is healthy
        """
        current_status = "healthy"

        # Reset all failure counters on a successful check
        self.consecutive_failures = 0
        self.consecutive_timeouts = 0
        self.system_officially_down = False  # System is back up

        # If system was previously down, send restoration notification
        if self.last_status == "unhealthy" and not self.restoration_notified:
            logger.warning("🟢 SYSTEM RESTORED - Application is back online!")
            self._send_restoration_emails()
            self.restoration_notified = True
            self.downtime_notified = False  # Reset for next downtime

        self.last_status = current_status

    def _handle_unhealthy_status(self, reason: str, is_timeout: bool = False):
        """
        Handle when system is unhealthy.

        Args:
            reason: Reason for unhealthy status
            is_timeout: True if the failure was a request timeout (server busy),
                        False for hard failures (connection refused, HTTP error, etc.)
        """
        current_status = "unhealthy"

        if is_timeout:
            # Timeout: server is alive but busy. Track separately with a higher threshold
            # so heavy LLM requests don't trigger false-positive "system down" alerts.
            self.consecutive_timeouts += 1
            effective_count = self.consecutive_timeouts
            effective_threshold = self.timeout_threshold
            logger.warning(
                f"⚠️ Health check timeout ({effective_count}/{effective_threshold}): {reason}"
            )
        else:
            # Hard failure: server is not accepting connections. Use the normal threshold.
            self.consecutive_failures += 1
            # Timeouts that were pending no longer matter once we have a hard failure
            self.consecutive_timeouts = 0
            effective_count = self.consecutive_failures
            effective_threshold = self.failure_threshold
            logger.warning(
                f"⚠️ Health check failed ({effective_count}/{effective_threshold}): {reason}"
            )

        # Only send downtime notification after reaching the appropriate threshold
        # This prevents false alerts from transient network issues or heavy load
        if effective_count >= effective_threshold:
            self.system_officially_down = True  # Mark system as officially down
            if self.last_status != "unhealthy" and not self.downtime_notified:
                logger.error(f"🔴 SYSTEM DOWN - {reason} (after {effective_count} consecutive failures)")
                self._send_downtime_emails()
                self.downtime_notified = True
                self.restoration_notified = False  # Reset for next restoration
            self.last_status = current_status
        # Don't change last_status until threshold is reached (gives system time to recover)

    def _send_downtime_emails(self):
        """
        Send downtime notification emails to admins only.
        Users see the in-app banner instead.
        """
        import os

        # Check if email notifications are disabled (useful for local development)
        if os.getenv('DISABLE_HEALTH_EMAIL_NOTIFICATIONS', 'false').lower() == 'true':
            logger.info("📧 Email notifications disabled (DISABLE_HEALTH_EMAIL_NOTIFICATIONS=true)")
            return

        try:
            admin_emails = self._get_admin_emails_only()

            if not admin_emails:
                logger.warning("⚠️ No admin emails found to send downtime notification")
                logger.warning("💡 Tip: Set ADMIN_EMAIL environment variable as fallback")
                return

            logger.info(f"📧 Sending downtime notification to {len(admin_emails)} admin(s)...")
            success = send_downtime_notification(admin_emails)

            if success:
                logger.info(f"✅ Downtime notification sent successfully to {len(admin_emails)} admin(s)")
            else:
                logger.error("❌ Failed to send downtime notification - check SMTP configuration")

        except Exception as e:
            logger.error(f"❌ Error sending downtime emails: {str(e)}")

    def _send_restoration_emails(self):
        """
        Send restoration notification emails to admins only.
        Users see the in-app banner disappear instead.
        """
        import os

        # Check if email notifications are disabled (useful for local development)
        if os.getenv('DISABLE_HEALTH_EMAIL_NOTIFICATIONS', 'false').lower() == 'true':
            logger.info("📧 Email notifications disabled (DISABLE_HEALTH_EMAIL_NOTIFICATIONS=true)")
            return

        try:
            admin_emails = self._get_admin_emails_only()

            if not admin_emails:
                logger.warning("⚠️ No admin emails found to send restoration notification")
                logger.warning("💡 Tip: Set ADMIN_EMAIL environment variable as fallback")
                return

            logger.info(f"📧 Sending restoration notification to {len(admin_emails)} admin(s)...")
            success = send_restoration_notification(admin_emails)

            if success:
                logger.info(f"✅ Restoration notification sent successfully to {len(admin_emails)} admin(s)")
            else:
                logger.error("❌ Failed to send restoration notification - check SMTP configuration")

        except Exception as e:
            logger.error(f"❌ Error sending restoration emails: {str(e)}")

    def _get_admin_emails_only(self):
        """
        Get ONLY admin emails from the database.
        Regular users are notified via the in-app banner instead.

        Returns:
            List of admin email addresses only
        """
        import os

        # Always get the dedicated admin email first (fallback)
        dedicated_admin_email = os.getenv('ADMIN_EMAIL', '').strip()

        try:
            # Check if FastAPI app is available
            if not self.fastapi_app:
                logger.warning("⚠️ FastAPI app not provided to health monitor")
                if dedicated_admin_email:
                    logger.info(f"Using dedicated ADMIN_EMAIL: {dedicated_admin_email}")
                    return [dedicated_admin_email]
                return []

            if True:
                from app.models.db.base import db
                from app.models.db.user_model import User

                # Get admin users only (role='admin')
                admin_users = db.session.query(User).filter_by(role='admin').all()
                admin_emails = [user.email for user in admin_users if user.email]
                logger.info(f"Found {len(admin_emails)} admin user(s) in database")

                # Add dedicated admin email from environment (if not already included)
                if dedicated_admin_email and dedicated_admin_email not in admin_emails:
                    admin_emails.append(dedicated_admin_email)
                    logger.info("Added dedicated ADMIN_EMAIL from environment variable")

                # Remove duplicates while preserving order
                admin_emails = list(dict.fromkeys(admin_emails))

                logger.info(f"📧 Total {len(admin_emails)} admin email(s) to notify")
                return admin_emails

        except Exception as e:
            logger.error(f"❌ Error fetching admin emails: {str(e)}")
            # Fallback to dedicated admin email if database query fails
            if dedicated_admin_email:
                logger.warning("⚠️ Using fallback ADMIN_EMAIL due to database error")
                return [dedicated_admin_email]
            return []


class DualHealthMonitor:
    """
    Manages dual health monitoring - system health and agent health
    Each runs on its own interval in separate threads
    """

    def __init__(self, base_url: str, system_interval: int = 30, agent_interval: int = 10):
        """
        Initialize dual health monitor

        Args:
            base_url: Base URL of application (e.g., "http://localhost:5000")
            system_interval: Seconds between system health checks (default: 30)
            agent_interval: Seconds between agent health checks (default: 10)
            fastapi_app: FastAPI application instance (required for database access)
        """
        self.base_url = base_url.rstrip('/')
        self.system_monitor = HealthMonitor(f"{self.base_url}/health", system_interval, fastapi_app)
        self.agent_monitor = HealthMonitor(f"{self.base_url}/health/agents", agent_interval, fastapi_app)

    def start(self):
        """Start both health monitors"""
        logger.info("🚀 Starting dual health monitoring system...")
        self.system_monitor.start()
        self.agent_monitor.start()
        logger.info(f"✅ System health: checking every {self.system_monitor.check_interval}s")
        logger.info(f"✅ Agent health: checking every {self.agent_monitor.check_interval}s")

    def stop(self):
        """Stop both health monitors"""
        logger.info("Stopping dual health monitoring system...")
        self.system_monitor.stop()
        self.agent_monitor.stop()
        logger.info("✅ Dual health monitoring stopped")


# Global health monitor instances
_health_monitor_instance: HealthMonitor | None = None
_dual_health_monitor_instance: DualHealthMonitor | None = None
_health_monitors: list[HealthMonitor] = []  # Support multiple monitors


def start_health_monitor(health_url: str, check_interval: int = 60):
    """
    Start a health monitoring service for the given URL.
    Supports multiple monitors running concurrently.

    Args:
        health_url: URL of the health check endpoint (e.g., "http://localhost:5000/health")
        check_interval: Seconds between health checks (default: 60)
        fastapi_app: FastAPI application instance (required for database access and email notifications)
    """
    global _health_monitors

    # Check if this URL is already being monitored
    for monitor in _health_monitors:
        if monitor.health_url == health_url and monitor.is_running:
            logger.warning(f"Health monitor for {health_url} is already running")
            return

    # Create and start new monitor
    new_monitor = HealthMonitor(health_url, check_interval, fastapi_app)
    new_monitor.start()
    _health_monitors.append(new_monitor)


def start_dual_health_monitor(base_url: str, system_interval: int = 60, agent_interval: int = 60):
    """
    Start dual health monitoring (system + agents)

    Args:
        base_url: Base URL of application (e.g., "http://localhost:5000")
        system_interval: Seconds between system health checks (default: 60)
        agent_interval: Seconds between agent health checks (default: 60)
        fastapi_app: FastAPI application instance (required for database access and email notifications)
    """
    global _dual_health_monitor_instance

    if _dual_health_monitor_instance:
        logger.warning("Dual health monitor is already running")
        return

    _dual_health_monitor_instance = DualHealthMonitor(base_url, system_interval, agent_interval, fastapi_app)
    _dual_health_monitor_instance.start()


def stop_health_monitor():
    """
    Stop all health monitoring services
    """
    global _health_monitors

    for monitor in _health_monitors:
        if monitor.is_running:
            monitor.stop()
    _health_monitors.clear()


def stop_dual_health_monitor():
    """
    Stop the dual health monitoring service
    """
    global _dual_health_monitor_instance

    if _dual_health_monitor_instance:
        _dual_health_monitor_instance.stop()
        _dual_health_monitor_instance = None


def is_system_officially_down():
    """
    Check if the system is officially down (after 3 consecutive failures).
    This is the same condition that triggers the downtime email notification.

    Returns:
        bool: True if system is officially down, False otherwise
    """
    global _dual_health_monitor_instance
    global _health_monitors

    if _dual_health_monitor_instance:
        # Check the system monitor (not agent monitor)
        return _dual_health_monitor_instance.system_monitor.system_officially_down

    # If dual monitor is not running, check individual monitors
    for monitor in _health_monitors:
        # We assume the basic System health check is what we want to rely on
        if monitor.system_officially_down:
            return True

    # If no monitor instance, assume system is healthy
    return False
