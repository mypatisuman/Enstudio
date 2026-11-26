"""
Auth Router
Routes: /api/csrf-token, /api/send-otp, /api/verify-otp, /api/contact-form,
        /api/microsoft-signin, /api/microsoft-signup, /api/verify-email,
        /api/validate-email, /register, /login, /logout, /user,
        /api/update_profile
Extracted from main.py lines ~1678-1884, ~8129-9060
"""
import logging
import os
import re
import secrets
import string
from datetime import UTC, datetime

import json
from fastapi import APIRouter, Request, UploadFile

from common.helpers.azure_session import get_session
from common.helpers.responses import JSONResponse

from app.core.security import generate_jwt_token, login_required, validate_uploaded_file
from app.models.db.base import db
from app.models.db.user_model import User
from common.auth.password import check_password, hash_password
from common.infra.database import redis_otp_client
from common.helpers.file_helpers import _safe_secure_filename, is_allowed_file
from app.services.upload_service import process_strategy_upload, process_assets_upload, upload_and_queue_standards_processing

blueprint = APIRouter()




# ── CSRF token ────────────────────────────────────────────────────────────────

@blueprint.get("/api/csrf-token")
async def get_csrf_token(request: Request):
    """Generate and return a CSRF token for the frontend."""
    try:
        token = secrets.token_hex(32)
        return JSONResponse({"csrfToken": token}, status_code=200)
    except Exception as e:
        logging.exception("Failed to generate CSRF token: %s", e)
        return JSONResponse({"error": "Failed to generate CSRF token"}, status_code=503)


# ── OTP ───────────────────────────────────────────────────────────────────────

@blueprint.post("/api/send-otp")
async def send_otp(request: Request):
    """Generate a 6-digit OTP and send it to the provided email address."""
    from common.services.email_service import send_verification_otp

    try:
        data = await request.json()
    except Exception:
        data = {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return JSONResponse({"success": False, "error": "Email is required"}, status_code=400)

    otp_code = "".join(secrets.choice(string.digits) for _ in range(6))

    try:
        success = send_verification_otp(email, otp_code)
        if not success:
            return JSONResponse({"success": False, "error": "Failed to send verification email. Please try again."}, status_code=500)
    except Exception as e:
        logging.error(f"[OTP] Error sending OTP to {email}: {e}")
        return JSONResponse({"success": False, "error": "Failed to send verification email. Please try again."}, status_code=500)

    if redis_otp_client:
        try:
            redis_otp_client.setex(f"otp:{email}", 600, otp_code)
        except Exception as redis_err:
            logging.error(f"[OTP] Redis setex failed for {email}: {redis_err}")
            return JSONResponse({"success": False, "error": "Service temporarily unavailable. Please try again."}, status_code=503)
    else:
        logging.error("[OTP] Redis not available")
        return JSONResponse({"success": False, "error": "Service temporarily unavailable"}, status_code=503)

    return JSONResponse({"success": True, "message": "Verification code sent to your email"}, status_code=200)


@blueprint.post("/api/verify-otp")
async def verify_otp(request: Request):
    """Verify the OTP code entered by the user."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    email = (data.get("email") or "").strip().lower()
    otp_code = (data.get("otp") or "").strip()

    if not email or not otp_code:
        return JSONResponse({"verified": False, "error": "Email and OTP are required"}, status_code=400)

    if not redis_otp_client:
        return JSONResponse({"verified": False, "error": "Service temporarily unavailable"}, status_code=503)

    try:
        stored_otp = redis_otp_client.get(f"otp:{email}")
    except Exception as redis_err:
        logging.error(f"[OTP] Redis get failed for {email}: {redis_err}")
        return JSONResponse({"verified": False, "error": "Service temporarily unavailable. Please try again."}, status_code=503)

    if not stored_otp:
        return JSONResponse({"verified": False, "error": "No verification code found. Please request a new code."}, status_code=200)

    if secrets.compare_digest(otp_code, stored_otp):
        try:
            redis_otp_client.delete(f"otp:{email}")
            redis_otp_client.setex(f"verified:{email}", 600, "true")
        except Exception as redis_err:
            logging.error(f"[OTP] Redis update failed after verify for {email}: {redis_err}")
            return JSONResponse({"verified": False, "error": "Service temporarily unavailable. Please try again."}, status_code=503)
        return JSONResponse({"verified": True, "message": "Email verified successfully!"}, status_code=200)
    else:
        return JSONResponse({"verified": False, "error": "Incorrect verification code. Please try again."}, status_code=200)


# ── Contact form ─────────────────────────────────────────────────────────────

@blueprint.post("/api/contact-form")
async def submit_contact_form(request: Request):
    """Handle contact form submissions from the landing page."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not phone or not message:
        return JSONResponse({"success": False, "error": "All fields are required"}, status_code=400)

    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_regex, email):
        return JSONResponse({"success": False, "error": "Invalid email format"}, status_code=400)

    if not re.match(r"^\d{10}$", phone):
        return JSONResponse({"success": False, "error": "Phone number must be 10 digits"}, status_code=400)

    try:
        from common.services.email_service import send_contact_form_email, validate_smtp_config
        smtp_ok, smtp_message = validate_smtp_config()
        if not smtp_ok:
            return JSONResponse({"success": False, "error": "Contact service is temporarily unavailable."}, status_code=503)

        success = send_contact_form_email(name=name, email=email, phone=phone, message=message, support_email="support@engenieai.com")
        if success:
            return JSONResponse({"success": True, "message": "Thank you for contacting us! We'll get back to you soon."}, status_code=200)
        else:
            return JSONResponse({"success": False, "error": "Failed to send message. Please try again later."}, status_code=500)
    except Exception as e:
        logging.error(f"[Contact Form] Error: {e}")
        return JSONResponse({"success": False, "error": "An error occurred. Please try again later."}, status_code=500)


