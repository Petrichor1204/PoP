import json
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    Text,
    DateTime,
    func,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from werkzeug.security import generate_password_hash, check_password_hash
from utils import validate_preferences, validate_decision

DB_NAME = "my_database.db"  # used as SQLite fallback in dev/tests


def get_database_url():
    url = os.getenv("DATABASE_URL")
    if url:
        # Render (and older Heroku) give postgres:// — SQLAlchemy needs postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    return f"sqlite:///{DB_NAME}"

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(200), unique=True, nullable=True)
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime, nullable=True)

    profiles = relationship("PreferenceProfile", back_populates="user", cascade="all, delete-orphan")
    decisions = relationship("Decision", back_populates="user", cascade="all, delete-orphan")


class PreferenceProfile(Base):
    __tablename__ = "preference_profiles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    likes = Column(Text, nullable=False)
    dislikes = Column(Text, nullable=False)
    pace = Column(String(50), nullable=False)
    emotional_tolerance = Column(String(50), nullable=False)
    goal = Column(String(100), nullable=False)
    updated_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=False)

    user = relationship("User", back_populates="profiles")
    decisions = relationship("Decision", back_populates="profile", cascade="all, delete-orphan")


class Decision(Base):
    __tablename__ = "decisions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    profile_id = Column(Integer, ForeignKey("preference_profiles.id"), nullable=True)
    item_title = Column(String(200), nullable=False)
    item_type = Column(String(20), nullable=False)
    verdict = Column(String(10), nullable=False)
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    potential_mismatches = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="decisions")
    profile = relationship("PreferenceProfile", back_populates="decisions")


class AiCache(Base):
    __tablename__ = "ai_cache"
    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(255), unique=True, nullable=False)
    response_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)


def get_engine():
    url = get_database_url()
    # connect_args is SQLite-only; Postgres doesn't accept it
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


def get_session():
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)


def create_user(username, email=None, password_hash=None):
    session = get_session()
    try:
        user = User(username=username, email=email, password_hash=password_hash)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def get_user_by_username(username):
    session = get_session()
    try:
        return session.query(User).filter(User.username == username).first()
    finally:
        session.close()


def set_last_login(user_id):
    session = get_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        user.last_login_at = datetime.now(timezone.utc)
        session.commit()
        return True
    finally:
        session.close()


def hash_password(password):
    return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def get_user(user_id):
    session = get_session()
    try:
        return session.query(User).filter(User.id == user_id).first()
    finally:
        session.close()


def list_profiles(user_id):
    session = get_session()
    try:
        profiles = session.query(PreferenceProfile).filter(PreferenceProfile.user_id == user_id).all()
        return [_profile_to_dict(p) for p in profiles]
    finally:
        session.close()


def set_active_profile(user_id, profile_id):
    session = get_session()
    try:
        profiles = session.query(PreferenceProfile).filter(PreferenceProfile.user_id == user_id).all()
        target = None
        for profile in profiles:
            if profile.id == profile_id:
                target = profile
                profile.is_active = True
            else:
                profile.is_active = False
        if not target:
            return False
        session.commit()
        return True
    finally:
        session.close()


