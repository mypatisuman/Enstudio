from datetime import datetime
from app.models.db.base import db

class MarketplaceTenant(db.Model):
    __tablename__ = 'marketplace_tenants'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    subscription_name = db.Column(db.String(255), nullable=True)
    offer_id = db.Column(db.String(100), nullable=False)
    plan_id = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)

    status = db.Column(db.String(50), default='pending', nullable=False, index=True)

    beneficiary_email = db.Column(db.String(255), nullable=True)
    beneficiary_tenant_id = db.Column(db.String(255), nullable=True)
    purchaser_email = db.Column(db.String(255), nullable=True)
    purchaser_tenant_id = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    activated_at = db.Column(db.DateTime, nullable=True)
    suspended_at = db.Column(db.DateTime, nullable=True)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)
    last_modified = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    monthly_ai_recommendations = db.Column(db.Integer, default=0, nullable=False)
    billing_period_start = db.Column(db.DateTime, nullable=True)
    billing_period_end = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'subscription_id': self.subscription_id,
            'subscription_name': self.subscription_name,
            'offer_id': self.offer_id,
            'plan_id': self.plan_id,
            'quantity': self.quantity,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'last_modified': self.last_modified.isoformat() if self.last_modified else None
        }


class MarketplaceAuditLog(db.Model):
    __tablename__ = 'marketplace_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.String(255), nullable=False, index=True)
    event_type = db.Column(db.String(100), nullable=False, index=True)  
    event_data = db.Column(db.Text, nullable=True)  
    status = db.Column(db.String(50), nullable=False)  
    error_message = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'subscription_id': self.subscription_id,
            'event_type': self.event_type,
            'status': self.status,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }
