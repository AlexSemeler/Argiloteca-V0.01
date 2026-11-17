"""Additive administrative journal; native records remain in Invenio tables."""
from datetime import datetime, timezone
import uuid
from invenio_db import db


def now():
    return datetime.now(timezone.utc)


class OpenAlexJob(db.Model):
    __tablename__ = 'argiloteca_openalex_job'
    id = db.Column(db.String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    kind = db.Column(db.String(20), nullable=False)
    state = db.Column(db.String(24), nullable=False, default='queued', index=True)
    actor = db.Column(db.Integer, nullable=False)
    created = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    updated = db.Column(db.DateTime(timezone=True), nullable=False, default=now, onupdate=now)
    params = db.Column(db.JSON, nullable=False, default=dict)
    snapshot = db.Column(db.JSON, nullable=False, default=dict)
    result = db.Column(db.JSON, nullable=False, default=dict)


class OpenAlexClaim(db.Model):
    __tablename__ = 'argiloteca_openalex_claim'
    token = db.Column(db.String(1024), primary_key=True)
    draft_id = db.Column(db.String(32), nullable=False)
    job_id = db.Column(db.String(32), nullable=False)
    payload_sha256 = db.Column(db.String(64), nullable=False)
    created = db.Column(db.DateTime(timezone=True), nullable=False, default=now)


class OpenAlexAnalyticHead(db.Model):
    """One transactionally activated pointer; immutable versions live privately."""
    __tablename__ = 'argiloteca_openalex_analytic_head'
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(32), nullable=True)


def install_tables():
    for model in (OpenAlexJob, OpenAlexClaim, OpenAlexAnalyticHead):
        model.__table__.create(db.engine, checkfirst=True)
    from sqlalchemy.dialects.postgresql import insert
    db.session.execute(insert(OpenAlexAnalyticHead).values(id=1).on_conflict_do_nothing(index_elements=['id']))
    db.session.commit()
