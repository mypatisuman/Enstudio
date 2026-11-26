"""
Email Utility Module
Handles email notifications for system health monitoring and user alerts
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# Email configuration from environment variables
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.getenv('SMTP_FROM_EMAIL', SMTP_USERNAME)
APP_NAME = os.getenv('APP_NAME', 'Your Application')
LOGO_URL = os.getenv('LOGO_URL', '')  # Optional logo URL for emails
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '')  # Dedicated admin email for critical notifications


def _strip_wrapping_quotes(value: str) -> str:
    value = (value or '').strip()
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return value[1:-1].strip()
    return value


def validate_smtp_config() -> tuple[bool, str]:
    """
    Validate SMTP configuration

    Returns:
        Tuple of (is_valid, message)
    """
    global SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, APP_NAME

    SMTP_SERVER = _strip_wrapping_quotes(os.getenv('SMTP_SERVER', 'smtp.gmail.com'))
    SMTP_PORT = int(_strip_wrapping_quotes(os.getenv('SMTP_PORT', '587')))
    SMTP_USERNAME = _strip_wrapping_quotes(os.getenv('SMTP_USERNAME', ''))
    SMTP_PASSWORD = _strip_wrapping_quotes(os.getenv('SMTP_PASSWORD', ''))
    SMTP_FROM_EMAIL = _strip_wrapping_quotes(os.getenv('SMTP_FROM_EMAIL', SMTP_USERNAME))
    APP_NAME = _strip_wrapping_quotes(os.getenv('APP_NAME', 'Your Application'))

    if not SMTP_USERNAME:
        return False, "SMTP_USERNAME environment variable not set"

    if not SMTP_PASSWORD:
        return False, "SMTP_PASSWORD environment variable not set"

    if not SMTP_FROM_EMAIL:
        return False, "SMTP_FROM_EMAIL environment variable not set"

    return True, f"SMTP configured: {SMTP_SERVER}:{SMTP_PORT} (from: {SMTP_FROM_EMAIL})"


# Log SMTP configuration status on module load
is_valid, config_message = validate_smtp_config()
if is_valid:
    logger.info(f"✅ Email System Ready: {config_message}")
    if ADMIN_EMAIL:
        logger.info(f"✅ Dedicated admin email configured: {ADMIN_EMAIL}")
else:
    logger.warning(f"⚠️ Email System NOT Configured: {config_message}")
    logger.warning("⚠️ Health monitoring email notifications will NOT be sent!")


def send_email(to_emails: list[str], subject: str, html_body: str) -> bool:
    """
    Send email to multiple recipients

    Args:
        to_emails: List of recipient email addresses
        subject: Email subject
        html_body: HTML content of the email

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    smtp_ok, smtp_message = validate_smtp_config()
    if not smtp_ok:
        logger.error(f"❌ SMTP credentials not configured in environment variables: {smtp_message}")
        return False

    if not to_emails:
        logger.warning("⚠️ No recipient emails provided")
        return False

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM_EMAIL
        # Use BCC to hide recipient emails from each other (privacy protection)
        msg['Bcc'] = ', '.join(to_emails)

        # Attach HTML content
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)

        # --- AZURE/PROD OPTIMIZATION: Robust SMTP Connection Logic ---
        # 1. Try SSL connection (Port 465) - More reliable in cloud/Azure
        # 2. Try STARTTLS connection (Port 587) - Alternative

        server_port = int(SMTP_PORT)

        # Connection with increased timeout for Azure network latency
        if server_port == 465:
            logger.debug(f"Connecting to SMTP SSL: {SMTP_SERVER}:{server_port}")
            with smtplib.SMTP_SSL(SMTP_SERVER, server_port, timeout=45) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            logger.debug(f"Connecting to SMTP STARTTLS: {SMTP_SERVER}:{server_port}")
            with smtplib.SMTP(SMTP_SERVER, server_port, timeout=45) as server:
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)

        logger.info(f"✅ Email sent successfully to {len(to_emails)} recipients")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP Authentication Failed: {str(e)}")
        return False
    except (smtplib.SMTPException, ConnectionRefusedError, TimeoutError) as e:
        logger.error(f"❌ SMTP Connection Error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected Email Error: {str(e)}")
        return False