# ── Microsoft SSO ─────────────────────────────────────────────────────────────

@blueprint.post("/api/microsoft-signin")
async def microsoft_signin(request: Request):
    session = get_session(request)
    """Handle 'Sign in with Microsoft' flow."""
    from common.auth.azure_ad import check_email_exists_in_organization

    try:
        data = await request.json()
    except Exception:
        data = {}
        email = (data.get("email") or "").strip().lower()
        ms_name = data.get("name", "")

        if not email:
            return JSONResponse({"success": False, "error": "Email is required"}, status_code=400)

        result = check_email_exists_in_organization(email)
        if not result.get("exists"):
            return JSONResponse({"success": False, "error": "This Microsoft account is not authorized. Only organization members can sign in."}, status_code=403)

        existing_user = db.session.query(User).filter_by(email=email).first()
        if existing_user:
            if existing_user.status != "active":
                return JSONResponse({"success": False, "error": f"Account not active. Current status: {existing_user.status}."}, status_code=403)

            session.clear()
            session["user_id"] = existing_user.id
            session["user_role"] = existing_user.role

            full_name = " ".join(filter(None, [existing_user.first_name, existing_user.last_name])) or existing_user.username
            
            # Start session tracking
            try:
                from common.monitoring.usage import session_analytics
                import time as _time
                session_id = request.headers.get("x-session-id") or f"ms_{existing_user.id}_{int(_time.time())}"
                session["session_id"] = session_id
                session_analytics.start_session(
                    user_id=str(existing_user.id),
                    session_id=str(session_id),
                    request_data={
                        "remote_addr": request.headers.get("x-forwarded-for") or "127.0.0.1",
                        "user_agent": request.headers.get("User-Agent"),
                        "referer": request.headers.get("Referer", ""),
                        "origin": request.headers.get("Origin", "")
                    }
                )
            except Exception as e:
                logging.error(f"[TRACKING] Failed to start MS log session: {e}")

            return JSONResponse({"success": True, "message": "Login successful", "isNewUser": False, "user": {"username": existing_user.username, "name": full_name, "first_name": existing_user.first_name, "last_name": existing_user.last_name, "email": existing_user.email, "role": existing_user.role, "company": existing_user.company, "location": existing_user.location}}, status_code=200)
        else:
            return JSONResponse({"success": False, "error": "This Microsoft account is not registered. Please sign up first."}, status_code=403)

    except Exception as e:
        logging.error(f"Microsoft Sign-In error: {e}")
        return JSONResponse({"success": False, "error": f"Sign-in failed: {str(e)}"}, status_code=500)


