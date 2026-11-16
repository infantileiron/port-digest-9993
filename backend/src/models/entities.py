from sqlalchemy import Column,Integer,String,Float,JSON,Text,Boolean,ForeignKey,UniqueConstraint
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True,nullable=False);password=Column(String(200));role=Column(String(20))
class Arrival(Base):
 __tablename__='arrivals'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);station=Column(String(30));planned_at=Column(String(40));actual_at=Column(String(40),nullable=True);note=Column(Text,default='');revision=Column(Integer,default=0,nullable=False)
class Subscription(Base):
 __tablename__='subscriptions'
 id=Column(Integer,primary_key=True);name=Column(String(100),unique=True,nullable=False);station=Column(String(30));daily_at=Column(String(5));recipient=Column(String(80));enabled=Column(Boolean,default=False);next_run_at=Column(String(40));last_run_at=Column(String(40),nullable=True)
class Manifest(Base):
 __tablename__='manifests'
 __table_args__=(UniqueConstraint('station','report_day','version',name='uq_manifest_station_day_version'),)
 id=Column(Integer,primary_key=True);station=Column(String(30),nullable=False);report_day=Column(String(10),nullable=False);version=Column(Integer,nullable=False);status=Column(String(20),default='pending');items=Column(JSON);checksum=Column(String(64));item_count=Column(Integer,default=0);note=Column(Text,default='');created_by=Column(String(100));created_at=Column(String(40));reconciled_at=Column(String(40),nullable=True)
class Reconciliation(Base):
 __tablename__='reconciliations'
 id=Column(Integer,primary_key=True);manifest_id=Column(Integer,ForeignKey('manifests.id'),nullable=False);station=Column(String(30));report_day=Column(String(10));manifest_version=Column(Integer);status=Column(String(20));manifest_checksum=Column(String(64));ledger_checksum=Column(String(64));manifest_total=Column(Integer,default=0);ledger_total=Column(Integer,default=0);matched=Column(Integer,default=0);completed=Column(Integer,default=0);missing=Column(Integer,default=0);pending=Column(Integer,default=0);unplanned=Column(Integer,default=0);balanced=Column(Boolean,default=False);details=Column(JSON);checked_by=Column(String(100));checked_at=Column(String(40));invalidated_at=Column(String(40),nullable=True);invalid_reason=Column(String(200),default='')
class DistributionGate(Base):
 __tablename__='distribution_gates'
 __table_args__=(UniqueConstraint('subscription_id','report_day',name='uq_gate_subscription_day'),)
 id=Column(Integer,primary_key=True);subscription_id=Column(Integer,ForeignKey('subscriptions.id'),nullable=False);report_day=Column(String(10),nullable=False);state=Column(String(20),default='waiting');reason=Column(String(300),default='');blocking=Column(JSON);attempts=Column(Integer,default=0);receipt_id=Column(Integer,nullable=True);first_blocked_at=Column(String(40),nullable=True);last_checked_at=Column(String(40),nullable=True);updated_at=Column(String(40),nullable=True)
class DayLock(Base):
 __tablename__='day_locks'
 __table_args__=(UniqueConstraint('station','report_day',name='uq_day_lock_station_day'),)
 id=Column(Integer,primary_key=True);station=Column(String(30),nullable=False);report_day=Column(String(10),nullable=False)
class Receipt(Base):
 __tablename__='receipts'
 __table_args__=(UniqueConstraint('subscription_id','report_day',name='uq_receipt_subscription_day'),)
 id=Column(Integer,primary_key=True);subscription_id=Column(Integer,ForeignKey('subscriptions.id'));report_day=Column(String(10));recipient=Column(String(80));created_at=Column(String(40));state=Column(String(20),default='delivered');payload=Column(JSON);review_note=Column(Text,default='')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