def save_preferences(preferences, user_id, profile_name="default"):
    is_valid, error = validate_preferences(preferences)
    if not is_valid:
        print(f"Preferences invalid, not able to save: {error}")
        return False

    session = get_session()
    try:
        profile = (
            session.query(PreferenceProfile)
            .filter(PreferenceProfile.user_id == user_id, PreferenceProfile.name == profile_name)
            .first()
        )
        if not profile:
            profile = PreferenceProfile(user_id=user_id, name=profile_name)
            session.add(profile)

        profile.likes = json.dumps(preferences["likes"])
        profile.dislikes = json.dumps(preferences["dislikes"])
        profile.pace = preferences["pace"]
        profile.emotional_tolerance = preferences["emotional_tolerance"]
        profile.goal = preferences["goal"]
        profile.updated_at = datetime.fromisoformat(preferences["updated_at"])

        # Set this profile active; deactivate others
        session.query(PreferenceProfile).filter(PreferenceProfile.user_id == user_id).update({"is_active": False})
        profile.is_active = True

        session.commit()
        return True
    except Exception as e:
        print(f"Error saving preferences: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def get_preferences(user_id):
    session = get_session()
    try:
        profile = (
            session.query(PreferenceProfile)
            .filter(PreferenceProfile.user_id == user_id, PreferenceProfile.is_active.is_(True))
            .first()
        )
        if not profile:
            return None
        return _profile_to_dict(profile)
    finally:
        session.close()


def delete_preferences(user_id, profile_id=None):
    session = get_session()
    try:
        query = session.query(PreferenceProfile).filter(PreferenceProfile.user_id == user_id)
        if profile_id:
            query = query.filter(PreferenceProfile.id == profile_id)
        else:
            query = query.filter(PreferenceProfile.is_active.is_(True))
        profile = query.first()
        if not profile:
            return False
        session.delete(profile)
        session.commit()
        return True
    finally:
        session.close()


def save_decision(decision, user_id, profile_id=None):
    if not validate_decision(decision):
        print("Decision is invalid, not saving.")
        return False

    session = get_session()
    try:
        record = Decision(
            user_id=user_id,
            profile_id=profile_id,
            item_title=decision["item_title"],
            item_type=decision["item_type"],
            verdict=decision["verdict"],
            confidence=decision["confidence"],
            reasoning=decision["reasoning"],
            potential_mismatches=json.dumps(decision["potential_mismatches"], ensure_ascii=False),
            created_at=datetime.fromisoformat(decision["created_at"]),
        )
        session.add(record)
        session.commit()
        return True
    except Exception as e:
        print(f"Error saving decision: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def get_recent_decisions(user_id, limit=5, offset=0, item_type=None, verdict=None, start=None, end=None):
    session = get_session()
    try:
        query = session.query(Decision).filter(Decision.user_id == user_id)
        if item_type:
            query = query.filter(Decision.item_type == item_type)
        if verdict:
            query = query.filter(Decision.verdict == verdict)
        if start:
            query = query.filter(Decision.created_at >= start)
        if end:
            query = query.filter(Decision.created_at <= end)

        total = query.with_entities(func.count(Decision.id)).scalar() or 0
        rows = (
            query.order_by(Decision.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        decisions = []
        for row in rows:
            decisions.append(_decision_to_dict(row))

        return decisions, total
    finally:
        session.close()


def get_ai_cache(cache_key, now):
    session = get_session()
    try:
        row = session.query(AiCache).filter(AiCache.cache_key == cache_key).first()
        if not row:
            return None
        if row.expires_at <= now:
            session.delete(row)
            session.commit()
            return None
        return json.loads(row.response_json)
    finally:
        session.close()


def set_ai_cache(cache_key, response_dict, now, ttl_seconds):
    session = get_session()
    try:
        expires_at = now + timedelta(seconds=ttl_seconds)
        row = session.query(AiCache).filter(AiCache.cache_key == cache_key).first()
        if not row:
            row = AiCache(cache_key=cache_key)
            session.add(row)
        row.response_json = json.dumps(response_dict, ensure_ascii=False)
        row.created_at = now
        row.expires_at = expires_at
        session.commit()
        return True
    finally:
        session.close()


def _profile_to_dict(profile):
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "name": profile.name,
        "likes": json.loads(profile.likes),
        "dislikes": json.loads(profile.dislikes),
        "pace": profile.pace,
        "emotional_tolerance": profile.emotional_tolerance,
        "goal": profile.goal,
        "updated_at": profile.updated_at.isoformat(),
        "is_active": profile.is_active,
    }


def _decision_to_dict(row):
    return {
        "id": row.id,
        "user_id": row.user_id,
        "profile_id": row.profile_id,
        "item_title": row.item_title,
        "item_type": row.item_type,
        "verdict": row.verdict,
        "confidence": row.confidence,
        "reasoning": row.reasoning,
        "potential_mismatches": json.loads(row.potential_mismatches),
        "created_at": row.created_at.isoformat(),
    }