def test_smtp_connection() -> bool:
    """
    Test SMTP connection without sending an email
    Useful for verifying configuration

    Returns:
        bool: True if connection successful, False otherwise
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.error("❌ SMTP credentials not configured")
        return False

    try:
        logger.info(f"Testing SMTP connection to {SMTP_SERVER}:{SMTP_PORT}...")

        # Port 465 requires SSL from the start, port 587 uses STARTTLS
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
        else:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)

        logger.info("✅ SMTP connection test successful!")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP Authentication Failed: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"❌ SMTP connection test failed: {str(e)}")
        return False


def get_downtime_email_template(app_name: str) -> str:
    """
    HTML template for application downtime notification

    Args:
        app_name: Name of the application

    Returns:
        str: HTML email template
    """
    logo_html = f'<img src="{os.getenv("LOGO_URL", LOGO_URL)}" alt="{app_name}" class="logo-circle" draggable="false">' if os.getenv("LOGO_URL", LOGO_URL) else ''

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.6;
                color: #1a1c21;
                margin: 0;
                padding: 0;
                background-color: #f4f7fa;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.08);
                overflow: hidden;
            }}
            .header {{
                background-color: #3B82F6;
                padding: 30px 40px;
                color: white;
            }}
            .header-table {{
                width: 100%;
                border-collapse: collapse;
            }}
            .logo-cell {{
                width: 60px;
                vertical-align: middle;
            }}
            .logo-circle {{
                width: 60px;
                height: 60px;
                border-radius: 50%;
                object-fit: cover;
                background: white;
                padding: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                pointer-events: none;
                user-select: none;
                -webkit-user-select: none;
                -webkit-user-drag: none;
                -moz-user-select: none;
                -ms-user-select: none;
            }}
            .header-text-cell {{
                text-align: center;
                vertical-align: middle;
                padding-right: 60px; /* Balances the logo on the left to keep text centered in div */
            }}
            .header-text h1 {{
                margin: 0;
                font-size: 24px;
                font-weight: 700;
                color: white;
            }}
            .content {{
                padding: 40px;
            }}
            .footer {{
                padding: 30px;
                background-color: #fcfcfd;
                border-top: 1px solid #f1f5f9;
                text-align: center;
                font-size: 13px;
                color: #94a3b8;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <table class="header-table">
                    <tr>
                        <td class="logo-cell">
                            {logo_html}
                        </td>
                        <td class="header-text-cell">
                            <h1>Service Interruption</h1>
                        </td>
                    </tr>
                </table>
            </div>
            <div class="content">
                <h2>Service Interruption Notice</h2>
                <p>We're writing to inform you that <strong>{app_name}</strong> is currently experiencing an unexpected service interruption and is temporarily unavailable.</p>

                <p><strong>Current Status:</strong></p>
                <ul>
                    <li>Service is temporarily offline</li>
                    <li>Our engineering team has been automatically alerted and is actively investigating</li>
                    <li>All your data remains secure and protected</li>
                </ul>

                <p><strong>What This Means for You:</strong></p>
                <ul>
                    <li>You may experience difficulty accessing the platform</li>
                    <li>No action is required on your part</li>
                    <li>We'll notify you immediately once service is restored</li>
                </ul>

                <p>We understand how important uninterrupted access is to your workflow, and we're committed to resolving this issue as quickly as possible. You'll receive a follow-up notification as soon as the system is fully operational.</p>

                <p>We sincerely apologize for any inconvenience this may cause and appreciate your patience.</p>

                <p>If you have urgent questions, please don't hesitate to contact our support team.</p>

                <p>Best regards,<br>
                <strong>The {app_name} Team</strong></p>
            </div>
            <div class="footer">
                <p>This is an automated system notification. Please do not reply to this email.</p>
            </div>
        </div>
    </body>
    </html>
    """