@blueprint.post("/api/microsoft-signup")
async def microsoft_signup(request: Request):
    session = get_session(request)
    """Handle 'Sign up with Microsoft' flow."""
    from common.auth.azure_ad import check_email_exists_in_organization

    try:
        data = await request.json()
    except Exception:
        data = {}
        email = (data.get("email") or "").strip().lower()
        ms_name = data.get("name", "")

        if not email:
            return JSONResponse({"success": False, "error": "Email is required"}, status_code=400)

        result = check_email_exists_in_organization(email)
        if not result.get("exists"):
            return JSONResponse({"success": False, "error": "This Microsoft account is not authorized."}, status_code=403)

        user_data = result.get("user_data", {})
        display_name = user_data.get("name") or ms_name or email.split("@")[0]

        existing_user = db.session.query(User).filter_by(email=email).first()
        if existing_user:
            return JSONResponse({"success": False, "error": "This Microsoft account is already registered. Please sign in instead."}, status_code=409)

        name_parts = display_name.strip().split(" ", 1)
        first_name = name_parts[0] if name_parts else email.split("@")[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        base_username = email.split("@")[0]
        username = base_username
        counter = 1
        while db.session.query(User).filter_by(username=username).first():
            username = f"{base_username}{counter}"
            counter += 1

        random_password = "".join(secrets.choice(string.ascii_letters + string.digits + string.punctuation) for _ in range(32))
        hashed_pw = hash_password(random_password)

        new_user = User(username=username, email=email, password_hash=hashed_pw, first_name=first_name, last_name=last_name, status="pending", role="user")
        db.session.add(new_user)
        db.session.commit()

        return JSONResponse({"success": True, "message": "Account created successfully! Your account is pending admin approval.", "isPending": True, "user": {"username": username, "email": email, "first_name": first_name, "last_name": last_name, "status": "pending"}}, status_code=201)

    except Exception as e:
        logging.error(f"Microsoft Sign-Up error: {e}")
        db.session.rollback()
        return JSONResponse({"success": False, "error": f"Sign-up failed: {str(e)}"}, status_code=500)


@blueprint.post("/api/verify-email")
async def azure_ad_verify_email(request: Request):
    session = get_session(request)
    """Verify if email exists in Azure AD organization before allowing signup."""
    from common.auth.azure_ad import check_email_exists_in_organization

    try:
        data = await request.json()
    except Exception:
        data = {}
        email = data.get("email", "").lower().strip()
        if not email:
            return JSONResponse({"exists": False, "message": "Email is required", "can_proceed": False}, status_code=400)

        result = check_email_exists_in_organization(email)
        if result.get("exists"):
            user_data = result.get("user_data")
            return JSONResponse({"exists": True, "message": f"Email verified! Welcome {user_data.get('name')}", "can_proceed": True, "user_name": user_data.get("name"), "user_id": user_data.get("user_id")}, status_code=200)
        else:
            return JSONResponse({"exists": False, "message": f"This email is not registered with your organization. {result.get('error', '')}", "can_proceed": False}, status_code=200)
    except Exception as e:
        return JSONResponse({"exists": False, "message": f"Error: {str(e)}", "can_proceed": False}, status_code=500)


@blueprint.post("/api/validate-email")
async def validate_email_endpoint(request: Request):
    session = get_session(request)
    """Validate if an email address is real using DNS MX record lookup."""
    import dns.resolver

    try:
        data = await request.json()
    except Exception:
        data = {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return JSONResponse({"valid": False, "error": "Email is required"}, status_code=400)

    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_regex, email):
        return JSONResponse({"valid": False, "error": "Invalid email format"}, status_code=200)

    domain = email.split("@")[1]

    try:
        mx_records = dns.resolver.resolve(domain, "MX")
        if not mx_records:
            return JSONResponse({"valid": False, "error": "This email domain does not exist."}, status_code=200)

        if db.session.query(User).filter_by(email=email).first():
            return JSONResponse({"valid": False, "error": "This email is already registered. Please login instead."}, status_code=200)

        return JSONResponse({"valid": True, "message": "Email is valid"}, status_code=200)

    except dns.resolver.NXDOMAIN:
        return JSONResponse({"valid": False, "error": "This email domain does not exist."}, status_code=200)
    except dns.resolver.NoAnswer:
        return JSONResponse({"valid": False, "error": "This email domain cannot receive emails."}, status_code=200)
    except dns.resolver.NoNameservers:
        return JSONResponse({"valid": False, "error": "This email domain is not reachable."}, status_code=200)
    except Exception as e:
        logging.warning(f"[EMAIL_VALIDATION] DNS lookup failed for {domain}: {e}")
        return JSONResponse({"valid": True, "message": "Could not verify domain, proceeding"}, status_code=200)


# ── Register ──────────────────────────────────────────────────────────────────

@blueprint.post("/register")
async def register(request: Request):
    session = get_session(request)
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        data = await request.form()
        file = data.get("document")
        assets_file = data.get("assets_document")
    else:
        try:
            data = await request.json()
        except Exception:
            data = {}
        file = None
        assets_file = None

    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    company = data.get("company", "").strip()
    location = data.get("location", "").strip()
    strategy = data.get("strategy", "").strip()

    standards_file = None
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form_data = await request.form()
        standards_file = form_data.get("standards_document")

    if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$", password):
        return JSONResponse({"error": "Password must be at least 8 characters long, contain an uppercase letter, a lowercase letter, a number, and a special character."}, status_code=400)

    if db.session.query(User).filter_by(username=username).first():
        return JSONResponse({"error": "Username already exists"}, status_code=409)
    if db.session.query(User).filter_by(email=email).first():
        return JSONResponse({"error": "Email already registered"}, status_code=409)

    pending_strategy_file_data = None
    pending_strategy_filename = None
    if file:
        try:
            filename = _safe_secure_filename(file.filename)
            if not is_allowed_file(filename):
                return JSONResponse({"error": f"Invalid strategy file extension."}, status_code=400)
            file_data = await file.read()
            pending_strategy_file_data = file_data
            pending_strategy_filename = filename
        except Exception as e:
            logging.error(f"Failed to read signup document: {e}")

    pending_assets_file_data = None
    pending_assets_filename = None
    if assets_file:
        try:
            assets_filename_temp = _safe_secure_filename(assets_file.filename)
            if not is_allowed_file(assets_filename_temp):
                return JSONResponse({"error": f"Invalid assets file extension."}, status_code=400)
            assets_file_data = await assets_file.read()
            pending_assets_file_data = assets_file_data
            pending_assets_filename = assets_filename_temp
        except Exception as e:
            logging.error(f"Failed to read signup assets document: {e}")

    pending_standards_file_data = None
    pending_standards_filename = None
    pending_standards_content_type = None
    if standards_file:
        try:
            validation = validate_uploaded_file(standards_file, allowed_extensions=['.pdf', '.docx', '.doc', '.txt'])
            if not validation["valid"]:
                return JSONResponse({"error": validation["error"]}, status_code=400)
            standards_file_data = await standards_file.read()
            pending_standards_file_data = standards_file_data
            pending_standards_filename = validation["filename"]
            pending_standards_content_type = standards_file.content_type
        except Exception as e:
            logging.error(f"Failed to read signup standards document: {e}")

    hashed_pw = hash_password(password)
    new_user = User(username=username, email=email, password_hash=hashed_pw, first_name=first_name, last_name=last_name, company=company, location=location, strategy=strategy, status="pending", role="user")
    db.session.add(new_user)
    db.session.commit()

    if pending_strategy_file_data and pending_strategy_filename:
        # Process strategy upload synchronously
        try:
            process_strategy_upload(pending_strategy_file_data, pending_strategy_filename, new_user.id)
        except Exception as e:
            logging.error(f"Failed to process signup strategy document {pending_strategy_filename}: {e}", exc_info=True)

    if pending_assets_file_data and pending_assets_filename:
        # Process assets upload synchronously
        try:
            process_assets_upload(pending_assets_file_data, pending_assets_filename, new_user.id)
        except Exception as e:
            logging.error(f"Failed to process signup assets document {pending_assets_filename}: {e}", exc_info=True)

    if pending_standards_file_data and pending_standards_filename:
        try:
            from common.infra.azure_blob import azure_blob_manager
            from app.services.upload_service import extract_and_store_standards_text
            
            logging.info(f"[AUTH] Processing signup standards document: {pending_standards_filename}")
            
            # Upload to blob storage
            blob_info = azure_blob_manager.upload_standards_document(
                file_bytes=pending_standards_file_data,
                filename=pending_standards_filename,
                user_id=new_user.id,
                content_type=pending_standards_content_type or "application/pdf",
            )
            
            blob_url = blob_info.get('blobUrl') if blob_info else None
            if blob_url:
                # Process synchronously
                result = extract_and_store_standards_text(
                    pending_standards_file_data, 
                    pending_standards_filename, 
                    new_user.id, 
                    blob_url
                )
                if not result.get("success"):
                    logging.error(f"Failed to process signup standards document {pending_standards_filename}: {result.get('error')}")
                else:
                    logging.info(f"Successfully processed signup standards document: {pending_standards_filename}")
            else:
                logging.error(f"Failed to upload signup standards document to blob: {pending_standards_filename}")
                
        except Exception as e:
            logging.error(f"Failed to process signup standards document {pending_standards_filename}: {e}", exc_info=True)

    return JSONResponse({"message": "User registration submitted. Awaiting admin approval."}, status_code=201)


# ── Login / Logout / User ─────────────────────────────────────────────────────

import time as _time

@blueprint.post("/login")
async def login(request: Request):
    session = get_session(request)
    try:
        data = await request.json()
    except Exception:
        data = {}
    username = data.get("username")
    password = data.get("password")

    try:
        user = db.session.query(User).filter_by(username=username).first()
    except Exception as db_err:
        logging.error(f"[LOGIN] Database unavailable: {db_err}")
        return JSONResponse({"error": "Authentication service temporarily unavailable. Please try again later."}, status_code=503)

    if not user:
        return JSONResponse({"error": "No account found with that username. Please register."}, status_code=404)
    if not user.password_hash:
        return JSONResponse({"error": "Account has no password set. Please reset your password."}, status_code=401)
    try:
        password_ok = check_password(user.password_hash, password)
    except Exception as pw_err:
        logging.error(f"[LOGIN] Password check error for {username}: {pw_err}")
        return JSONResponse({"error": "Authentication error. Please contact support."}, status_code=500)
    if not password_ok:
        return JSONResponse({"error": "Incorrect password."}, status_code=401)
    if user.status != "active":
        return JSONResponse({"error": f"Account not active. Current status: {user.status}."}, status_code=403)

    session.clear()
    session["user_id"] = user.id
    session["user_role"] = user.role

    jwt_token = generate_jwt_token(user.id, user.username)

    session_id = request.headers.get("x-session-id") or f"sess_{user.id}_{int(_time.time())}"
    session["session_id"] = session_id
    
    try:
        from common.monitoring.usage import session_analytics
        session_analytics.start_session(
            user_id=str(user.id),
            session_id=str(session_id),
            request_data={
                "remote_addr": request.headers.get("x-forwarded-for") or "127.0.0.1",
                "user_agent": request.headers.get("User-Agent"),
                "referer": request.headers.get("Referer", ""),
                "origin": request.headers.get("Origin", "")
            }
        )
    except Exception as e:
        logging.error(f"[TRACKING] Failed to start log session: {e}")

    full_name = " ".join(filter(None, [user.first_name, user.last_name])) or user.username

    return JSONResponse({"message": "Login successful", "token": jwt_token, "user": {"username": user.username, "name": full_name, "first_name": user.first_name, "last_name": user.last_name, "email": user.email, "role": user.role, "company": user.company, "location": user.location}}, status_code=200)


@blueprint.post("/logout")
async def logout(request: Request):
    session = get_session(request)
    user_id = session.get("user_id")
    session_id = None or session.get("_id")
    session.pop("user_id", None)

    if user_id and session_id:
        try:
            from common.monitoring.usage import session_analytics
            session_analytics.end_session(user_id=str(user_id), session_id=str(session_id))
        except Exception as e:
            logging.error(f"[TRACKING] Failed to end session: {e}")

    return JSONResponse({"message": "Logout successful"}, status_code=200)


@blueprint.get("/user")
@login_required
async def get_user_profile(request: Request):
    # Use JWT-validated user_id (from @login_required) instead of AzureSession,
    # which may be empty when a new tab opens without an x-session-id header.
    from app.dependencies.auth import get_current_user
    validation = get_current_user(request)
    user_id = validation.get("user_id")

    # Fallback to session only if JWT didn't provide user_id
    if not user_id:
        session = get_session(request)
        user_id = session.get("user_id")

    if not user_id:
        return JSONResponse({"error": "User not found"}, status_code=404)

    user = db.session.get(User, user_id)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    full_name = " ".join(filter(None, [user.first_name, user.last_name])) or user.username

    return JSONResponse({"user": {"username": user.username, "name": full_name, "first_name": user.first_name, "last_name": user.last_name, "email": user.email, "role": user.role, "company": user.company, "location": user.location}}, status_code=200)


# ── Update Profile ────────────────────────────────────────────────────────────

@blueprint.post("/api/update_profile")
@login_required
async def api_update_profile(request: Request):
    session = get_session(request)
    """Updates the user's profile (first name, last name, username, files)."""
    try:
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            data = await request.form()
            strategy_files = [f for f in data.getlist("document") if f and f.filename]
            standards_files = [f for f in data.getlist("standards_document") if f and f.filename]
            assets_files = [f for f in data.getlist("assets_document") if f and f.filename]
        else:
            try:
                data = await request.json()
            except Exception:
                data = {}
            strategy_files = []
            standards_files = []
            assets_files = []

        user_id = session.get("user_id")
        user = db.session.get(User, user_id)
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)

        for field, attr in [("first_name", "first_name"), ("last_name", "last_name"), ("company", "company"), ("location", "location")]:
            val = data.get(field)
            if val is not None:
                setattr(user, attr, val.strip())

        username = data.get("username")
        if username is not None:
            new_username = username.strip()
            if new_username and new_username != user.username:
                if db.session.query(User).filter_by(username=new_username).first():
                    return JSONResponse({"error": "Username already taken"}, status_code=400)
                user.username = new_username

        strategy_file_uploaded = False
        strategy_files_uploaded_count = 0
        if strategy_files:
            try:
                for file in strategy_files:
                    filename = _safe_secure_filename(file.filename)
                    file_data = await file.read()

                    # Process strategy upload synchronously
                    try:
                        process_strategy_upload(file_data, filename, user_id)
                        strategy_files_uploaded_count += 1
                    except Exception as e:
                        logging.error(f"Strategy extraction error for {filename}: {e}")

                strategy_file_uploaded = strategy_files_uploaded_count > 0
            except Exception as e:
                logging.error(f"Failed to queue strategy document: {e}")

        standards_file_uploaded = False
        standards_files_uploaded_count = 0
        if standards_files:
            try:
                from common.infra.azure_blob import azure_blob_manager
                from app.services.upload_service import extract_and_store_standards_text
                
                for standards_file in standards_files:
                    validation = validate_uploaded_file(standards_file, allowed_extensions=['.pdf', '.docx', '.doc', '.txt'])
                    if not validation["valid"]:
                        return JSONResponse({"error": validation["error"]}, status_code=400)

                    standards_filename = validation["filename"]
                    standards_file_data = await standards_file.read()
                    content_type = standards_file.content_type or "application/pdf"

                    logging.info(f"[AUTH] Processing profile update standards document: {standards_filename}")
                    
                    # Upload to blob storage
                    blob_info = azure_blob_manager.upload_standards_document(
                        file_bytes=standards_file_data,
                        filename=standards_filename,
                        user_id=user_id,
                        content_type=content_type,
                    )
                    
                    blob_url = blob_info.get('blobUrl') if blob_info else None
                    if blob_url:
                        # Process synchronously
                        result = extract_and_store_standards_text(
                            standards_file_data, 
                            standards_filename, 
                            user_id, 
                            blob_url
                        )
                        if result.get("success"):
                            standards_files_uploaded_count += 1
                            logging.info(f"Successfully processed profile update standards document: {standards_filename}")
                        else:
                            logging.error(f"Failed to process standards document {standards_filename}: {result.get('error')}")
                    else:
                        logging.error(f"Failed to upload standards document to blob: {standards_filename}")

                standards_file_uploaded = standards_files_uploaded_count > 0
            except Exception as e:
                logging.error(f"Failed to process standards documents: {e}")

        assets_file_uploaded = False
        assets_files_uploaded_count = 0
        if assets_files:
            try:
                for assets_file in assets_files:
                    assets_filename = _safe_secure_filename(assets_file.filename)
                    assets_file_data = await assets_file.read()

                    # Process assets upload synchronously
                    try:
                        process_assets_upload(assets_file_data, assets_filename, user_id)
                        assets_files_uploaded_count += 1
                    except Exception as e:
                        logging.error(f"Assets extraction error for {assets_filename}: {e}")

                assets_file_uploaded = assets_files_uploaded_count > 0
            except Exception as e:
                logging.error(f"Failed to queue assets document: {e}")

        db.session.commit()

        message_parts = ["Profile updated successfully"]
        if strategy_file_uploaded:
            message_parts.append(f"{strategy_files_uploaded_count} strategy file(s) processed successfully")
        if standards_file_uploaded:
            message_parts.append(f"{standards_files_uploaded_count} standards file(s) processed successfully")
        if assets_file_uploaded:
            message_parts.append(f"{assets_files_uploaded_count} assets file(s) processed successfully")

        response_data = {"success": True, "message": ". ".join(message_parts) + ".", "user": {"first_name": user.first_name, "last_name": user.last_name, "username": user.username, "company": user.company, "location": user.location}}
        if strategy_file_uploaded:
            response_data["strategy_extraction"] = {"status": "completed", "message": "Strategy file processed successfully."}

        return JSONResponse(response_data, status_code=200)

    except Exception as e:
        logging.exception("Profile update failed.")
        return JSONResponse({"error": str(e)}, status_code=500)