def get_restoration_email_template(app_name: str) -> str:
    """
    HTML template for application restoration notification

    Args:
        app_name: Name of the application

    Returns:
        str: HTML email template
    """
    logo_html = f'<img src="{os.getenv("LOGO_URL", LOGO_URL)}" alt="{app_name}" class="logo-circle" draggable="false">' if os.getenv("LOGO_URL", LOGO_URL) else ''

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.6;
                color: #1a1c21;
                margin: 0;
                padding: 0;
                background-color: #f4f7fa;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.08);
                overflow: hidden;
            }}
            .header {{
                background-color: #3B82F6;
                padding: 30px 40px;
                color: white;
            }}
            .header-table {{
                width: 100%;
                border-collapse: collapse;
            }}
            .logo-cell {{
                width: 60px;
                vertical-align: middle;
            }}
            .logo-circle {{
                width: 60px;
                height: 60px;
                border-radius: 50%;
                object-fit: cover;
                background: white;
                padding: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                pointer-events: none;
                user-select: none;
                -webkit-user-select: none;
                -webkit-user-drag: none;
                -moz-user-select: none;
                -ms-user-select: none;
            }}
            .header-text-cell {{
                text-align: center;
                vertical-align: middle;
                padding-right: 60px; /* Balances the logo on the left to keep text centered in div */
            }}
            .header-text h1 {{
                margin: 0;
                font-size: 24px;
                font-weight: 700;
                color: white;
            }}
            .content {{
                padding: 40px;
            }}
            .footer {{
                padding: 30px;
                background-color: #fcfcfd;
                border-top: 1px solid #f1f5f9;
                text-align: center;
                font-size: 13px;
                color: #94a3b8;
            }}
            .cta-button {{
                display: inline-block;
                padding: 12px 30px;
                background-color: #3B82F6;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                margin-top: 20px;
                font-weight: 600;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <table class="header-table">
                    <tr>
                        <td class="logo-cell">
                            {logo_html}
                        </td>
                        <td class="header-text-cell">
                            <h1>Service Restored</h1>
                        </td>
                    </tr>
                </table>
            </div>
            <div class="content">
                <h2>Service Fully Restored</h2>
                <p>We're pleased to inform you that <strong>{app_name}</strong> has been fully restored and is now operating normally.</p>

                <p><strong>Resolution Summary:</strong></p>
                <ul>
                    <li>All systems are back online and fully operational</li>
                    <li>The underlying issue has been identified and resolved</li>
                    <li>Additional monitoring has been implemented to prevent recurrence</li>
                </ul>

                <p><strong>You Can Now:</strong></p>
                <ul>
                    <li>Access all platform features without any restrictions</li>
                    <li>Resume your normal workflow</li>
                    <li>Rest assured that all your data is intact and secure</li>
                </ul>

                <p>We sincerely apologize for any disruption this may have caused to your work. We've taken steps to strengthen our infrastructure and monitoring to minimize the likelihood of similar incidents in the future.</p>

                <p>Thank you for your patience and understanding during the service interruption. If you continue to experience any issues or have questions, our support team is ready to assist you.</p>

                <p>Best regards,<br>
                <strong>The {app_name} Team</strong></p>
            </div>
            <div class="footer">
                <p>This is an automated system notification. Please do not reply to this email.</p>
            </div>
        </div>
    </body>
    </html>
    """


def send_downtime_notification(user_emails: list[str]) -> bool:
    """
    Send downtime notification to all users

    Args:
        user_emails: List of user email addresses

    Returns:
        bool: True if email sent successfully
    """
    subject = f"[Service Alert] {APP_NAME} - Temporary Service Interruption"
    html_body = get_downtime_email_template(APP_NAME)
    return send_email(user_emails, subject, html_body)


def send_restoration_notification(user_emails: list[str]) -> bool:
    """
    Send restoration notification to all users

    Args:
        user_emails: List of user email addresses

    Returns:
        bool: True if email sent successfully
    """
    subject = f"[Service Restored] {APP_NAME} - All Systems Operational"
    html_body = get_restoration_email_template(APP_NAME)
    return send_email(user_emails, subject, html_body)


def get_verification_otp_template(app_name: str, otp_code: str) -> str:
    """
    HTML template for email verification OTP (Premium Design)
    """
    from datetime import datetime
    logo_html = f'<img src="{os.getenv("LOGO_URL", LOGO_URL)}" alt="{app_name}" width="60" height="60" style="display: block; border-radius: 50%; max-width: 60px; max-height: 60px; background: white; padding: 8px;" class="logo-circle" draggable="false">' if os.getenv("LOGO_URL", LOGO_URL) else ''

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background-color: #f4f7fa;
                margin: 0;
                padding: 0;
                -webkit-font-smoothing: antialiased;
            }}
            .wrapper {{
                width: 100%;
                table-layout: fixed;
                background-color: #f4f7fa;
                padding-bottom: 40px;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
                overflow: hidden;
                margin-top: 40px;
            }}
            .header {{
                background-color: #3B82F6;
                padding: 30px 40px;
                color: white;
            }}
            .header-table {{
                width: 100%;
                border-collapse: collapse;
            }}
            .logo-cell {{
                width: 60px;
                vertical-align: middle;
            }}
            .logo-circle {{
                width: 60px;
                height: 60px;
                border-radius: 50%;
                object-fit: cover;
                background: white;
                padding: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                pointer-events: none;
                user-select: none;
                -webkit-user-select: none;
                -webkit-user-drag: none;
                -moz-user-select: none;
                -ms-user-select: none;
            }}
            .header-text-cell {{
                text-align: center;
                vertical-align: middle;
                padding-right: 60px; /* Balances the logo on the left to keep text centered in div */
            }}
            .header-text h1 {{
                margin: 0;
                font-size: 26px;
                color: white;
                font-weight: 700;
                letter-spacing: -0.5px;
                line-height: 1.2;
            }}
            .header-text p {{
                margin: 4px 0 0;
                font-size: 16px;
                color: rgba(255, 255, 255, 0.9);
            }}
            .content {{
                padding: 40px;
            }}
            .content h2 {{
                font-size: 18px;
                color: #1a1c21;
                margin-bottom: 16px;
            }}
            .content p {{
                font-size: 16px;
                line-height: 24px;
                color: #475569;
                margin-bottom: 24px;
            }}
            .otp-container {{
                background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: 30px;
                text-align: center;
                margin: 30px 0;
            }}
            .otp-label {{
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 1px;
                color: #94a3b8;
                font-weight: 600;
                margin-bottom: 12px;
            }}
            .otp-code {{
                font-family: 'SF Mono', 'Fira Code', monospace;
                font-size: 42px;
                font-weight: 800;
                color: #3B82F6;
                letter-spacing: 12px;
                margin: 0;
            }}
            .footer {{
                padding: 30px 40px;
                background-color: #fcfcfd;
                border-top: 1px solid #f1f5f9;
                text-align: center;
            }}
            .footer p {{
                font-size: 13px;
                color: #94a3b8;
                margin: 0 0 10px;
                line-height: 20px;
            }}
            .footer-links {{
                margin-top: 15px;
            }}
            .footer-links a {{
                color: #3B82F6;
                text-decoration: none;
                margin: 0 10px;
                font-size: 13px;
            }}
            .warning-badge {{
                display: inline-block;
                background-color: #fff7ed;
                color: #c2410c;
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="wrapper">
            <div class="container">
                <div class="header">
                    <table class="header-table">
                        <tr>
                            <td class="logo-cell">
                                {logo_html}
                            </td>
                            <td class="header-text-cell">
                                <div class="header-text">
                                    <h1>Verify Your Email</h1>
                                    <p>Welcome to {app_name}</p>
                                </div>
                            </td>
                        </tr>
                    </table>
                </div>
                <div class="content">
                    <p>Hello,</p>
                    <p>Thank you for signing up with <strong>{app_name}</strong>. To ensure the security of your account, please verify your email address by entering the code below.</p>

                    <div class="otp-container">
                        <div class="otp-label">Your Verification Code</div>
                        <div class="otp-code">{otp_code}</div>
                    </div>

                    <div class="warning-badge">
                        ⏱️ Valid for 10 minutes
                    </div>

                    <p><strong>Why am I receiving this?</strong><br>
                    This verification step helps us confirm that you own this email address and protects your account from unauthorized access.</p>

                    <p><strong>Didn't request this code?</strong><br>
                    If you didn't attempt to sign up for {app_name}, you can safely disregard this email. Your email address may have been entered by mistake.</p>

                    <p>If you need assistance, our support team is here to help.</p>

                    <p>Best regards,<br>
                    <strong>The {app_name} Team</strong></p>
                </div>
                <div class="footer">
                    <p>&copy; {datetime.now().year} {app_name}. All rights reserved.</p>
                    <p>This is an automated system message. Please do not reply to this email.</p>
                    <div class="footer-links">
                        <a href="#">Privacy Policy</a>
                        <a href="#">Terms of Service</a>
                        <a href="#">Support</a>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


def send_verification_otp(email: str, otp_code: str) -> bool:
    """
    Send a verification OTP to a single email address.
    Uses direct To: header (not BCC) to ensure delivery to Microsoft/Outlook inboxes.
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.error("SMTP credentials not configured for OTP email")
        return False

    try:
        subject = f"Verify your email address for {APP_NAME}"
        html_body = get_verification_otp_template(APP_NAME, otp_code)

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM_EMAIL
        msg['To'] = email  # Direct To: header for reliable delivery

        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)

        # Robust connection with increased timeout for Azure/Cloud
        server_port = int(SMTP_PORT)

        if server_port == 465:
            logger.debug(f"Connecting to SMTP SSL: {SMTP_SERVER}:{server_port}")
            with smtplib.SMTP_SSL(SMTP_SERVER, server_port, timeout=45) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            logger.debug(f"Connecting to SMTP STARTTLS: {SMTP_SERVER}:{server_port}")
            with smtplib.SMTP(SMTP_SERVER, server_port, timeout=45) as server:
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)

        logger.info(f"✅ OTP email sent successfully to {email}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ OTP SMTP Authentication Failed for {email}: {str(e)}")
        return False
    except (smtplib.SMTPException, ConnectionRefusedError, TimeoutError, OSError) as e:
        logger.error(f"❌ OTP SMTP Connection Error for {email}: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected OTP Email Error for {email}: {str(e)}")
        return False


def get_contact_form_template(app_name: str, name: str, email: str, phone: str, message: str) -> str:
    """
    HTML template for contact form submission notification

    Args:
        app_name: Name of the application
        name: Contact person's name
        email: Contact person's email
        phone: Contact person's phone
        message: Contact message

    Returns:
        str: HTML email template
    """
    from datetime import datetime
    logo_html = f'<img src="{os.getenv("LOGO_URL", LOGO_URL)}" alt="{app_name}" class="logo-circle" draggable="false">' if os.getenv("LOGO_URL", LOGO_URL) else ''

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background-color: #f4f7fa;
                margin: 0;
                padding: 0;
                line-height: 1.6;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
                overflow: hidden;
            }}
            .header {{
                background-color: #3B82F6;
                padding: 30px 40px;
                color: white;
            }}
            .header-table {{
                width: 100%;
                border-collapse: collapse;
            }}
            .logo-cell {{
                width: 60px;
                vertical-align: middle;
            }}
            .logo-circle {{
                width: 60px;
                height: 60px;
                border-radius: 50%;
                object-fit: cover;
                background: white;
                padding: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }}
            .header-text-cell {{
                text-align: center;
                vertical-align: middle;
                padding-right: 60px;
            }}
            .header-text h1 {{
                margin: 0;
                font-size: 24px;
                font-weight: 700;
                color: white;
            }}
            .content {{
                padding: 40px;
            }}
            .info-section {{
                background-color: #f8fafc;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }}
            .info-row {{
                margin-bottom: 12px;
                padding-bottom: 12px;
                border-bottom: 1px solid #e2e8f0;
            }}
            .info-row:last-child {{
                border-bottom: none;
                margin-bottom: 0;
                padding-bottom: 0;
            }}
            .info-label {{
                font-weight: 600;
                color: #1a1c21;
                font-size: 13px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 4px;
            }}
            .info-value {{
                color: #475569;
                font-size: 15px;
            }}
            .message-box {{
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
                white-space: pre-wrap;
                word-wrap: break-word;
            }}
            .footer {{
                padding: 30px 40px;
                background-color: #fcfcfd;
                border-top: 1px solid #f1f5f9;
                text-align: center;
                font-size: 13px;
                color: #94a3b8;
            }}
            .timestamp {{
                color: #94a3b8;
                font-size: 12px;
                margin-top: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <table class="header-table">
                    <tr>
                        <td class="logo-cell">
                            {logo_html}
                        </td>
                        <td class="header-text-cell">
                            <h1>New Contact Form Submission</h1>
                        </td>
                    </tr>
                </table>
            </div>
            <div class="content">
                <h2 style="margin-top: 0; color: #1a1c21;">Contact Request from Landing Page</h2>
                <p style="color: #475569;">You have received a new contact form submission from the {app_name} landing page.</p>

                <div class="info-section">
                    <div class="info-row">
                        <div class="info-label">Name</div>
                        <div class="info-value">{name}</div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">Email Address</div>
                        <div class="info-value"><a href="mailto:{email}" style="color: #3B82F6; text-decoration: none;">{email}</a></div>
                    </div>
                    <div class="info-row">
                        <div class="info-label">Phone Number</div>
                        <div class="info-value">{phone}</div>
                    </div>
                </div>

                <div class="info-label" style="margin-bottom: 8px;">Message</div>
                <div class="message-box">
                    {message}
                </div>

                <div class="timestamp">
                    Submitted on {datetime.now().strftime('%B %d, %Y at %I:%M %p UTC')}
                </div>
            </div>
            <div class="footer">
                <p>This is an automated notification from {app_name} Contact Form.</p>
                <p>&copy; {datetime.now().year} {app_name}. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


def send_contact_form_email(name: str, email: str, phone: str, message: str, support_email: str = "support@engenieai.com") -> bool:
    """
    Send contact form submission to support email

    Args:
        name: Contact person's name
        email: Contact person's email
        phone: Contact person's phone
        message: Contact message
        support_email: Support team email address

    Returns:
        bool: True if email sent successfully
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.error("SMTP credentials not configured for contact form email")
        return False

    try:
        subject = f"[{APP_NAME}] New Contact Form Submission from {name}"
        html_body = get_contact_form_template(APP_NAME, name, email, phone, message)

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM_EMAIL
        msg['To'] = support_email
        msg['Reply-To'] = email  # Allow easy reply to the contact person

        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)

        # Robust connection with increased timeout for Azure/Cloud
        server_port = int(SMTP_PORT)

        if server_port == 465:
            logger.debug(f"Connecting to SMTP SSL: {SMTP_SERVER}:{server_port}")
            with smtplib.SMTP_SSL(SMTP_SERVER, server_port, timeout=45) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            logger.debug(f"Connecting to SMTP STARTTLS: {SMTP_SERVER}:{server_port}")
            with smtplib.SMTP(SMTP_SERVER, server_port, timeout=45) as server:
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)

        logger.info(f"✅ Contact form email sent successfully to {support_email} from {name} ({email})")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ Contact Form SMTP Authentication Failed: {str(e)}")
        return False
    except (smtplib.SMTPException, ConnectionRefusedError, TimeoutError, OSError) as e:
        logger.error(f"❌ Contact Form SMTP Connection Error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send contact form email: {str(e)}")
        return False
